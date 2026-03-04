from django.contrib import admin
from .models import GalleryImage, WorkSchedule, ImageLike


@admin.register(WorkSchedule)
class WorkScheduleAdmin(admin.ModelAdmin):
    """إدارة مواعيد العمل"""
    list_display = ('shop_owner', 'work_days', 'work_hours', 'updated_at')
    search_fields = ('shop_owner__shop_name', 'shop_owner__owner_name')
    readonly_fields = ('created_at', 'updated_at')


@admin.register(GalleryImage)
class GalleryImageAdmin(admin.ModelAdmin):
    """إدارة صور المعرض"""
    list_display = ('shop_owner', 'image', 'status', 'likes_count', 'uploaded_at')
    list_filter = ('status', 'uploaded_at')
    search_fields = ('shop_owner__shop_name', 'description')
    readonly_fields = ('uploaded_at', 'updated_at', 'likes_count')
    fieldsets = (
        ('معلومات أساسية', {
            'fields': ('shop_owner', 'image', 'description')
        }),
        ('الحالة والإحصائيات', {
            'fields': ('status', 'likes_count')
        }),
        ('معلومات إضافية', {
            'fields': ('uploaded_at', 'updated_at')
        }),
    )


@admin.register(ImageLike)
class ImageLikeAdmin(admin.ModelAdmin):
    """إدارة الإعجابات"""
    list_display = ('image', 'user_identifier', 'created_at')
    list_filter = ('created_at',)
    search_fields = ('image__shop_owner__shop_name', 'user_identifier')
    readonly_fields = ('created_at',)
