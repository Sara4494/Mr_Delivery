from django.contrib.auth.hashers import check_password, make_password
from django.db import models

from .otp_service import normalize_phone


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


ADMIN_DESKTOP_PERMISSION_CHOICES = (
    ("dashboard", "لوحة التحكم"),
    ("store_management", "إدارة المتاجر"),
    ("approvals", "الموافقات"),
    ("invoices_payments", "الفواتير والمدفوعات"),
    ("reports", "التقارير"),
    ("activity_logs", "سجل النشاطات"),
    ("abuse_reports", "بلاغات الإساءة"),
    ("support_actions", "إدارة الحسابات"),
    ("support_center", "مركز الدعم"),
    ("app_updates", "تحديثات التطبيق"),
    ("notifications", "التنبيهات"),
)

ADMIN_DESKTOP_PERMISSION_CHOICES += (
    ("admin_management", "إدارة المديرين"),
)

ADMIN_DESKTOP_ALL_PERMISSIONS = [code for code, _ in ADMIN_DESKTOP_PERMISSION_CHOICES]
ADMIN_DESKTOP_READONLY_ADMIN_ROLES = {"dashboard_manager"}
ADMIN_DESKTOP_FULL_ADMIN_ROLE = "system_developer"

ADMIN_DESKTOP_ROLE_CHOICES = (
    ("dashboard_manager", "مدير النظام"),
    ("accounts_manager", "مدير الحسابات"),
    ("technical_support", "الدعم الفني"),
    ("store_supervisor", "مشرف المتاجر"),
    ("system_developer", "مطور النظام"),
)


def get_admin_desktop_role_permissions(role: str) -> list[str]:
    if role == ADMIN_DESKTOP_FULL_ADMIN_ROLE:
        return list(ADMIN_DESKTOP_ALL_PERMISSIONS)
    if role == "dashboard_manager":
        return [code for code in ADMIN_DESKTOP_ALL_PERMISSIONS if code != "app_updates"]
    if role == "accounts_manager":
        return [
            "dashboard",
            "reports",
            "invoices_payments",
        ]
    if role == "technical_support":
        return [
            "support_actions",
            "support_center",
            "abuse_reports",
        ]
    if role == "store_supervisor":
        return [
            "store_management",
            "approvals",
        ]
    return []


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


class AdminDesktopUser(models.Model):
    name = models.CharField(max_length=100, verbose_name="اسم المستخدم")
    phone_number = models.CharField(max_length=20, unique=True, verbose_name="رقم الهاتف")
    email = models.EmailField(blank=True, null=True, verbose_name="البريد الإلكتروني")
    password = models.CharField(max_length=128, verbose_name="كلمة المرور")
    role = models.CharField(max_length=50, choices=ADMIN_DESKTOP_ROLE_CHOICES, verbose_name="الدور")
    permissions = models.JSONField(default=list, blank=True, verbose_name="الصلاحيات")
    profile_image = models.ImageField(
        upload_to="admin_desktop_profiles/",
        blank=True,
        null=True,
        verbose_name="صورة المستخدم",
    )
    is_active = models.BooleanField(default=True, verbose_name="نشط")
    last_login_at = models.DateTimeField(blank=True, null=True, verbose_name="آخر تسجيل دخول")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="تاريخ الإنشاء")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="تاريخ التحديث")

    class Meta:
        verbose_name = "مستخدم الديسكتوب"
        verbose_name_plural = "مستخدمو الديسكتوب"
        ordering = ["-created_at"]

    def set_password(self, raw_password):
        self.password = make_password(raw_password)

    def check_password(self, raw_password):
        if not self.password:
            return False
        return check_password(raw_password, self.password)

    def apply_role_permissions(self):
        self.permissions = get_admin_desktop_role_permissions(self.role)

    def get_resolved_permissions(self) -> list[str]:
        return get_admin_desktop_role_permissions(self.role)

    def sync_role_permissions(self, *, save: bool = False):
        resolved_permissions = self.get_resolved_permissions()
        if self.permissions != resolved_permissions:
            self.permissions = resolved_permissions
            if save and self.pk:
                self.save(update_fields=["permissions"])
        return self.permissions

    def save(self, *args, **kwargs):
        update_fields = kwargs.get("update_fields")

        if self.phone_number:
            self.phone_number = normalize_phone(self.phone_number)

        if self.password and not self.password.startswith("pbkdf2_"):
            self.password = make_password(self.password)

        if not self.permissions:
            self.apply_role_permissions()

        if update_fields is not None:
            update_fields = set(update_fields)
            if "phone_number" in update_fields:
                self.phone_number = normalize_phone(self.phone_number)
            if "password" in update_fields and self.password and not self.password.startswith("pbkdf2_"):
                self.password = make_password(self.password)
            if "role" in update_fields and "permissions" not in update_fields:
                self.apply_role_permissions()
                update_fields.add("permissions")
            kwargs["update_fields"] = list(update_fields)

        super().save(*args, **kwargs)

    @property
    def is_authenticated(self):
        return True

    @property
    def role_display(self):
        return self.get_role_display()

    def has_permission(self, permission_code: str) -> bool:
        return permission_code in self.get_resolved_permissions()

    def __str__(self):
        return f"{self.name} - {self.get_role_display()} ({self.phone_number})"


class AdminDesktopActivityLog(models.Model):
    ACTION_CATEGORY_CHOICES = (
        ("all", "الكل"),
        ("data_operations", "عمليات البيانات"),
        ("review_actions", "عمليات المراجعة"),
        ("suspension_actions", "إجراءات التعليق"),
    )

    actor = models.ForeignKey(
        "user.AdminDesktopUser",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="activity_logs",
        verbose_name="المنفذ",
    )
    actor_name = models.CharField(max_length=120, verbose_name="اسم المنفذ")
    actor_role = models.CharField(max_length=50, choices=ADMIN_DESKTOP_ROLE_CHOICES, verbose_name="الدور")
    section_key = models.CharField(max_length=60, verbose_name="القسم")
    section_label = models.CharField(max_length=120, verbose_name="القسم المعروض")
    action_key = models.CharField(max_length=60, verbose_name="نوع الإجراء")
    action_label = models.CharField(max_length=120, verbose_name="نوع الإجراء المعروض")
    action_category = models.CharField(
        max_length=30,
        choices=ACTION_CATEGORY_CHOICES,
        default="data_operations",
        verbose_name="تصنيف نوع الإجراء",
    )
    target_name = models.CharField(max_length=150, blank=True, null=True, verbose_name="اسم الهدف")
    details = models.TextField(blank=True, null=True, verbose_name="التفاصيل")
    metadata = models.JSONField(default=dict, blank=True, verbose_name="بيانات إضافية")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="وقت التنفيذ")

    class Meta:
        verbose_name = "سجل نشاط إداري"
        verbose_name_plural = "سجل النشاطات الإدارية"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["actor_role", "-created_at"]),
            models.Index(fields=["action_category", "-created_at"]),
            models.Index(fields=["section_key", "-created_at"]),
        ]

    def __str__(self):
        return f"{self.actor_name} - {self.action_label}"


class AdminApprovalRequest(models.Model):
    REQUEST_TYPE_CHOICES = (
        ("image_publish", "طلب نشر صورة"),
        ("shop_edit", "طلب تعديل بيانات"),
        ("offer", "طلب عروض"),
    )
    STATUS_CHOICES = (
        ("pending", "قيد المراجعة"),
        ("approved", "مقبول"),
        ("rejected", "مرفوض"),
    )

    shop_owner = models.ForeignKey(
        "user.ShopOwner",
        on_delete=models.CASCADE,
        related_name="approval_requests",
        verbose_name="المحل",
    )
    request_type = models.CharField(max_length=30, choices=REQUEST_TYPE_CHOICES, verbose_name="نوع الطلب")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="pending", verbose_name="الحالة")
    payload = models.JSONField(default=dict, blank=True, verbose_name="بيانات الطلب")
    gallery_image = models.ForeignKey(
        "gallery.GalleryImage",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="approval_requests",
        verbose_name="صورة المعرض",
    )
    offer = models.ForeignKey(
        "shop.Offer",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="approval_requests",
        verbose_name="العرض",
    )
    reviewed_by = models.ForeignKey(
        "user.AdminDesktopUser",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="reviewed_approval_requests",
        verbose_name="تمت المراجعة بواسطة",
    )
    reviewed_at = models.DateTimeField(null=True, blank=True, verbose_name="تاريخ المراجعة")
    rejection_reason = models.TextField(blank=True, null=True, verbose_name="سبب الرفض")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="تاريخ الإنشاء")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="تاريخ التحديث")

    class Meta:
        verbose_name = "طلب موافقة"
        verbose_name_plural = "طلبات الموافقات"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["request_type", "status"]),
            models.Index(fields=["shop_owner", "request_type"]),
        ]

    def __str__(self):
        return f"{self.get_request_type_display()} - {self.shop_owner.shop_name} - {self.get_status_display()}"


class ShopOwner(models.Model):
    """نموذج صاحب المحل."""
    ADMIN_STATUS_CHOICES = (
        ("active", "نشط"),
        ("pending_review", "قيد المراجعة"),
        ("suspended", "موقوف"),
    )


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
    admin_status = models.CharField(max_length=20, choices=ADMIN_STATUS_CHOICES, default="active", verbose_name="الحالة الإدارية")
    commission_rate = models.DecimalField(max_digits=5, decimal_places=2, default=0, verbose_name="نسبة العمولة")
    suspension_reason = models.TextField(blank=True, null=True, verbose_name="سبب التعليق")
    suspension_started_at = models.DateTimeField(blank=True, null=True, verbose_name="تاريخ بدء التعليق")
    suspension_ends_at = models.DateTimeField(blank=True, null=True, verbose_name="تاريخ انتهاء التعليق")
    admin_notes = models.TextField(blank=True, null=True, verbose_name="ملاحظات الإدارة")
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
