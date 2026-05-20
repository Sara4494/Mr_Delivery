import secrets

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.conf import settings
from rest_framework_simplejwt.authentication import JWTAuthentication
from rest_framework_simplejwt.exceptions import AuthenticationFailed, InvalidToken
from rest_framework_simplejwt.tokens import RefreshToken

from .account_status import ensure_account_is_active
from .models import AdminDesktopUser, ShopOwner


def _session_access_lifetime():
    return getattr(settings, "SESSION_ACCESS_TOKEN_LIFETIME", None)


def _session_refresh_lifetime():
    return getattr(settings, "SESSION_REFRESH_TOKEN_LIFETIME", None)


def generate_admin_desktop_session_key():
    return secrets.token_hex(24)


def rotate_user_session(user):
    user.active_session_key = generate_admin_desktop_session_key()
    return user.active_session_key


def get_socket_session_group_name(user_type, user_id):
    return f"session_{str(user_type).strip()}_{int(user_id)}"


def notify_session_revoked(user, user_type):
    channel_layer = get_channel_layer()
    if not channel_layer or not getattr(user, "id", None):
        return

    async_to_sync(channel_layer.group_send)(
        get_socket_session_group_name(user_type, user.id),
        {
            "type": "auth.session_revoked",
            "session_key": str(getattr(user, "active_session_key", "") or "").strip(),
            "user_type": str(user_type or "").strip(),
        },
    )


def apply_session_token_lifetimes(refresh_token):
    refresh_lifetime = _session_refresh_lifetime()
    if refresh_lifetime:
        refresh_token.set_exp(lifetime=refresh_lifetime)

    access_token = refresh_token.access_token
    access_lifetime = _session_access_lifetime()
    if access_lifetime:
        access_token.set_exp(lifetime=access_lifetime)
    return access_token


def validate_user_session_token(validated_token, user):
    token_session_key = str(validated_token.get("session_key") or "").strip()
    active_session_key = str(getattr(user, "active_session_key", "") or "").strip()

    if not token_session_key or not active_session_key or token_session_key != active_session_key:
        raise InvalidToken("User session is no longer active")


def build_session_refresh_token(*, user, user_type, extra_claims=None):
    refresh = RefreshToken()
    user_type = str(user_type or "").strip()
    if user_type == "customer":
        refresh["customer_id"] = user.id
        refresh["phone_number"] = getattr(user, "phone_number", None)
        refresh["email"] = getattr(user, "email", None)
    elif user_type == "employee":
        refresh["employee_id"] = user.id
        refresh["phone_number"] = getattr(user, "phone_number", None)
        refresh["shop_owner_id"] = getattr(user, "shop_owner_id", None)
        refresh["role"] = getattr(user, "role", None)
    elif user_type == "driver":
        refresh["driver_id"] = user.id
        refresh["phone_number"] = getattr(user, "phone_number", None)
    elif user_type == "shop_owner":
        refresh["shop_owner_id"] = user.id
        refresh["shop_number"] = getattr(user, "shop_number", None)
        refresh["shop_name"] = getattr(user, "shop_name", None)
        refresh["shop_category_id"] = getattr(user, "shop_category_id", None)
        refresh["shop_category_name"] = getattr(getattr(user, "shop_category", None), "name", None)
    elif user_type == "admin_desktop":
        refresh["admin_desktop_user_id"] = user.id
        refresh["phone_number"] = getattr(user, "phone_number", None)
        refresh["role"] = getattr(user, "role", None)
        permissions = getattr(user, "get_resolved_permissions", lambda: [])()
        refresh["permissions"] = permissions
    else:
        raise InvalidToken(f"Unsupported user_type for session token: {user_type}")

    refresh["user_type"] = user_type
    refresh["session_key"] = str(getattr(user, "active_session_key", "") or "").strip()
    for key, value in (extra_claims or {}).items():
        refresh[key] = value
    return refresh


class ShopOwnerJWTAuthentication(JWTAuthentication):
    """
    Custom JWT authentication for all project roles.
    Enforces strict role->id mapping to prevent cross-role access.
    """

    def get_user(self, validated_token):
        user_type = validated_token.get("user_type")
        if not user_type:
            raise InvalidToken("Token missing user_type")

        if user_type == "customer":
            customer_id = validated_token.get("customer_id")
            if not customer_id:
                raise InvalidToken("Customer token missing customer_id")
            try:
                from shop.models import Customer

                customer = Customer.objects.get(id=customer_id)
                validate_user_session_token(validated_token, customer)
                customer.user_type = "customer"
                return ensure_account_is_active(customer)
            except Customer.DoesNotExist as exc:
                raise AuthenticationFailed("Customer not found") from exc

        if user_type == "employee":
            employee_id = validated_token.get("employee_id")
            if not employee_id:
                raise InvalidToken("Employee token missing employee_id")
            try:
                from shop.models import Employee

                employee = Employee.objects.get(id=employee_id)
                validate_user_session_token(validated_token, employee)
                employee.user_type = "employee"
                return ensure_account_is_active(employee)
            except Employee.DoesNotExist as exc:
                raise AuthenticationFailed("Employee not found or inactive") from exc

        if user_type == "driver":
            driver_id = validated_token.get("driver_id")
            if not driver_id:
                raise InvalidToken("Driver token missing driver_id")
            try:
                from shop.models import Driver

                driver = Driver.objects.get(id=driver_id)
                validate_user_session_token(validated_token, driver)
                driver.user_type = "driver"
                return ensure_account_is_active(driver)
            except Driver.DoesNotExist as exc:
                raise AuthenticationFailed("Driver not found") from exc

        if user_type == "shop_owner":
            shop_owner_id = validated_token.get("shop_owner_id") or validated_token.get("user_id")
            if not shop_owner_id:
                raise InvalidToken("Shop owner token missing shop_owner_id")
            try:
                shop_owner = ShopOwner.objects.get(id=shop_owner_id)
                validate_user_session_token(validated_token, shop_owner)
                shop_owner.user_type = "shop_owner"
                return ensure_account_is_active(shop_owner)
            except ShopOwner.DoesNotExist as exc:
                raise AuthenticationFailed("Shop owner not found or inactive") from exc

        if user_type == "admin_desktop":
            admin_desktop_user_id = validated_token.get("admin_desktop_user_id")
            if not admin_desktop_user_id:
                raise InvalidToken("Admin desktop token missing admin_desktop_user_id")
            try:
                admin_user = AdminDesktopUser.objects.get(id=admin_desktop_user_id)
                validate_user_session_token(validated_token, admin_user)
                admin_user.user_type = "admin_desktop"
                return ensure_account_is_active(admin_user)
            except AdminDesktopUser.DoesNotExist as exc:
                raise AuthenticationFailed("Admin desktop user not found or inactive") from exc

        raise InvalidToken("Unsupported user_type in token")
