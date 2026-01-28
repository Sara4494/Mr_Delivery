from rest_framework_simplejwt.authentication import JWTAuthentication
from rest_framework_simplejwt.exceptions import InvalidToken, AuthenticationFailed
from .models import ShopOwner


class ShopOwnerJWTAuthentication(JWTAuthentication):
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
