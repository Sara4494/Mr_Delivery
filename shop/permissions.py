"""
Custom permissions for role-based access control.
"""

from rest_framework.permissions import BasePermission

from user.models import ShopOwner
from user.utils import t
from .models import Customer, Employee, Driver


def _is_suspended_user(user):
    if isinstance(user, ShopOwner):
        return getattr(user, 'admin_status', None) == 'suspended' or not getattr(user, 'is_active', True)

    if isinstance(user, Customer):
        moderation = getattr(user, 'moderation_status', None)
        return bool(moderation and moderation.is_suspended)

    if isinstance(user, Driver):
        moderation = getattr(user, 'moderation_status', None)
        return bool(moderation and moderation.is_suspended)

    return False


def _token_user_type(request):
    token = getattr(request, 'auth', None)
    if token is None:
        return None
    try:
        return token.get('user_type')
    except Exception:
        return None


class IsShopOwner(BasePermission):
    """Allow only shop owner."""

    message = 'This action is available only for shop owner.'

    def has_permission(self, request, view):
        self.message = t(request, 'permission_only_shop_owner')
        user = request.user
        if not user or not user.is_authenticated:
            return False

        token_user_type = _token_user_type(request)
        if token_user_type and token_user_type != 'shop_owner':
            return False

        if getattr(user, 'user_type', None) == 'shop_owner':
            return not _is_suspended_user(user)
        return isinstance(user, ShopOwner) and not _is_suspended_user(user)


class IsCustomer(BasePermission):
    """Allow only customer."""

    message = 'This action is available only for customers.'

    def has_permission(self, request, view):
        self.message = t(request, 'permission_only_customers')
        user = request.user
        if not user or not user.is_authenticated:
            return False

        token_user_type = _token_user_type(request)
        if token_user_type and token_user_type != 'customer':
            return False

        if getattr(user, 'user_type', None) == 'customer':
            return not _is_suspended_user(user)
        return isinstance(user, Customer) and not _is_suspended_user(user)


class IsEmployee(BasePermission):
    """Allow only employee."""

    message = 'This action is available only for employees.'

    def has_permission(self, request, view):
        self.message = t(request, 'permission_only_employees')
        user = request.user
        if not user or not user.is_authenticated:
            return False

        token_user_type = _token_user_type(request)
        if token_user_type and token_user_type != 'employee':
            return False

        if getattr(user, 'user_type', None) == 'employee':
            return True
        return isinstance(user, Employee)


class IsDriver(BasePermission):
    """Allow only driver."""

    message = 'This action is available only for drivers.'

    def has_permission(self, request, view):
        self.message = t(request, 'permission_only_drivers')
        user = request.user
        if not user or not user.is_authenticated:
            return False

        token_user_type = _token_user_type(request)
        if token_user_type and token_user_type != 'driver':
            return False

        if getattr(user, 'user_type', None) == 'driver':
            return not _is_suspended_user(user)
        return isinstance(user, Driver) and not _is_suspended_user(user)


class IsShopOwnerOrEmployee(BasePermission):
    """Allow shop owner or employee."""

    message = 'This action is available only for shop owner or employees.'

    def has_permission(self, request, view):
        self.message = t(request, 'permission_only_shop_owner_or_employees')
        user = request.user
        if not user or not user.is_authenticated:
            return False

        token_user_type = _token_user_type(request)
        if token_user_type and token_user_type not in {'shop_owner', 'employee'}:
            return False

        user_type = getattr(user, 'user_type', None)
        if user_type in {'shop_owner', 'employee'}:
            return not _is_suspended_user(user)
        return isinstance(user, (ShopOwner, Employee)) and not _is_suspended_user(user)


class IsShopStaff(BasePermission):
    """Allow shop owner, employee, or driver."""

    message = 'This action is available only for shop staff.'

    def has_permission(self, request, view):
        self.message = t(request, 'permission_only_shop_staff')
        user = request.user
        if not user or not user.is_authenticated:
            return False

        token_user_type = _token_user_type(request)
        if token_user_type and token_user_type not in {'shop_owner', 'employee', 'driver'}:
            return False

        user_type = getattr(user, 'user_type', None)
        if user_type in {'shop_owner', 'employee', 'driver'}:
            return not _is_suspended_user(user)
        return isinstance(user, (ShopOwner, Employee, Driver)) and not _is_suspended_user(user)
