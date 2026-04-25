from channels.db import database_sync_to_async
from channels.middleware import BaseMiddleware
from django.conf import settings
from jwt import decode as jwt_decode
from rest_framework_simplejwt.exceptions import InvalidToken, TokenError
from rest_framework_simplejwt.tokens import UntypedToken

from shop.models import Customer, Driver, Employee
from user.account_status import get_account_suspension_context
from user.models import AdminDesktopUser, ShopOwner


@database_sync_to_async
def get_user_from_token(token):
    """
    Returns: (user_object, user_type, suspension_context)
    """
    try:
        UntypedToken(token)
        decoded_data = jwt_decode(token, settings.SECRET_KEY, algorithms=["HS256"])

        user_type = decoded_data.get("user_type")
        if not user_type:
            return None, None, None

        user = None
        if user_type == "shop_owner":
            shop_owner_id = decoded_data.get("shop_owner_id") or decoded_data.get("user_id")
            if shop_owner_id:
                user = ShopOwner.objects.filter(id=shop_owner_id).first()
        elif user_type == "customer":
            customer_id = decoded_data.get("customer_id")
            if customer_id:
                user = Customer.objects.filter(id=customer_id).first()
        elif user_type == "employee":
            employee_id = decoded_data.get("employee_id")
            if employee_id:
                user = Employee.objects.filter(id=employee_id).first()
        elif user_type == "driver":
            driver_id = decoded_data.get("driver_id")
            if driver_id:
                user = Driver.objects.filter(id=driver_id).first()
        elif user_type == "admin_desktop":
            admin_user_id = decoded_data.get("admin_desktop_user_id")
            if admin_user_id:
                user = AdminDesktopUser.objects.filter(id=admin_user_id).first()

        if not user:
            return None, None, None

        user.user_type = user_type
        return user, user_type, get_account_suspension_context(user)
    except (InvalidToken, TokenError, Exception) as e:
        print(f"[JWTAuthMiddleware] Token error: {e}")
        return None, None, None


class JWTAuthMiddleware(BaseMiddleware):
    """Middleware للمصادقة باستخدام JWT في WebSocket - يدعم جميع أنواع المستخدمين"""

    async def __call__(self, scope, receive, send):
        query_string = scope.get("query_string", b"").decode("utf-8")
        token = None
        if "token=" in query_string:
            token = query_string.split("token=")[-1].split("&")[0]

        scope["user"] = None
        scope["user_type"] = None
        scope["account_suspension"] = None

        if token:
            user, user_type, suspension = await get_user_from_token(token)
            if user:
                scope["user"] = user
                scope["user_type"] = user_type
                scope["account_suspension"] = suspension
                print(f"[JWTAuthMiddleware] Authenticated: {user_type} - ID: {user.id}")

        return await super().__call__(scope, receive, send)
