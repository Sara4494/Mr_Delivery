from rest_framework import serializers

from .authentication import (
    apply_session_token_lifetimes,
    build_session_refresh_token,
    notify_session_revoked,
    rotate_user_session,
)
from .models import ShopOwner
from .otp_service import normalize_phone


class ShopOwnerTokenObtainPairSerializer(serializers.Serializer):
    """Custom Token Serializer للـ ShopOwner"""
    phone_number = serializers.CharField(required=False, allow_blank=True)
    shop_number = serializers.CharField(required=False, allow_blank=True)
    password = serializers.CharField(required=True, write_only=True)
    
    @classmethod
    def get_token(cls, shop_owner):
        """
        إنشاء token مع shop_owner_id
        """
        return build_session_refresh_token(user=shop_owner, user_type='shop_owner')
    
    def validate(self, attrs):
        """
        التحقق من بيانات تسجيل الدخول وإرجاع token
        """
        raw_phone = str(attrs.get('phone_number') or attrs.get('shop_number') or '').strip()
        password = attrs.get('password')
        if not raw_phone:
            raise serializers.ValidationError({
                'phone_number': 'رقم الهاتف مطلوب'
            })

        normalized_phone = normalize_phone(raw_phone)
        phone_variants = [raw_phone]
        if normalized_phone and normalized_phone not in phone_variants:
            phone_variants.append(normalized_phone)

        try:
            shop_owner = (
                ShopOwner.objects
                .select_related('moderation_status')
                .filter(phone_number__in=phone_variants)
                .order_by('-updated_at')
                .first()
            )
            if shop_owner is None:
                raise ShopOwner.DoesNotExist
        except ShopOwner.DoesNotExist:
            raise serializers.ValidationError({
                'phone_number': 'رقم الهاتف أو كلمة المرور غير صحيحة'
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
        
        rotate_user_session(shop_owner)
        shop_owner.save(update_fields=['active_session_key'])
        notify_session_revoked(shop_owner, 'shop_owner')
        refresh = self.get_token(shop_owner)
        access_token = apply_session_token_lifetimes(refresh)
        
        return {
            'refresh': str(refresh),
            'access': str(access_token),
            'shop_owner': {
                'id': shop_owner.id,
                'owner_name': shop_owner.owner_name,
                'shop_name': shop_owner.shop_name,
                'shop_number': shop_owner.shop_number,
                'shop_category_id': shop_owner.shop_category_id,
                'shop_category_name': shop_owner.shop_category.name if shop_owner.shop_category else None,
            }
        }
