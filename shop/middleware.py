from channels.middleware import BaseMiddleware
from channels.db import database_sync_to_async
from rest_framework_simplejwt.tokens import UntypedToken
from rest_framework_simplejwt.exceptions import InvalidToken, TokenError
from jwt import decode as jwt_decode
from django.conf import settings
from user.models import ShopOwner
from shop.models import Customer, Employee, Driver


@database_sync_to_async
def get_user_from_token(token):
    """
    الحصول على المستخدم من التوكن - يدعم جميع أنواع المستخدمين
    Returns: (user_object, user_type)
    """
    try:
        UntypedToken(token)
        decoded_data = jwt_decode(token, settings.SECRET_KEY, algorithms=["HS256"])
        
        user_type = decoded_data.get('user_type')
        
        # ShopOwner
        if user_type == 'shop_owner' or decoded_data.get('shop_owner_id'):
            shop_owner_id = decoded_data.get('shop_owner_id') or decoded_data.get('user_id')
            if shop_owner_id:
                try:
                    user = ShopOwner.objects.get(id=shop_owner_id, is_active=True)
                    return user, 'shop_owner'
                except ShopOwner.DoesNotExist:
                    pass
        
        # Customer
        if user_type == 'customer' or decoded_data.get('customer_id'):
            customer_id = decoded_data.get('customer_id') or decoded_data.get('user_id')
            if customer_id:
                try:
                    user = Customer.objects.get(id=customer_id)
                    return user, 'customer'
                except Customer.DoesNotExist:
                    pass
        
        # Employee
        if user_type == 'employee' or decoded_data.get('employee_id'):
            employee_id = decoded_data.get('employee_id') or decoded_data.get('user_id')
            if employee_id:
                try:
                    user = Employee.objects.get(id=employee_id, is_active=True)
                    return user, 'employee'
                except Employee.DoesNotExist:
                    pass
        
        # Driver
        if user_type == 'driver' or decoded_data.get('driver_id'):
            driver_id = decoded_data.get('driver_id') or decoded_data.get('user_id')
            if driver_id:
                try:
                    user = Driver.objects.get(id=driver_id)
                    return user, 'driver'
                except Driver.DoesNotExist:
                    pass
        
        # Fallback: try shop_owner_id or user_id for backward compatibility
        user_id = decoded_data.get('user_id')
        if user_id:
            try:
                user = ShopOwner.objects.get(id=user_id, is_active=True)
                return user, 'shop_owner'
            except ShopOwner.DoesNotExist:
                pass
                
    except (InvalidToken, TokenError, Exception) as e:
        print(f"[JWTAuthMiddleware] Token error: {e}")
        return None, None
    
    return None, None


class JWTAuthMiddleware(BaseMiddleware):
    """Middleware للمصادقة باستخدام JWT في WebSocket - يدعم جميع أنواع المستخدمين"""
    
    async def __call__(self, scope, receive, send):
        # استخراج التوكن من query string
        query_string = scope.get('query_string', b'').decode('utf-8')
        token = None
        
        if 'token=' in query_string:
            token = query_string.split('token=')[-1].split('&')[0]
        
        scope['user'] = None
        scope['user_type'] = None
        
        if token:
            user, user_type = await get_user_from_token(token)
            if user:
                scope['user'] = user
                scope['user_type'] = user_type
                print(f"[JWTAuthMiddleware] Authenticated: {user_type} - ID: {user.id}")
        
        return await super().__call__(scope, receive, send)
