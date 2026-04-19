from rest_framework import serializers
from rest_framework_simplejwt.tokens import RefreshToken
from .models import ShopOwner


class ShopOwnerTokenObtainPairSerializer(serializers.Serializer):
    """Custom Token Serializer للـ ShopOwner"""
    shop_number = serializers.CharField(required=True)
    password = serializers.CharField(required=True, write_only=True)
    
    @classmethod
    def get_token(cls, shop_owner):
        """
        إنشاء token مع shop_owner_id
        """
        token = RefreshToken()
        token['shop_owner_id'] = shop_owner.id
        token['shop_number'] = shop_owner.shop_number
        token['shop_name'] = shop_owner.shop_name
        token['shop_category_id'] = shop_owner.shop_category_id
        token['shop_category_name'] = shop_owner.shop_category.name if shop_owner.shop_category else None
        token['user_type'] = 'shop_owner'
        return token
    
    def validate(self, attrs):
        """
        التحقق من بيانات تسجيل الدخول وإرجاع token
        """
        shop_number = attrs.get('shop_number')
        password = attrs.get('password')

        try:
            shop_owner = ShopOwner.objects.select_related('moderation_status').get(shop_number=shop_number)
        except ShopOwner.DoesNotExist:
            raise serializers.ValidationError({
                'shop_number': 'رقم المحل أو كلمة المرور غير صحيحة'
            })

        moderation = getattr(shop_owner, 'moderation_status', None)
        if getattr(shop_owner, 'admin_status', None) == 'suspended' or (moderation and moderation.is_suspended):
            raise serializers.ValidationError({
                'code': 'SHOP_OWNER_ACCOUNT_SUSPENDED',
                'detail': (
                    getattr(shop_owner, 'suspension_reason', None)
                    or getattr(moderation, 'suspension_reason', None)
                    or 'هذا الحساب معلق حاليًا. برجاء التواصل مع الدعم.'
                )
            })

        if not shop_owner.is_active:
            raise serializers.ValidationError({
                'code': 'SHOP_OWNER_ACCOUNT_INACTIVE',
                'detail': 'هذا الحساب غير نشط حاليًا. برجاء التواصل مع الإدارة.'
            })

        if not shop_owner.check_password(password):
            raise serializers.ValidationError({
                'password': 'كلمة المرور غير صحيحة'
            })
        
        refresh = self.get_token(shop_owner)
        
        return {
            'refresh': str(refresh),
            'access': str(refresh.access_token),
            'shop_owner': {
                'id': shop_owner.id,
                'owner_name': shop_owner.owner_name,
                'shop_name': shop_owner.shop_name,
                'shop_number': shop_owner.shop_number,
                'shop_category_id': shop_owner.shop_category_id,
                'shop_category_name': shop_owner.shop_category.name if shop_owner.shop_category else None,
            }
        }
