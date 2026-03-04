"""
Custom Permissions لأنواع المستخدمين المختلفة
"""

from rest_framework.permissions import BasePermission
from user.models import ShopOwner
from user.utils import t
from .models import Customer, Employee, Driver


class IsShopOwner(BasePermission):
    """
    السماح فقط لصاحب المحل
    """
    message = 'هذا الإجراء متاح فقط لصاحب المحل'
    
    def has_permission(self, request, view):
        self.message = t(request, 'permission_only_shop_owner')
        user = request.user
        if not user or not user.is_authenticated:
            return False
        
        # التحقق من نوع المستخدم
        if hasattr(user, 'user_type') and user.user_type == 'shop_owner':
            return True
        
        # أو إذا كان من نوع ShopOwner
        return isinstance(user, ShopOwner)


class IsCustomer(BasePermission):
    """
    السماح فقط للعميل
    """
    message = 'هذا الإجراء متاح فقط للعملاء'
    
    def has_permission(self, request, view):
        self.message = t(request, 'permission_only_customers')
        user = request.user
        if not user or not user.is_authenticated:
            return False
        
        # التحقق من نوع المستخدم
        if hasattr(user, 'user_type') and user.user_type == 'customer':
            return True
        
        # أو إذا كان من نوع Customer
        return isinstance(user, Customer)


class IsEmployee(BasePermission):
    """
    السماح فقط للموظف
    """
    message = 'هذا الإجراء متاح فقط للموظفين'
    
    def has_permission(self, request, view):
        self.message = t(request, 'permission_only_employees')
        user = request.user
        if not user or not user.is_authenticated:
            return False
        
        # التحقق من نوع المستخدم
        if hasattr(user, 'user_type') and user.user_type == 'employee':
            return True
        
        # أو إذا كان من نوع Employee
        return isinstance(user, Employee)


class IsDriver(BasePermission):
    """
    السماح فقط للسائق
    """
    message = 'هذا الإجراء متاح فقط للسائقين'
    
    def has_permission(self, request, view):
        self.message = t(request, 'permission_only_drivers')
        user = request.user
        if not user or not user.is_authenticated:
            return False
        
        # التحقق من نوع المستخدم
        if hasattr(user, 'user_type') and user.user_type == 'driver':
            return True
        
        # أو إذا كان من نوع Driver
        return isinstance(user, Driver)


class IsShopOwnerOrEmployee(BasePermission):
    """
    السماح لصاحب المحل أو الموظف
    """
    message = 'هذا الإجراء متاح فقط لصاحب المحل أو الموظفين'
    
    def has_permission(self, request, view):
        self.message = t(request, 'permission_only_shop_owner_or_employees')
        user = request.user
        if not user or not user.is_authenticated:
            return False
        
        user_type = getattr(user, 'user_type', None)
        if user_type in ['shop_owner', 'employee']:
            return True
        
        return isinstance(user, (ShopOwner, Employee))


class IsShopStaff(BasePermission):
    """
    السماح لصاحب المحل أو الموظف أو السائق (فريق المحل)
    """
    message = 'هذا الإجراء متاح فقط لفريق المحل'
    
    def has_permission(self, request, view):
        self.message = t(request, 'permission_only_shop_staff')
        user = request.user
        if not user or not user.is_authenticated:
            return False
        
        user_type = getattr(user, 'user_type', None)
        if user_type in ['shop_owner', 'employee', 'driver']:
            return True
        
        return isinstance(user, (ShopOwner, Employee, Driver))
