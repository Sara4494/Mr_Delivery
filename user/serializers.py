from rest_framework import serializers
from .models import ShopOwner


<<<<<<< HEAD
class ShopOwnerSerializer(serializers.ModelSerializer):
    """Serializer لصاحب المحل"""
    password = serializers.CharField(write_only=True, required=False, style={'input_type': 'password'})
    profile_image_url = serializers.SerializerMethodField()
    shop_category_name = serializers.CharField(source='shop_category.name', read_only=True)

    class Meta:
        model = ShopOwner
        fields = ['id', 'owner_name', 'shop_name', 'shop_number', 'shop_category', 'shop_category_name', 'password',
                  'profile_image', 'profile_image_url', 'created_at', 'updated_at', 'is_active']
=======
class ShopOwnerSerializer(serializers.ModelSerializer):
    """Serializer لصاحب المحل"""
    password = serializers.CharField(write_only=True, required=False, style={'input_type': 'password'})
    profile_image_url = serializers.SerializerMethodField()

    class Meta:
        model = ShopOwner
        fields = ['id', 'owner_name', 'shop_name', 'shop_number', 'password', 
                  'profile_image', 'profile_image_url', 'created_at', 'updated_at', 'is_active']
>>>>>>> 4e65025 (feat: Implement gallery management features for shop owners)
        read_only_fields = ['id', 'created_at', 'updated_at']
        extra_kwargs = {
            'password': {'write_only': True}
        }
    
    def get_profile_image_url(self, obj):
        """إرجاع رابط صورة البروفيل الكامل"""
        if obj.profile_image:
            request = self.context.get('request')
            if request:
                return request.build_absolute_uri(obj.profile_image.url)
            return obj.profile_image.url
        return None

    def create(self, validated_data):
        """إنشاء صاحب محل جديد مع تشفير كلمة المرور"""
        password = validated_data.pop('password', None)
        shop_owner = ShopOwner.objects.create(**validated_data)
        if password:
            shop_owner.set_password(password)
            shop_owner.save()
        return shop_owner

    def update(self, instance, validated_data):
        """تحديث بيانات صاحب المحل"""
        password = validated_data.pop('password', None)
        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        if password:
            instance.set_password(password)
        instance.save()
        return instance


class LoginSerializer(serializers.Serializer):
    """Serializer لتسجيل الدخول"""
    shop_number = serializers.CharField(required=True, help_text="رقم المحل")
    password = serializers.CharField(required=True, write_only=True, style={'input_type': 'password'}, help_text="كلمة المرور")

    def validate(self, attrs):
        """التحقق من بيانات تسجيل الدخول"""
        shop_number = attrs.get('shop_number')
        password = attrs.get('password')

        try:
            shop_owner = ShopOwner.objects.get(shop_number=shop_number, is_active=True)
        except ShopOwner.DoesNotExist:
            raise serializers.ValidationError({
                'shop_number': 'رقم المحل غير صحيح أو الحساب غير نشط'
            })

        if not shop_owner.check_password(password):
            raise serializers.ValidationError({
                'password': 'كلمة المرور غير صحيحة'
            })

        attrs['shop_owner'] = shop_owner
        return attrs

<<<<<<< HEAD
 
=======
 
>>>>>>> 4e65025 (feat: Implement gallery management features for shop owners)
