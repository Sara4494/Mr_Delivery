"""
Custom permissions for role-based access control.
"""

from rest_framework.permissions import BasePermission

from user.account_status import ensure_account_is_active
from user.models import ShopOwner
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


class EnsureActiveAccountPermission(BasePermission):
    def has_permission(self, request, view):
        user = getattr(request, "user", None)
        if not user or not getattr(user, "is_authenticated", False):
            return True
        _ensure_active_account(request, user)
        return True


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
