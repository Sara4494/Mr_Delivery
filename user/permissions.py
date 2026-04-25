from rest_framework.permissions import BasePermission

from shop.core.permissions import _ensure_active_account

from .models import AdminDesktopUser, ShopOwner
from .utils import t


class IsShopOwner(BasePermission):
    """
    يسمح فقط لصاحب المحل (ShopOwner) بالوصول.
    """

    message = "المسموح فقط لصاحب المحل بتعديل هذا المحتوى."

    def has_permission(self, request, view):
        self.message = t(request, "permission_only_shop_owner_edit_content")
        user = getattr(request, "user", None)
        if not user or not getattr(user, "is_authenticated", False):
            return False
        _ensure_active_account(request, user)
        return isinstance(user, ShopOwner)


class IsAdminDesktopUser(BasePermission):
    message = "هذا الإجراء متاح فقط لمستخدمي الديسكتوب."

    def has_permission(self, request, view):
        self.message = "هذا الإجراء متاح فقط لمستخدمي الديسكتوب."
        user = getattr(request, "user", None)
        if not user or not getattr(user, "is_authenticated", False):
            return False
        _ensure_active_account(request, user)
        return isinstance(user, AdminDesktopUser) and user.is_active
