<<<<<<< HEAD
from django.contrib import admin
from .models import ShopCategory, ShopOwner


@admin.register(ShopCategory)
class ShopCategoryAdmin(admin.ModelAdmin):
    """إدارة تصنيفات المحلات."""
    list_display = ('id', 'name', 'is_active', 'created_at')
    list_filter = ('is_active', 'created_at')
    search_fields = ('name',)
    readonly_fields = ('created_at', 'updated_at')


@admin.register(ShopOwner)
class ShopOwnerAdmin(admin.ModelAdmin):
    """إدارة أصحاب المحلات"""
    list_display = ('owner_name', 'shop_name', 'shop_number', 'shop_category', 'phone_number', 'is_active', 'created_at')
    list_filter = ('is_active', 'created_at')
    search_fields = ('owner_name', 'shop_name', 'shop_number', 'shop_category__name', 'phone_number')
    readonly_fields = ('created_at', 'updated_at')
    fieldsets = (
        ('معلومات أساسية', {
            'fields': ('owner_name', 'shop_name', 'shop_number', 'shop_category', 'phone_number', 'profile_image')
        }),
=======
from django.contrib import admin
from .models import ShopOwner


@admin.register(ShopOwner)
class ShopOwnerAdmin(admin.ModelAdmin):
    """إدارة أصحاب المحلات"""
    list_display = ('owner_name', 'shop_name', 'shop_number', 'is_active', 'created_at')
    list_filter = ('is_active', 'created_at')
    search_fields = ('owner_name', 'shop_name', 'shop_number')
    readonly_fields = ('created_at', 'updated_at')
    fieldsets = (
        ('معلومات أساسية', {
            'fields': ('owner_name', 'shop_name', 'shop_number', 'profile_image')
        }),
>>>>>>> 4e65025 (feat: Implement gallery management features for shop owners)
        ('الأمان', {
            'fields': ('password', 'is_active')
        }),
        ('معلومات إضافية', {
            'fields': ('created_at', 'updated_at')
        }),
    )

    def save_model(self, request, obj, form, change):
        """تشفير كلمة المرور عند الحفظ من الـ Admin"""
        if 'password' in form.changed_data:
            obj.set_password(obj.password)
        super().save_model(request, obj, form, change)
