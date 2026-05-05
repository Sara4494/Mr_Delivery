from django.contrib import admin

from .models import AdminDesktopUser, AppMaintenanceSettings, AppStatusSettings, ShopCategory, ShopOwner


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


@admin.register(AdminDesktopUser)
class AdminDesktopUserAdmin(admin.ModelAdmin):
    list_display = ("name", "phone_number", "role", "is_active", "last_login_at", "created_at")
    list_filter = ("role", "is_active", "created_at")
    search_fields = ("name", "phone_number", "email")
    readonly_fields = ("created_at", "updated_at", "last_login_at")
    fieldsets = (
        ("البيانات الأساسية", {
            "fields": ("name", "phone_number", "email", "profile_image")
        }),
        ("الصلاحيات", {
            "fields": ("role", "permissions", "is_active")
        }),
        ("الأمان", {
            "fields": ("password", "last_login_at")
        }),
        ("معلومات إضافية", {
            "fields": ("created_at", "updated_at")
        }),
    )

    def save_model(self, request, obj, form, change):
        if "password" in form.changed_data:
            obj.set_password(obj.password)
        if "role" in form.changed_data and "permissions" not in form.changed_data:
            obj.apply_role_permissions()
        super().save_model(request, obj, form, change)


@admin.register(AppMaintenanceSettings)
class AppMaintenanceSettingsAdmin(admin.ModelAdmin):
    list_display = ("enabled", "target_user_type", "target_platform", "starts_at", "ends_at", "updated_at")
    list_filter = ("enabled", "target_user_type", "target_platform")
    readonly_fields = ("created_at", "updated_at")
    fieldsets = (
        ("الاستهداف", {
            "fields": ("enabled", "target_user_type", "target_platform")
        }),
        ("المحتوى", {
            "fields": (
                "title_ar",
                "title_en",
                "message_ar",
                "message_en",
                "footnote_ar",
                "footnote_en",
            )
        }),
        ("الجدولة", {
            "fields": ("starts_at", "ends_at", "retry_after_seconds")
        }),
        ("معلومات إضافية", {
            "fields": ("created_at", "updated_at")
        }),
    )


@admin.register(AppStatusSettings)
class AppStatusSettingsAdmin(admin.ModelAdmin):
    list_display = ("maintenance_mode", "update_enabled", "force_update", "updated_at")
    readonly_fields = ("created_at", "updated_at")
    fieldsets = (
        ("الحالة العامة", {
            "fields": ("maintenance_mode", "update_enabled", "force_update")
        }),
        ("إعدادات التحديث", {
            "fields": (
                "android_min_version",
                "android_store_url",
                "ios_min_version",
                "ios_store_url",
                "windows_min_version",
                "windows_download_url",
            )
        }),
        ("نصوص شاشة الحالة", {
            "fields": (
                "maintenance_title_ar",
                "maintenance_title_en",
                "maintenance_message_ar",
                "maintenance_message_en",
                "maintenance_window_label_ar",
                "maintenance_window_label_en",
                "show_contact_support",
                "support_whatsapp",
                "estimated_minutes",
            )
        }),
        ("معلومات إضافية", {
            "fields": ("created_at", "updated_at")
        }),
    )
