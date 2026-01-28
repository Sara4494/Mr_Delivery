from django.utils import timezone
from rest_framework import serializers

from .models import GalleryImage, WorkSchedule, ImageLike
from user.models import ShopOwner, WORK_SCHEDULE_DAY_LABELS


PY_WEEKDAY_TO_WORK_DAY = {
    0: 'monday',
    1: 'tuesday',
    2: 'wednesday',
    3: 'thursday',
    4: 'friday',
    5: 'saturday',
    6: 'sunday',
}


class WorkScheduleSerializer(serializers.ModelSerializer):
    """Serializer لمواعيد العمل"""

    class Meta:
        model = WorkSchedule
        fields = ['id', 'work_days', 'work_hours', 'created_at', 'updated_at']
        read_only_fields = ['id', 'created_at', 'updated_at']


class GalleryImageSerializer(serializers.ModelSerializer):
    """Serializer لصور المعرض"""
    image_url = serializers.SerializerMethodField()
    is_liked = serializers.SerializerMethodField()

    class Meta:
        model = GalleryImage
        fields = ['id', 'image', 'image_url', 'description', 'status',
                  'uploaded_at', 'updated_at', 'likes_count', 'is_liked']
        read_only_fields = ['id', 'uploaded_at', 'updated_at', 'likes_count']

    def get_image_url(self, obj):
        """إرجاع رابط الصورة الكامل"""
        if obj.image:
            request = self.context.get('request')
            if request:
                return request.build_absolute_uri(obj.image.url)
            return obj.image.url
        return None

    def get_is_liked(self, obj):
        """التحقق من إعجاب المستخدم بالصورة"""
        request = self.context.get('request')
        user_identifier = request.query_params.get('user_identifier') if request else None
        if user_identifier:
            return ImageLike.objects.filter(
                image=obj,
                user_identifier=user_identifier
            ).exists()
        return False


class GalleryImageCreateSerializer(serializers.ModelSerializer):
    """Serializer لإنشاء صورة جديدة"""

    class Meta:
        model = GalleryImage
        fields = ['image', 'description', 'status']

    def create(self, validated_data):
        """إنشاء صورة جديدة"""
        shop_owner = self.context['shop_owner']
        return GalleryImage.objects.create(shop_owner=shop_owner, **validated_data)


class ShopProfileSerializer(serializers.ModelSerializer):
    """Serializer لملف صاحب المحل"""
    work_schedule = serializers.SerializerMethodField()
    profile_image_url = serializers.SerializerMethodField()
    total_images = serializers.SerializerMethodField()
    published_images = serializers.SerializerMethodField()
    total_likes = serializers.SerializerMethodField()

    class Meta:
        model = ShopOwner
        fields = ['id', 'owner_name', 'shop_name', 'shop_number', 'phone_number', 'description', 'profile_image', 'profile_image_url',
                  'work_schedule', 'total_images', 'published_images',
                  'total_likes', 'created_at', 'updated_at', 'is_active']
        read_only_fields = ['id', 'created_at', 'updated_at']

    def get_work_schedule(self, obj):
        legacy_schedule = getattr(obj, 'legacy_work_schedule', None)
        if not legacy_schedule:
            return None

        today_key = PY_WEEKDAY_TO_WORK_DAY.get(timezone.localdate().weekday(), 'monday')
        today_label = WORK_SCHEDULE_DAY_LABELS.get(today_key, today_key)

        work_hours = legacy_schedule.work_hours
        schedule = obj.work_schedule if isinstance(obj.work_schedule, dict) else {}
        today_data = schedule.get(today_key) if isinstance(schedule, dict) else None

        if isinstance(today_data, dict):
            is_working = today_data.get('is_working', False)
            start_time = today_data.get('start_time')
            end_time = today_data.get('end_time')

            if is_working and start_time and end_time:
                work_hours = f'{start_time} - {end_time}'
            elif not is_working:
                work_hours = 'إجازة'

        return {
            'id': legacy_schedule.id,
            'work_days': today_label,
            'work_hours': work_hours,
            'created_at': legacy_schedule.created_at,
            'updated_at': legacy_schedule.updated_at,
        }

    def get_profile_image_url(self, obj):
        """إرجاع رابط صورة البروفيل الكامل"""
        if obj.profile_image:
            request = self.context.get('request')
            if request:
                return request.build_absolute_uri(obj.profile_image.url)
            return obj.profile_image.url
        return None

    def get_total_images(self, obj):
        """إجمالي عدد الصور"""
        return obj.gallery_images.count()

    def get_published_images(self, obj):
        """عدد الصور المنشورة"""
        return obj.gallery_images.filter(status='published').count()

    def get_total_likes(self, obj):
        """إجمالي الإعجابات"""
        return sum(img.likes_count for img in obj.gallery_images.filter(status='published'))


class ShopProfileUpdateSerializer(serializers.ModelSerializer):
    """Serializer لتحديث ملف صاحب المحل (البيانات + صورة البروفيل في endpoint واحد)"""
    profile_image = serializers.ImageField(required=False, allow_null=True)

    class Meta:
        model = ShopOwner
        fields = ['owner_name', 'shop_name', 'phone_number', 'description', 'profile_image']


class ImageLikeSerializer(serializers.Serializer):
    """Serializer للإعجاب/إلغاء الإعجاب"""
    user_identifier = serializers.CharField(required=True, help_text="معرف المستخدم (رقم هاتف أو أي معرف)")
