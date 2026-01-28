from rest_framework_simplejwt.authentication import JWTAuthentication
from rest_framework_simplejwt.exceptions import InvalidToken, AuthenticationFailed
from .models import ShopOwner


class ShopOwnerJWTAuthentication(JWTAuthentication):
<<<<<<< HEAD
    """
    Custom JWT Authentication يدعم جميع أنواع المستخدمين:
    - ShopOwner
    - Customer
    - Employee
    - Driver
    """
    
    def get_user(self, validated_token):
        """
        الحصول على المستخدم من validated token حسب نوعه
        """
        user_type = validated_token.get('user_type')
        
        # ===== Customer =====
        if user_type == 'customer' or validated_token.get('customer_id'):
            customer_id = validated_token.get('customer_id')
            if customer_id:
                try:
                    from shop.models import Customer
                    customer = Customer.objects.get(id=customer_id)
                    customer.user_type = 'customer'
                    return customer
                except Customer.DoesNotExist:
                    raise AuthenticationFailed('العميل غير موجود')
        
        # ===== Employee =====
        if user_type == 'employee' or validated_token.get('employee_id'):
            employee_id = validated_token.get('employee_id')
            if employee_id:
                try:
                    from shop.models import Employee
                    employee = Employee.objects.get(id=employee_id, is_active=True)
                    employee.user_type = 'employee'
                    return employee
                except Employee.DoesNotExist:
                    raise AuthenticationFailed('الموظف غير موجود أو غير نشط')
        
        # ===== Driver =====
        if user_type == 'driver' or validated_token.get('driver_id'):
            driver_id = validated_token.get('driver_id')
            if driver_id:
                try:
                    from shop.models import Driver
                    driver = Driver.objects.get(id=driver_id)
                    driver.user_type = 'driver'
                    return driver
                except Driver.DoesNotExist:
                    raise AuthenticationFailed('السائق غير موجود')
        
        # ===== ShopOwner (Default) =====
        shop_owner_id = validated_token.get('shop_owner_id') or validated_token.get('user_id')
        if shop_owner_id:
            try:
                shop_owner = ShopOwner.objects.get(id=shop_owner_id, is_active=True)
                shop_owner.user_type = 'shop_owner'
                return shop_owner
            except ShopOwner.DoesNotExist:
                raise AuthenticationFailed('صاحب المحل غير موجود أو غير نشط')
        
        raise InvalidToken('Token غير صالح - لا يحتوي على معرف مستخدم')
=======
    """Custom JWT Authentication للـ ShopOwner"""
    
    def get_user(self, validated_token):
        """
        الحصول على ShopOwner من validated token
        """
        try:
            shop_owner_id = validated_token.get('shop_owner_id')
            if not shop_owner_id:
                raise InvalidToken('Token does not contain shop_owner_id')
            
            shop_owner = ShopOwner.objects.get(id=shop_owner_id, is_active=True)
            return shop_owner
        except ShopOwner.DoesNotExist:
            raise AuthenticationFailed('Shop owner not found or inactive')
        except KeyError:
            raise InvalidToken('Invalid token format')
>>>>>>> 4e65025 (feat: Implement gallery management features for shop owners)
