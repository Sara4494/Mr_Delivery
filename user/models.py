<<<<<<< HEAD
from django.contrib.auth.hashers import check_password, make_password
from django.db import models


WORK_SCHEDULE_DAYS = (
    "saturday",
    "sunday",
    "monday",
    "tuesday",
    "wednesday",
    "thursday",
    "friday",
)

WORK_SCHEDULE_DAY_LABELS = {
    "saturday": "السبت",
    "sunday": "الأحد",
    "monday": "الاثنين",
    "tuesday": "الثلاثاء",
    "wednesday": "الأربعاء",
    "thursday": "الخميس",
    "friday": "الجمعة",
}


def default_work_schedule():
    schedule = {}
    for day in WORK_SCHEDULE_DAYS:
        is_working = day != "friday"
        schedule[day] = {
            "is_working": is_working,
            "start_time": "09:00" if is_working else None,
            "end_time": "17:00" if is_working else None,
        }
    return schedule


class ShopCategory(models.Model):
    """نموذج تصنيف المحل (مطعم، صيدلية، ...)."""

    name = models.CharField(max_length=100, unique=True, verbose_name="اسم التصنيف")
    is_active = models.BooleanField(default=True, verbose_name="نشط")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="تاريخ الإنشاء")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="تاريخ التحديث")

    class Meta:
        verbose_name = "تصنيف محل"
        verbose_name_plural = "تصنيفات المحلات"
        ordering = ["name"]

    def __str__(self):
        return self.name


class ShopOwner(models.Model):
    """نموذج صاحب المحل."""

    owner_name = models.CharField(max_length=100, verbose_name="اسم صاحب المحل")
    shop_name = models.CharField(max_length=100, verbose_name="اسم المحل")
    shop_number = models.CharField(max_length=50, unique=True, verbose_name="رقم المحل")
    shop_category = models.ForeignKey(
        ShopCategory,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="shops",
        verbose_name="تصنيف المحل",
    )
    phone_number = models.CharField(max_length=20, blank=True, null=True, verbose_name="رقم الهاتف")
    password = models.CharField(max_length=128, verbose_name="كلمة المرور")
    profile_image = models.ImageField(upload_to="shop_profiles/", blank=True, null=True, verbose_name="صورة البروفيل")
    description = models.TextField(blank=True, null=True, verbose_name="وصف المحل")
    work_schedule = models.JSONField(default=default_work_schedule, blank=True, verbose_name="مواعيد العمل الأسبوعية")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="تاريخ الإنشاء")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="تاريخ التحديث")
    is_active = models.BooleanField(default=True, verbose_name="نشط")

    class Meta:
        verbose_name = "صاحب المحل"
        verbose_name_plural = "أصحاب المحلات"
        ordering = ["-created_at"]

    def set_password(self, raw_password):
        """تشفير كلمة المرور."""
        self.password = make_password(raw_password)

    def check_password(self, raw_password):
        """التحقق من كلمة المرور."""
        return check_password(raw_password, self.password)

    def save(self, *args, **kwargs):
        """تشفير كلمة المرور تلقائيًا عند الحفظ."""
        if not self.pk or "password" in kwargs.get("update_fields", []):
            if not self.password.startswith("pbkdf2_"):
                self.password = make_password(self.password)
        super().save(*args, **kwargs)

    @property
    def is_authenticated(self):
        """للتوافق مع Django authentication."""
        return True

    def __str__(self):
        return f"{self.owner_name} - {self.shop_name} ({self.shop_number})"
=======
from django.db import models
from django.contrib.auth.hashers import make_password, check_password


class ShopOwner(models.Model):
    """نموذج صاحب المحل"""
    owner_name = models.CharField(max_length=100, verbose_name="اسم صاحب المحل")
    shop_name = models.CharField(max_length=100, verbose_name="اسم المحل")
    shop_number = models.CharField(max_length=50, unique=True, verbose_name="رقم المحل")
    password = models.CharField(max_length=128, verbose_name="كلمة المرور")
    profile_image = models.ImageField(upload_to='shop_profiles/', blank=True, null=True, verbose_name="صورة البروفيل")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="تاريخ الإنشاء")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="تاريخ التحديث")
    is_active = models.BooleanField(default=True, verbose_name="نشط")

    class Meta:
        verbose_name = "صاحب المحل"
        verbose_name_plural = "أصحاب المحلات"
        ordering = ['-created_at']

    def set_password(self, raw_password):
        """تشفير كلمة المرور"""
        self.password = make_password(raw_password)

    def check_password(self, raw_password):
        """التحقق من كلمة المرور"""
        return check_password(raw_password, self.password)

    def save(self, *args, **kwargs):
        """تشفير كلمة المرور تلقائياً عند الحفظ"""
        if not self.pk or 'password' in kwargs.get('update_fields', []):
            if not self.password.startswith('pbkdf2_'):
                self.password = make_password(self.password)
        super().save(*args, **kwargs)
    
    @property
    def is_authenticated(self):
        """للتوافق مع Django authentication"""
        return True

    def __str__(self):
        return f"{self.owner_name} - {self.shop_name} ({self.shop_number})"
>>>>>>> 4e65025 (feat: Implement gallery management features for shop owners)
