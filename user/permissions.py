from rest_framework.permissions import BasePermission
from .models import AdminDesktopUser, ShopOwner
from .utils import t


class IsShopOwner(BasePermission):
    """
    يسمح فقط لصاحب المحل (ShopOwner) بالوصول.
    """
    message = "المسموح فقط لصاحب المحل بتعديل هذا المحتوى."

    def has_permission(self, request, view):
        self.message = t(request, "permission_only_shop_owner_edit_content")
        return request.user and isinstance(request.user, ShopOwner)


class IsAdminDesktopUser(BasePermission):
    message = "هذا الإجراء متاح فقط لمستخدمي الديسكتوب."

    def has_permission(self, request, view):
        self.message = "هذا الإجراء متاح فقط لمستخدمي الديسكتوب."
        return request.user and isinstance(request.user, AdminDesktopUser) and request.user.is_active
