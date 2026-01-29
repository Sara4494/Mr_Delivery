from rest_framework.permissions import BasePermission
from .models import ShopOwner


class IsShopOwner(BasePermission):
    """
    يسمح فقط لصاحب المحل (ShopOwner) بالوصول.
    """
    message = "المسموح فقط لصاحب المحل بتعديل هذا المحتوى."

    def has_permission(self, request, view):
        return request.user and isinstance(request.user, ShopOwner)
