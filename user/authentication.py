from rest_framework_simplejwt.authentication import JWTAuthentication
from rest_framework_simplejwt.exceptions import InvalidToken, AuthenticationFailed

from .models import AdminDesktopUser, ShopOwner


class ShopOwnerJWTAuthentication(JWTAuthentication):
    """
    Custom JWT authentication for all project roles.
    Enforces strict role->id mapping to prevent cross-role access.
    """

    def get_user(self, validated_token):
        user_type = validated_token.get('user_type')
        if not user_type:
            raise InvalidToken('Token missing user_type')

        if user_type == 'customer':
            customer_id = validated_token.get('customer_id')
            if not customer_id:
                raise InvalidToken('Customer token missing customer_id')
            try:
                from shop.models import Customer

                customer = Customer.objects.get(id=customer_id)
                customer.user_type = 'customer'
                return customer
            except Customer.DoesNotExist as exc:
                raise AuthenticationFailed('Customer not found') from exc

        if user_type == 'employee':
            employee_id = validated_token.get('employee_id')
            if not employee_id:
                raise InvalidToken('Employee token missing employee_id')
            try:
                from shop.models import Employee

                employee = Employee.objects.get(id=employee_id, is_active=True)
                employee.user_type = 'employee'
                return employee
            except Employee.DoesNotExist as exc:
                raise AuthenticationFailed('Employee not found or inactive') from exc

        if user_type == 'driver':
            driver_id = validated_token.get('driver_id')
            if not driver_id:
                raise InvalidToken('Driver token missing driver_id')
            try:
                from shop.models import Driver

                driver = Driver.objects.get(id=driver_id)
                driver.user_type = 'driver'
                return driver
            except Driver.DoesNotExist as exc:
                raise AuthenticationFailed('Driver not found') from exc

        if user_type == 'shop_owner':
            # Legacy compatibility for owner tokens generated with for_user().
            shop_owner_id = validated_token.get('shop_owner_id') or validated_token.get('user_id')
            if not shop_owner_id:
                raise InvalidToken('Shop owner token missing shop_owner_id')
            try:
                shop_owner = ShopOwner.objects.get(id=shop_owner_id, is_active=True)
                shop_owner.user_type = 'shop_owner'
                return shop_owner
            except ShopOwner.DoesNotExist as exc:
                raise AuthenticationFailed('Shop owner not found or inactive') from exc

        if user_type == 'admin_desktop':
            admin_desktop_user_id = validated_token.get('admin_desktop_user_id')
            if not admin_desktop_user_id:
                raise InvalidToken('Admin desktop token missing admin_desktop_user_id')
            try:
                admin_user = AdminDesktopUser.objects.get(id=admin_desktop_user_id, is_active=True)
                admin_user.user_type = 'admin_desktop'
                return admin_user
            except AdminDesktopUser.DoesNotExist as exc:
                raise AuthenticationFailed('Admin desktop user not found or inactive') from exc

        raise InvalidToken('Unsupported user_type in token')
