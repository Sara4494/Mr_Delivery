from channels.middleware import BaseMiddleware
from channels.db import database_sync_to_async
from django.contrib.auth import get_user_model
from rest_framework_simplejwt.tokens import UntypedToken
from rest_framework_simplejwt.exceptions import InvalidToken, TokenError
from jwt import decode as jwt_decode
from django.conf import settings
from user.models import ShopOwner


@database_sync_to_async
def get_user_from_token(token):
    """الحصول على المستخدم من التوكن"""
    try:
        UntypedToken(token)
        decoded_data = jwt_decode(token, settings.SECRET_KEY, algorithms=["HS256"])
        # استخدام shop_owner_id من التوكن المخصص
        shop_owner_id = decoded_data.get('shop_owner_id') or decoded_data.get('user_id')
        
        if shop_owner_id:
            try:
                return ShopOwner.objects.get(id=shop_owner_id, is_active=True)
            except ShopOwner.DoesNotExist:
                return None
    except (InvalidToken, TokenError, Exception):
        return None
    return None


class JWTAuthMiddleware(BaseMiddleware):
    """Middleware للمصادقة باستخدام JWT في WebSocket"""
    
    async def __call__(self, scope, receive, send):
        # استخراج التوكن من query string
        query_string = scope.get('query_string', b'').decode('utf-8')
        token = None
        
        if 'token=' in query_string:
            token = query_string.split('token=')[-1].split('&')[0]
        
        if token:
            user = await get_user_from_token(token)
            if user:
                scope['user'] = user
        
        return await super().__call__(scope, receive, send)
