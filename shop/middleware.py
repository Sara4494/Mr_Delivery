from channels.middleware import BaseMiddleware
from channels.db import database_sync_to_async
from rest_framework_simplejwt.tokens import UntypedToken
from rest_framework_simplejwt.exceptions import InvalidToken, TokenError
from jwt import decode as jwt_decode
from django.conf import settings
from user.models import AdminDesktopUser, ShopOwner
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
        if not user_type:
            return None, None

        if user_type == 'shop_owner':
            shop_owner_id = decoded_data.get('shop_owner_id') or decoded_data.get('user_id')
            if not shop_owner_id:
                return None, None
            try:
                user = ShopOwner.objects.get(id=shop_owner_id, is_active=True)
                return user, 'shop_owner'
            except ShopOwner.DoesNotExist:
                return None, None

        if user_type == 'customer':
            customer_id = decoded_data.get('customer_id')
            if not customer_id:
                return None, None
            try:
                user = Customer.objects.get(id=customer_id)
                return user, 'customer'
            except Customer.DoesNotExist:
                return None, None

        if user_type == 'employee':
            employee_id = decoded_data.get('employee_id')
            if not employee_id:
                return None, None
            try:
                user = Employee.objects.get(id=employee_id, is_active=True)
                return user, 'employee'
            except Employee.DoesNotExist:
                return None, None

        if user_type == 'driver':
            driver_id = decoded_data.get('driver_id')
            if not driver_id:
                return None, None
            try:
                user = Driver.objects.get(id=driver_id)
                return user, 'driver'
            except Driver.DoesNotExist:
                return None, None

        if user_type == 'admin_desktop':
            admin_user_id = decoded_data.get('admin_desktop_user_id')
            if not admin_user_id:
                return None, None
            try:
                user = AdminDesktopUser.objects.get(id=admin_user_id, is_active=True)
                return user, 'admin_desktop'
            except AdminDesktopUser.DoesNotExist:
                return None, None
                
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
