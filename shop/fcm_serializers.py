from rest_framework import serializers

from .models import FCMDeviceToken


class FCMAccessTokenSerializer(serializers.Serializer):
    access_token = serializers.CharField(required=False, allow_blank=False, write_only=True)

    def validate_access_token(self, value):
        value = str(value or '').strip()
        if value.lower().startswith('bearer '):
            value = value[7:].strip()
        if not value:
            raise serializers.ValidationError('access_token is required when provided.')
        return value


class FCMDeviceTokenSerializer(serializers.ModelSerializer):
    class Meta:
        model = FCMDeviceToken
        fields = (
            'id',
            'user_type',
            'user_id',
            'device_id',
            'platform',
            'fcm_token',
            'app_version',
            'is_active',
            'last_used_at',
            'created_at',
            'updated_at',
        )
        read_only_fields = (
            'id',
            'user_type',
            'user_id',
            'is_active',
            'last_used_at',
            'created_at',
            'updated_at',
        )


class FCMDeviceRegisterSerializer(FCMAccessTokenSerializer):
    device_id = serializers.CharField(max_length=191)
    platform = serializers.ChoiceField(choices=[choice[0] for choice in FCMDeviceToken.PLATFORM_CHOICES])
    fcm_token = serializers.CharField()
    app_version = serializers.CharField(max_length=50, required=False, allow_blank=True, allow_null=True)

    def validate_device_id(self, value):
        value = str(value or '').strip()
        if not value:
            raise serializers.ValidationError('device_id is required.')
        return value

    def validate_fcm_token(self, value):
        value = str(value or '').strip()
        if not value:
            raise serializers.ValidationError('fcm_token is required.')
        return value


class FCMDeviceRefreshSerializer(FCMDeviceRegisterSerializer):
    pass


class FCMDeviceUnregisterSerializer(FCMAccessTokenSerializer):
    device_id = serializers.CharField(max_length=191, required=False, allow_blank=False)
    fcm_token = serializers.CharField(required=False, allow_blank=False)

    def validate(self, attrs):
        device_id = str(attrs.get('device_id') or '').strip()
        fcm_token = str(attrs.get('fcm_token') or '').strip()
        if not device_id and not fcm_token:
            raise serializers.ValidationError('Either device_id or fcm_token is required.')
        if device_id:
            attrs['device_id'] = device_id
        if fcm_token:
            attrs['fcm_token'] = fcm_token
        return attrs
