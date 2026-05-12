from datetime import timedelta

from django import forms
from django.contrib import admin
from django.utils import timezone

from .models import AdminDesktopUser, AppMaintenanceSettings, AppStatusSettings, ShopCategory, ShopOwner


class AppMaintenanceSettingsAdminForm(forms.ModelForm):
    duration_hours = forms.IntegerField(
        required=False,
        min_value=1,
        label="مدة الصيانة بالساعات",
        help_text="اختياري: إذا أدخلتها فسيتم حساب وقت الانتهاء تلقائيًا. وإذا تركتها فارغة يمكنك إدخال وقت البدء والانتهاء يدويًا.",
    )

    class Meta:
        model = AppMaintenanceSettings
        fields = "__all__"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        instance = getattr(self, "instance", None)
        if instance and instance.starts_at and instance.ends_at and not self.is_bound:
            duration = instance.ends_at - instance.starts_at
            total_hours = int(duration.total_seconds() // 3600)
            if duration.total_seconds() % 3600:
                total_hours += 1
            if total_hours > 0:
                self.fields["duration_hours"].initial = total_hours


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
    form = AppMaintenanceSettingsAdminForm
    list_display = ("enabled", "target_user_type", "target_platform", "starts_at", "ends_at", "display_updated_at")
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
            "fields": ("duration_hours", "retry_after_seconds", "starts_at", "ends_at")
        }),
        ("معلومات إضافية", {
            "fields": ("created_at", "updated_at")
        }),
    )

    def save_model(self, request, obj, form, change):
        # Django admin edits only the legacy single-value fields, so keep
        # the JSON target lists in sync before the model normalizes them.
        if obj.target_user_type:
            obj.set_target_user_types([obj.target_user_type])
        if obj.target_platform:
            obj.set_target_platforms([obj.target_platform])

        if obj.enabled:
            now = timezone.now()
            duration_hours = form.cleaned_data.get("duration_hours")
            starts_changed = "starts_at" in form.changed_data
            ends_changed = "ends_at" in form.changed_data
            if duration_hours:
                base_start = obj.starts_at if starts_changed and obj.starts_at else now
                obj.starts_at = base_start
                obj.ends_at = base_start + timedelta(hours=duration_hours)
            else:
                if not obj.starts_at:
                    obj.starts_at = now
                elif not starts_changed and obj.starts_at > now:
                    obj.starts_at = now
            if "duration_hours" in form.changed_data and not duration_hours and not ends_changed:
                obj.ends_at = None
        super().save_model(request, obj, form, change)

    @admin.display(description="تاريخ التحديث", ordering="starts_at")
    def display_updated_at(self, obj):
        return obj.starts_at or obj.updated_at


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
                "windows_installer_file",
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
