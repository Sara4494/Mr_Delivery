"""
Custom permissions for role-based access control.
"""

from rest_framework.permissions import BasePermission

from user.maintenance_exceptions import MaintenanceModeError
from user.account_status import ensure_account_is_active
from user.models import AppMaintenanceSettings, ShopOwner
from user.utils import t

from ..models import Customer, Driver, Employee


def _ensure_active_account(request, user):
    if not user or not getattr(user, "is_authenticated", False):
        return
    ensure_account_is_active(user, request=request)


def _token_user_type(request):
    token = getattr(request, "auth", None)
    if token is None:
        return None
    try:
        return token.get("user_type")
    except Exception:
        return None


def _request_platform(request):
    for key in ("platform",):
        value = request.query_params.get(key) if hasattr(request, "query_params") else None
        normalized = AppMaintenanceSettings.normalize_platform(value)
        if normalized:
            return normalized

    headers = getattr(request, "headers", None) or {}
    for key in ("platform", "x-platform", "x-app-platform"):
        normalized = AppMaintenanceSettings.normalize_platform(headers.get(key))
        if normalized:
            return normalized

    meta = getattr(request, "META", None) or {}
    for key in ("HTTP_PLATFORM", "HTTP_X_PLATFORM", "HTTP_X_APP_PLATFORM"):
        normalized = AppMaintenanceSettings.normalize_platform(meta.get(key))
        if normalized:
            return normalized
    return None


def _resolve_maintenance_user_type(request):
    token_user_type = AppMaintenanceSettings.normalize_user_type(_token_user_type(request))
    if token_user_type:
        return token_user_type

    user = getattr(request, "user", None)
    user_type = AppMaintenanceSettings.normalize_user_type(getattr(user, "user_type", None))
    if user_type:
        return user_type

    if isinstance(user, Customer):
        return "customer"
    if isinstance(user, Driver):
        return "driver"
    if isinstance(user, (ShopOwner, Employee)):
        return "shop_owner"
    return None


class EnsureActiveAccountPermission(BasePermission):
    def has_permission(self, request, view):
        user = getattr(request, "user", None)
        if not user or not getattr(user, "is_authenticated", False):
            return True
        _ensure_active_account(request, user)
        return True


class MaintenanceModePermission(BasePermission):
    def has_permission(self, request, view):
        path = str(getattr(request, "path", "") or "")
        if path.rstrip("/") == "/api/app/status":
            return True

        if request.method == "OPTIONS":
            return True

        user = getattr(request, "user", None)
        if not user or not getattr(user, "is_authenticated", False):
            return True

        maintenance = AppMaintenanceSettings.get_solo()
        if not maintenance.is_live():
            return True

        user_type = _resolve_maintenance_user_type(request)
        platform = _request_platform(request)
        if not maintenance.matches_target(user_type=user_type, platform=platform):
            return True

        detail = t(
            request,
            "app_under_maintenance_detail",
            default=(
                "The app is currently under maintenance. Please try again later."
                if str(getattr(request, "LANGUAGE_CODE", "")).lower() == "en"
                else "التطبيق تحت الصيانة حاليًا. يرجى المحاولة لاحقًا."
            ),
        )
        exc = MaintenanceModeError(detail=detail)
        exc.retry_after_seconds = maintenance.retry_after_seconds
        raise exc


class IsShopOwner(BasePermission):
    message = "This action is available only for shop owner."

    def has_permission(self, request, view):
        self.message = t(request, "permission_only_shop_owner")
        user = request.user
        if not user or not user.is_authenticated:
            return False
        _ensure_active_account(request, user)

        token_user_type = _token_user_type(request)
        if token_user_type and token_user_type != "shop_owner":
            return False

        if getattr(user, "user_type", None) == "shop_owner":
            return True
        return isinstance(user, ShopOwner)


class IsCustomer(BasePermission):
    message = "This action is available only for customers."

    def has_permission(self, request, view):
        self.message = t(request, "permission_only_customers")
        user = request.user
        if not user or not user.is_authenticated:
            return False
        _ensure_active_account(request, user)

        token_user_type = _token_user_type(request)
        if token_user_type and token_user_type != "customer":
            return False

        if getattr(user, "user_type", None) == "customer":
            return True
        return isinstance(user, Customer)


class IsEmployee(BasePermission):
    message = "This action is available only for employees."

    def has_permission(self, request, view):
        self.message = t(request, "permission_only_employees")
        user = request.user
        if not user or not user.is_authenticated:
            return False
        _ensure_active_account(request, user)

        token_user_type = _token_user_type(request)
        if token_user_type and token_user_type != "employee":
            return False

        if getattr(user, "user_type", None) == "employee":
            return True
        return isinstance(user, Employee)


class IsDriver(BasePermission):
    message = "This action is available only for drivers."

    def has_permission(self, request, view):
        self.message = t(request, "permission_only_drivers")
        user = request.user
        if not user or not user.is_authenticated:
            return False
        _ensure_active_account(request, user)

        token_user_type = _token_user_type(request)
        if token_user_type and token_user_type != "driver":
            return False

        if getattr(user, "user_type", None) == "driver":
            return True
        return isinstance(user, Driver)


class IsShopOwnerOrEmployee(BasePermission):
    message = "This action is available only for shop owner or employees."

    def has_permission(self, request, view):
        self.message = t(request, "permission_only_shop_owner_or_employees")
        user = request.user
        if not user or not user.is_authenticated:
            return False
        _ensure_active_account(request, user)

        token_user_type = _token_user_type(request)
        if token_user_type and token_user_type not in {"shop_owner", "employee"}:
            return False

        user_type = getattr(user, "user_type", None)
        if user_type in {"shop_owner", "employee"}:
            return True
        return isinstance(user, (ShopOwner, Employee))


class IsShopStaff(BasePermission):
    message = "This action is available only for shop staff."

    def has_permission(self, request, view):
        self.message = t(request, "permission_only_shop_staff")
        user = request.user
        if not user or not user.is_authenticated:
            return False
        _ensure_active_account(request, user)

        token_user_type = _token_user_type(request)
        if token_user_type and token_user_type not in {"shop_owner", "employee", "driver"}:
            return False

        user_type = getattr(user, "user_type", None)
        if user_type in {"shop_owner", "employee", "driver"}:
            return True
        return isinstance(user, (ShopOwner, Employee, Driver))
