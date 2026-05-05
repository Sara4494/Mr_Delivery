import uuid

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone
from user.models import ShopOwner


def _generate_public_token(prefix):
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


class ShopStatus(models.Model):
    """نموذج حالة المتجر"""
    STATUS_CHOICES = [
        ('open', 'مفتوح'),
        ('busy', 'مشغول'),
        ('closed', 'مغلق'),
    ]
    
    shop_owner = models.OneToOneField(ShopOwner, on_delete=models.CASCADE, related_name='shop_status', verbose_name="صاحب المحل")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='closed', verbose_name="الحالة")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="تاريخ التحديث")

    class Meta:
        verbose_name = "حالة المتجر"
        verbose_name_plural = "حالات المتاجر"
    
    def __str__(self):
        return f"{self.shop_owner.shop_name} - {self.get_status_display()}"


class Customer(models.Model):
    """نموذج العميل"""
    shop_owner = models.ForeignKey(ShopOwner, on_delete=models.CASCADE, related_name='customers', verbose_name="صاحب المحل", null=True, blank=True)
    name = models.CharField(max_length=100, verbose_name="اسم العميل")
    phone_number = models.CharField(max_length=20, unique=True, verbose_name="رقم الهاتف")
    email = models.EmailField(unique=True, blank=True, null=True, verbose_name="البريد الإلكتروني")
    password = models.CharField(max_length=128, blank=True, null=True, verbose_name="كلمة المرور")
    profile_image = models.ImageField(upload_to='customer_profiles/', blank=True, null=True, verbose_name="صورة العميل")
    google_profile_image_url = models.URLField(blank=True, null=True, verbose_name="رابط صورة جوجل")
    is_online = models.BooleanField(default=False, verbose_name="متصل الآن")
    last_seen = models.DateTimeField(blank=True, null=True, verbose_name="آخر ظهور")
    is_verified = models.BooleanField(default=False, verbose_name="تم التحقق")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="تاريخ الإنشاء")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="تاريخ التحديث")

    class Meta:
        verbose_name = "عميل"
        verbose_name_plural = "العملاء"
        ordering = ['-updated_at']
        indexes = [
            models.Index(fields=['-updated_at']),
            models.Index(fields=['phone_number']),
            models.Index(fields=['email']),
        ]

    def set_password(self, raw_password):
        """تشفير كلمة المرور"""
        from django.contrib.auth.hashers import make_password
        self.password = make_password(raw_password)

    def check_password(self, raw_password):
        """التحقق من كلمة المرور"""
        from django.contrib.auth.hashers import check_password
        if not self.password:
            return False
        return check_password(raw_password, self.password)

    def save(self, *args, **kwargs):
        """تشفير كلمة المرور تلقائياً عند الحفظ"""
        from django.contrib.auth.hashers import make_password
        if self.password and not self.password.startswith('pbkdf2_'):
            self.password = make_password(self.password)
        super().save(*args, **kwargs)

    @property
    def is_authenticated(self):
        """للتوافق مع Django authentication"""
        return True

    def __str__(self):
        return f"{self.name} - {self.email or self.phone_number}"


class CustomerPresenceConnection(models.Model):
    """Active websocket connections used to derive customer presence."""

    customer = models.ForeignKey(
        Customer,
        on_delete=models.CASCADE,
        related_name='presence_connections',
        verbose_name="العميل",
    )
    channel_name = models.CharField(max_length=255, unique=True, verbose_name="اسم القناة")
    connection_type = models.CharField(max_length=50, default='websocket', verbose_name="نوع الاتصال")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="تاريخ الإنشاء")

    class Meta:
        verbose_name = "اتصال حضور العميل"
        verbose_name_plural = "اتصالات حضور العميل"
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['customer', '-created_at']),
        ]

    def __str__(self):
        return f"{self.customer_id} - {self.connection_type} - {self.channel_name}"


class CustomerAddress(models.Model):
    """نموذج عناوين العميل (يدعم عناوين متعددة)"""
    ADDRESS_TYPE_CHOICES = [
        ('home', 'المنزل'),
        ('work', 'العمل'),
        ('other', 'أخرى'),
    ]
    
    customer = models.ForeignKey(Customer, on_delete=models.CASCADE, related_name='addresses', verbose_name="العميل")
    title = models.CharField(max_length=100, verbose_name="عنوان مختصر")
    address_type = models.CharField(max_length=20, choices=ADDRESS_TYPE_CHOICES, default='home', verbose_name="نوع العنوان")
    full_address = models.TextField(verbose_name="العنوان الكامل")
    city = models.CharField(max_length=150, blank=True, null=True, verbose_name="المدينة")
    area = models.CharField(max_length=150, blank=True, null=True, verbose_name="المنطقة")
    street_name = models.CharField(max_length=150, blank=True, null=True, verbose_name="اسم الشارع")
    landmark = models.CharField(max_length=150, blank=True, null=True, verbose_name="أقرب علامة مميزة")
    latitude = models.DecimalField(max_digits=10, decimal_places=7, blank=True, null=True, verbose_name="خط العرض")
    longitude = models.DecimalField(max_digits=10, decimal_places=7, blank=True, null=True, verbose_name="خط الطول")
    building_number = models.CharField(max_length=50, blank=True, null=True, verbose_name="رقم المبنى")
    floor = models.CharField(max_length=20, blank=True, null=True, verbose_name="الطابق")
    apartment = models.CharField(max_length=20, blank=True, null=True, verbose_name="رقم الشقة")
    notes = models.TextField(blank=True, null=True, verbose_name="ملاحظات")
    is_default = models.BooleanField(default=False, verbose_name="العنوان الافتراضي")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="تاريخ الإنشاء")

    class Meta:
        verbose_name = "عنوان عميل"
        verbose_name_plural = "عناوين العملاء"
        ordering = ['-is_default', '-created_at']

    def save(self, *args, **kwargs):
        if self.is_default:
            CustomerAddress.objects.filter(customer=self.customer, is_default=True).update(is_default=False)
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.customer.name} - {self.title}"


class Employee(models.Model):
    """نموذج الموظف"""
    ROLE_CHOICES = [
        ('cashier', 'كاشير'),
        ('accountant', 'محاسب'),
        ('supervisor', 'مشرف عمليات'),
        ('customer_service', 'خدمة عملاء'),
        ('sales', 'مندوب مبيعات'),
        ('hr', 'موارد بشرية'),
        ('manager', 'مدير فرع'),
    ]
    
    shop_owner = models.ForeignKey(ShopOwner, on_delete=models.CASCADE, related_name='employees', verbose_name="صاحب المحل")
    name = models.CharField(max_length=100, verbose_name="اسم الموظف")
    phone_number = models.CharField(max_length=20, verbose_name="رقم الهاتف")
    password = models.CharField(max_length=128, verbose_name="كلمة المرور")
    role = models.CharField(max_length=50, choices=ROLE_CHOICES, default='cashier', verbose_name="الدور")
    profile_image = models.ImageField(upload_to='employee_profiles/', blank=True, null=True, verbose_name="صورة الموظف")
    custody_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0, verbose_name="المبلغ في العهدة")
    is_active = models.BooleanField(default=True, verbose_name="نشط")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="تاريخ الإنشاء")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="تاريخ التحديث")

    class Meta:
        verbose_name = "موظف"
        verbose_name_plural = "الموظفين"
        unique_together = ['shop_owner', 'phone_number']  # نفس الرقم لا يمكن أن يكون لموظفين مختلفين لنفس المحل
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['shop_owner', 'role']),
            models.Index(fields=['shop_owner', 'is_active']),
        ]

    def set_password(self, raw_password):
        """تشفير كلمة المرور"""
        from django.contrib.auth.hashers import make_password
        self.password = make_password(raw_password)

    def check_password(self, raw_password):
        """التحقق من كلمة المرور"""
        from django.contrib.auth.hashers import check_password
        return check_password(raw_password, self.password)

    def save(self, *args, **kwargs):
        """تشفير كلمة المرور تلقائياً عند الحفظ"""
        from django.contrib.auth.hashers import make_password
        if not self.pk or 'password' in kwargs.get('update_fields', []):
            if not self.password.startswith('pbkdf2_'):
                self.password = make_password(self.password)
        super().save(*args, **kwargs)
    
    @property
    def is_authenticated(self):
        """للتوافق مع Django authentication"""
        return True
    
    @property
    def total_orders_count(self):
        """عدد الطلبات التي تعامل معها الموظف"""
        return self.orders_handled.count()

    def __str__(self):
        return f"{self.name} - {self.get_role_display()} ({self.phone_number})"


class Driver(models.Model):
    """نموذج السائق"""
    STATUS_CHOICES = [
        ('available', 'متاح'),
        ('busy', 'مشغول'),
        ('unavailable', 'غير متاح'),
        ('offline', 'غير متصل'),
    ]
    VEHICLE_TYPE_CHOICES = [
        ('motorcycle', 'دراجة نارية'),
        ('bicycle', 'دراجة'),
    ]
    
    # تم تغيير العلاقة لدعم تعدد المتاجر، السائق يمكنه العمل في أكثر من محل
    shops = models.ManyToManyField(ShopOwner, through='ShopDriver', related_name='drivers', verbose_name="المتاجر")
    
    name = models.CharField(max_length=100, verbose_name="اسم السائق")
    phone_number = models.CharField(max_length=20, unique=True, verbose_name="رقم الهاتف")
    password = models.CharField(max_length=128, verbose_name="كلمة المرور", blank=True, null=True)  # إضافة password للسائق
    profile_image = models.ImageField(upload_to='driver_profiles/', blank=True, null=True, verbose_name="صورة السائق")
    vehicle_label = models.CharField(max_length=120, blank=True, null=True, verbose_name="وصف المركبة")
    plate_number = models.CharField(max_length=50, blank=True, null=True, verbose_name="رقم اللوحة")
    vehicle_type = models.CharField(
        max_length=20,
        choices=VEHICLE_TYPE_CHOICES,
        blank=True,
        null=True,
        verbose_name="نوع المركبة",
    )
    is_verified = models.BooleanField(default=True, verbose_name="تم التحقق")
    is_online = models.BooleanField(default=False, verbose_name="متصل الآن")
    availability_enabled = models.BooleanField(default=False, verbose_name="يرغب في استقبال الطلبات")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='offline', verbose_name="الحالة التشغيلية")
    current_orders_count = models.IntegerField(default=0, verbose_name="عدد الطلبات الحالية")
    rating = models.DecimalField(max_digits=3, decimal_places=2, default=0.0, verbose_name="التقييم")
    total_rides = models.IntegerField(default=0, verbose_name="إجمالي الرحلات")
    # حقول تتبع الموقع
    current_latitude = models.DecimalField(max_digits=10, decimal_places=7, blank=True, null=True, verbose_name="خط العرض الحالي")
    current_longitude = models.DecimalField(max_digits=10, decimal_places=7, blank=True, null=True, verbose_name="خط الطول الحالي")
    location_updated_at = models.DateTimeField(blank=True, null=True, verbose_name="آخر تحديث للموقع")
    last_seen_at = models.DateTimeField(blank=True, null=True, verbose_name="آخر ظهور")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="تاريخ الإنشاء")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="تاريخ التحديث")

    class Meta:
        verbose_name = "سائق"
        verbose_name_plural = "السائقين"
        ordering = ['-updated_at']

    def set_password(self, raw_password):
        """تشفير كلمة المرور"""
        from django.contrib.auth.hashers import make_password
        if raw_password:
            self.password = make_password(raw_password)

    def check_password(self, raw_password):
        """التحقق من كلمة المرور"""
        from django.contrib.auth.hashers import check_password
        if not self.password:
            return False
        return check_password(raw_password, self.password)

    def save(self, *args, **kwargs):
        """تشفير كلمة المرور تلقائياً عند الحفظ"""
        from django.contrib.auth.hashers import make_password
        if self.password and not self.password.startswith('pbkdf2_'):
            self.password = make_password(self.password)
        super().save(*args, **kwargs)
    
    @property
    def is_authenticated(self):
        """للتوافق مع Django authentication"""
        return True

    def __str__(self):
        return f"{self.name} - {self.get_status_display()}"

    @property
    def shop_owner(self):
        """للتوافق مع لوحة التحكم (Admin): إرجاع أول متجر مرتبط"""
        return self.shops.first()

    def get_active_orders_count(self):
        orders_manager = getattr(self, 'orders', None)
        if orders_manager is None or not hasattr(orders_manager, 'filter'):
            return int(getattr(self, 'current_orders_count', 0) or 0)
        return orders_manager.filter(status__in=['confirmed', 'preparing', 'on_way']).count()

    def get_in_delivery_orders_count(self):
        orders_manager = getattr(self, 'orders', None)
        if orders_manager is None or not hasattr(orders_manager, 'filter'):
            return 0
        return orders_manager.filter(status__in=['preparing', 'on_way']).count()

    def get_max_active_orders_limit(self):
        raw_value = getattr(settings, 'MAX_ACTIVE_ORDERS_PER_DRIVER', 2)
        try:
            limit = int(raw_value)
        except (TypeError, ValueError):
            limit = 2
        return max(limit, 1)

    def get_availability_snapshot(self, *, active_orders_count=None, in_delivery_count=None):
        active_orders_count = self.get_active_orders_count() if active_orders_count is None else int(active_orders_count or 0)
        in_delivery_count = self.get_in_delivery_orders_count() if in_delivery_count is None else int(in_delivery_count or 0)
        max_active_orders = self.get_max_active_orders_limit()

        moderation = None
        try:
            moderation = self.moderation_status
        except Exception:
            moderation = None

        is_suspended = bool(getattr(moderation, 'is_suspended', False))
        presence_online = bool(self.is_online)
        availability_enabled = bool(getattr(self, 'availability_enabled', False))

        reason = None
        if not self.is_verified or is_suspended:
            status = 'unavailable'
            can_receive_orders = False
            reason = 'account_restricted'
        elif not presence_online:
            status = 'offline'
            can_receive_orders = False
            reason = 'offline'
        elif not availability_enabled:
            status = 'unavailable'
            can_receive_orders = False
            reason = 'availability_disabled'
        elif active_orders_count >= max_active_orders:
            status = 'busy'
            can_receive_orders = False
            reason = 'max_active_orders'
        else:
            status = 'available'
            can_receive_orders = True
            reason = 'available'

        return {
            'presence_online': presence_online,
            'is_online': presence_online,
            'availability_enabled': availability_enabled,
            'can_receive_orders': can_receive_orders,
            'status': status,
            'active_orders_count': active_orders_count,
            'in_delivery_count': in_delivery_count,
            'max_active_orders_per_driver': max_active_orders,
            'reason': reason,
        }


class ShopDriver(models.Model):
    """جدول وسيط لربط السائق بالمتجر وإدارة حالة الدعوة"""
    STATUS_CHOICES = [
        ('pending', 'بانتظار الموافقة'),
        ('active', 'نشط'),
        ('blocked', 'محظور'),
        ('rejected', 'مرفوض'),
    ]
    
    shop_owner = models.ForeignKey(ShopOwner, on_delete=models.CASCADE, related_name='shop_drivers', verbose_name="المحل")
    driver = models.ForeignKey(Driver, on_delete=models.CASCADE, related_name='driver_shops', verbose_name="السائق")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending', verbose_name="حالة الارتباط")
    joined_at = models.DateTimeField(auto_now_add=True, verbose_name="تاريخ الانضمام")

    class Meta:
        unique_together = ['shop_owner', 'driver']
        verbose_name = "سائق في محل"
        verbose_name_plural = "سائقين المحلات"


class Order(models.Model):
    """نموذج الطلب"""
    STATUS_CHOICES = [
        ('new', 'جديد'),
        ('pending_customer_confirm', 'في انتظار تأكيد العميل'),
        ('confirmed', 'مؤكد'),
        ('preparing', 'قيد التحضير'),
        ('on_way', 'في الطريق'),
        ('delivered', 'تم التسليم'),
        ('cancelled', 'ملغي'),
    ]
    
    PAYMENT_METHOD_CHOICES = [
        ('cash', 'نقداً عند الاستلام'),
        ('card', 'بطاقة ائتمان'),
        ('wallet', 'محفظة إلكترونية'),
    ]
    
    shop_owner = models.ForeignKey(ShopOwner, on_delete=models.CASCADE, related_name='orders', verbose_name="صاحب المحل")
    customer = models.ForeignKey(Customer, on_delete=models.CASCADE, related_name='orders', verbose_name="العميل")
    employee = models.ForeignKey(Employee, on_delete=models.SET_NULL, null=True, blank=True, related_name='orders_handled', verbose_name="الموظف المسؤول")
    driver = models.ForeignKey(Driver, on_delete=models.SET_NULL, null=True, blank=True, related_name='orders', verbose_name="السائق")
    delivery_address = models.ForeignKey('CustomerAddress', on_delete=models.SET_NULL, null=True, blank=True, related_name='orders', verbose_name="عنوان التوصيل")
    order_number = models.CharField(max_length=50, unique=True, verbose_name="رقم الطلب")
    status = models.CharField(max_length=32, choices=STATUS_CHOICES, default='new', verbose_name="حالة الطلب")
    items = models.TextField(verbose_name="الأصناف")  # JSON string أو text
    total_amount = models.DecimalField(max_digits=10, decimal_places=2, verbose_name="المبلغ الإجمالي")
    delivery_fee = models.DecimalField(max_digits=10, decimal_places=2, default=0, verbose_name="رسوم التوصيل")
    address = models.TextField(verbose_name="العنوان الكامل")
    payment_method = models.CharField(max_length=20, choices=PAYMENT_METHOD_CHOICES, default='cash', verbose_name="طريقة الدفع")
    is_paid = models.BooleanField(default=False, verbose_name="تم الدفع")
    notes = models.TextField(blank=True, null=True, verbose_name="ملاحظات")
    unread_messages_count = models.IntegerField(default=0, verbose_name="عدد الرسائل غير المقروءة")
    estimated_delivery_time = models.DateTimeField(blank=True, null=True, verbose_name="الوقت المتوقع للتوصيل")
    driver_assigned_at = models.DateTimeField(blank=True, null=True, verbose_name="وقت تعيين السائق")
    driver_accepted_at = models.DateTimeField(blank=True, null=True, verbose_name="وقت قبول السائق")
    driver_chat_opened_at = models.DateTimeField(blank=True, null=True, verbose_name="وقت فتح شات السائق مع العميل")
    delivered_at = models.DateTimeField(blank=True, null=True, verbose_name="وقت التسليم الفعلي")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="تاريخ الإنشاء")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="تاريخ التحديث")

    class Meta:
        verbose_name = "طلب"
        verbose_name_plural = "الطلبات"
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['shop_owner', 'status']),
            models.Index(fields=['shop_owner', '-created_at']),
        ]

    def __str__(self):
        return f"طلب #{self.order_number} - {self.customer.name}"


class DriverOrderRejection(models.Model):
    """Persistent per-driver rejection state for available delivery orders."""

    driver = models.ForeignKey(
        Driver,
        on_delete=models.CASCADE,
        related_name='order_rejections',
        verbose_name="السائق",
    )
    order = models.ForeignKey(
        Order,
        on_delete=models.CASCADE,
        related_name='driver_rejections',
        verbose_name="الطلب",
    )
    reason = models.CharField(max_length=120, blank=True, null=True, verbose_name="سبب الرفض")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="تاريخ الإنشاء")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="تاريخ التحديث")

    class Meta:
        verbose_name = "رفض سائق للطلب"
        verbose_name_plural = "رفض السائقين للطلبات"
        ordering = ['-updated_at', '-created_at']
        constraints = [
            models.UniqueConstraint(fields=['driver', 'order'], name='unique_driver_order_rejection'),
        ]
        indexes = [
            models.Index(fields=['driver', '-updated_at'], name='drvordrej_driver_idx'),
            models.Index(fields=['order', '-updated_at'], name='drvordrej_order_idx'),
        ]

    def __str__(self):
        return f"رفض الطلب #{self.order_id} بواسطة السائق #{self.driver_id}"


class DriverPresenceConnection(models.Model):
    """Active websocket connections used to derive driver presence."""

    driver = models.ForeignKey(
        Driver,
        on_delete=models.CASCADE,
        related_name='presence_connections',
        verbose_name="السائق",
    )
    channel_name = models.CharField(max_length=255, unique=True, verbose_name="اسم القناة")
    connection_type = models.CharField(max_length=50, default='websocket', verbose_name="نوع الاتصال")
    last_heartbeat_at = models.DateTimeField(blank=True, null=True, verbose_name="آخر heartbeat")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="تاريخ الإنشاء")

    class Meta:
        verbose_name = "اتصال حضور السائق"
        verbose_name_plural = "اتصالات حضور السائق"
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['driver', '-created_at'], name='drvprs_driver_created_idx'),
            models.Index(fields=['driver', '-last_heartbeat_at'], name='drvprs_driver_heartbeat_idx'),
        ]

    def __str__(self):
        return f"{self.driver_id} - {self.connection_type} - {self.channel_name}"


class FCMDeviceToken(models.Model):
    """Registered mobile device tokens for Firebase Cloud Messaging."""

    USER_TYPE_CHOICES = [
        ('customer', 'عميل'),
        ('shop_owner', 'صاحب المحل'),
        ('employee', 'موظف'),
        ('driver', 'سائق'),
    ]
    PLATFORM_CHOICES = [
        ('android', 'Android'),
        ('ios', 'iOS'),
    ]

    user_type = models.CharField(max_length=20, choices=USER_TYPE_CHOICES, verbose_name="نوع المستخدم")
    user_id = models.PositiveBigIntegerField(verbose_name="معرف المستخدم")
    device_id = models.CharField(max_length=191, verbose_name="معرف الجهاز")
    platform = models.CharField(max_length=20, choices=PLATFORM_CHOICES, verbose_name="المنصة")
    fcm_token = models.TextField(verbose_name="رمز FCM")
    app_version = models.CharField(max_length=50, blank=True, null=True, verbose_name="إصدار التطبيق")
    is_active = models.BooleanField(default=True, verbose_name="نشط")
    last_seen_at = models.DateTimeField(blank=True, null=True, verbose_name="آخر ظهور")
    last_used_at = models.DateTimeField(blank=True, null=True, verbose_name="آخر استخدام")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="تاريخ الإنشاء")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="تاريخ التحديث")

    class Meta:
        verbose_name = "رمز جهاز FCM"
        verbose_name_plural = "رموز أجهزة FCM"
        ordering = ['-updated_at', '-created_at']
        constraints = [
            models.UniqueConstraint(fields=['user_type', 'user_id', 'device_id'], name='unique_fcm_device_per_user'),
        ]
        indexes = [
            models.Index(fields=['user_type', 'user_id', 'is_active'], name='fcm_user_active_idx'),
            models.Index(fields=['device_id'], name='fcm_device_id_idx'),
            models.Index(fields=['fcm_token'], name='fcm_token_idx'),
            models.Index(fields=['is_active', '-updated_at'], name='fcm_active_updated_idx'),
        ]

    def __str__(self):
        return f"{self.user_type}:{self.user_id}:{self.device_id}"


class DriverChatConversation(models.Model):
    STATUS_CHOICES = [
        ('waiting_reply', 'في انتظار الرد'),
        ('awaiting_driver_acceptance', 'بانتظار موافقة السائق'),
        ('transfer_requested', 'تم طلب التحويل'),
        ('driver_busy', 'السائق مشغول'),
        ('driver_on_way', 'السائق في الطريق'),
        ('driver_arrived', 'السائق وصل'),
        ('transferred_to_another_driver', 'تم التحويل لسائق آخر'),
        ('delivered', 'تم التسليم'),
        ('cancelled', 'ملغي'),
        ('rejected', 'مرفوض'),
    ]

    shop_owner = models.ForeignKey(ShopOwner, on_delete=models.CASCADE, related_name='driver_chat_conversations', verbose_name="المتجر")
    driver = models.ForeignKey(Driver, on_delete=models.CASCADE, related_name='shop_conversations', verbose_name="السائق")
    public_id = models.CharField(max_length=64, unique=True, blank=True, verbose_name="المعرف العام")
    status = models.CharField(max_length=40, choices=STATUS_CHOICES, default='waiting_reply', verbose_name="حالة المحادثة")
    unread_count = models.PositiveIntegerField(default=0, verbose_name="عدد الرسائل غير المقروءة")
    last_message_preview = models.TextField(blank=True, null=True, verbose_name="معاينة آخر رسالة")
    last_message_at = models.DateTimeField(blank=True, null=True, verbose_name="وقت آخر رسالة")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="تاريخ الإنشاء")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="تاريخ التحديث")

    class Meta:
        verbose_name = "محادثة سائق"
        verbose_name_plural = "محادثات السائقين"
        ordering = ['-updated_at', '-created_at']
        constraints = [
            models.UniqueConstraint(fields=['shop_owner', 'driver'], name='unique_shop_driver_conversation')
        ]
        indexes = [
            models.Index(fields=['shop_owner', '-updated_at'], name='drvchatconv_shop_upd_idx'),
            models.Index(fields=['driver', '-updated_at'], name='drvchatconv_driver_upd_idx'),
            models.Index(fields=['public_id'], name='drvchatconv_public_idx'),
        ]

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        if not self.public_id:
            self.public_id = f"conv_{self.pk}"
            super().save(update_fields=['public_id'])

    def __str__(self):
        return f"{self.shop_owner_id}:{self.driver_id}"


class DriverChatOrder(models.Model):
    STATUS_CHOICES = DriverChatConversation.STATUS_CHOICES

    conversation = models.ForeignKey(DriverChatConversation, on_delete=models.CASCADE, related_name='orders', verbose_name="المحادثة")
    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name='driver_chat_links', verbose_name="الطلب")
    status = models.CharField(max_length=40, choices=STATUS_CHOICES, default='waiting_reply', verbose_name="حالة الطلب")
    transfer_reason = models.TextField(blank=True, null=True, verbose_name="سبب التحويل")
    is_active = models.BooleanField(default=True, verbose_name="نشط")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="تاريخ الإنشاء")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="تاريخ التحديث")

    class Meta:
        verbose_name = "أوردر في محادثة سائق"
        verbose_name_plural = "أوردرات محادثات السائقين"
        ordering = ['-updated_at', '-created_at']
        constraints = [
            models.UniqueConstraint(fields=['conversation', 'order'], name='unique_driver_chat_order_per_conversation')
        ]
        indexes = [
            models.Index(fields=['conversation', '-updated_at'], name='drvchatord_conv_upd_idx'),
            models.Index(fields=['order', '-updated_at'], name='drvchatord_order_upd_idx'),
            models.Index(fields=['status'], name='drvchatord_status_idx'),
        ]

    def __str__(self):
        return f"{self.conversation_id}:{self.order_id}:{self.status}"


class DriverChatCall(models.Model):
    STATUS_CHOICES = [
        ('initiated', 'تم بدء الاتصال'),
        ('ringing', 'جاري الرن'),
        ('accepted', 'تم القبول'),
        ('rejected', 'تم الرفض'),
        ('cancelled', 'تم الإلغاء'),
        ('ended', 'تم إنهاء الاتصال'),
        ('missed', 'مكالمة فائتة'),
        ('timeout', 'انتهى الوقت'),
        ('failed', 'فشل الاتصال'),
    ]
    INITIATOR_CHOICES = [
        ('store', 'المتجر'),
        ('driver', 'السائق'),
    ]

    conversation = models.ForeignKey(DriverChatConversation, on_delete=models.CASCADE, related_name='calls', verbose_name="المحادثة")
    public_id = models.CharField(max_length=64, unique=True, blank=True, verbose_name="المعرف العام")
    initiated_by = models.CharField(max_length=20, choices=INITIATOR_CHOICES, verbose_name="بدأها")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='initiated', verbose_name="الحالة")
    reason = models.CharField(max_length=120, blank=True, null=True, verbose_name="السبب")
    channel_name = models.CharField(max_length=120, blank=True, null=True, verbose_name="اسم غرفة الاتصال")
    rtc_token = models.TextField(blank=True, null=True, verbose_name="رمز RTC")
    answered_at = models.DateTimeField(blank=True, null=True, verbose_name="وقت الرد")
    ended_at = models.DateTimeField(blank=True, null=True, verbose_name="وقت الإنهاء")
    duration_seconds = models.PositiveIntegerField(default=0, verbose_name="مدة المكالمة بالثواني")
    metadata = models.JSONField(blank=True, null=True, verbose_name="بيانات إضافية")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="تاريخ الإنشاء")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="تاريخ التحديث")

    class Meta:
        verbose_name = "مكالمة سائق"
        verbose_name_plural = "مكالمات السائقين"
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['conversation', '-created_at'], name='drvchatcall_conv_idx'),
            models.Index(fields=['public_id'], name='drvchatcall_public_idx'),
            models.Index(fields=['status'], name='drvchatcall_status_idx'),
        ]

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        if not self.public_id:
            self.public_id = f"call_{self.pk}"
            super().save(update_fields=['public_id'])

    def __str__(self):
        return f"{self.public_id}:{self.status}"


class DriverChatMessage(models.Model):
    MESSAGE_TYPE_CHOICES = [
        ('text', 'نص'),
        ('voice', 'صوت'),
        ('invoice', 'فاتورة'),
        ('system', 'نظام'),
        ('call', 'اتصال'),
    ]
    SENDER_CHOICES = [
        ('store', 'المتجر'),
        ('driver', 'السائق'),
        ('system', 'النظام'),
    ]
    DELIVERY_STATUS_CHOICES = [
        ('sent', 'تم الإرسال'),
        ('delivered', 'تم التسليم'),
        ('read', 'تمت القراءة'),
        ('failed', 'فشل الإرسال'),
    ]

    conversation = models.ForeignKey(DriverChatConversation, on_delete=models.CASCADE, related_name='messages', verbose_name="المحادثة")
    public_id = models.CharField(max_length=64, unique=True, blank=True, verbose_name="المعرف العام")
    message_type = models.CharField(max_length=20, choices=MESSAGE_TYPE_CHOICES, default='text', verbose_name="نوع الرسالة")
    sender_type = models.CharField(max_length=20, choices=SENDER_CHOICES, verbose_name="المرسل")
    text = models.TextField(blank=True, null=True, verbose_name="نص الرسالة")
    audio_url = models.TextField(blank=True, null=True, verbose_name="رابط الصوت")
    voice_duration_seconds = models.PositiveIntegerField(blank=True, null=True, verbose_name="مدة الصوت")
    client_message_id = models.CharField(max_length=120, blank=True, null=True, verbose_name="معرف رسالة العميل")
    delivery_status = models.CharField(max_length=20, choices=DELIVERY_STATUS_CHOICES, default='sent', verbose_name="حالة التسليم")
    conversation_order = models.ForeignKey(DriverChatOrder, on_delete=models.SET_NULL, null=True, blank=True, related_name='messages', verbose_name="الأوردر المرتبط")
    call = models.ForeignKey(DriverChatCall, on_delete=models.SET_NULL, null=True, blank=True, related_name='messages', verbose_name="المكالمة")
    metadata = models.JSONField(blank=True, null=True, verbose_name="بيانات إضافية")
    is_read = models.BooleanField(default=False, verbose_name="مقروءة")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="تاريخ الإرسال")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="تاريخ التحديث")

    class Meta:
        verbose_name = "رسالة محادثة سائق"
        verbose_name_plural = "رسائل محادثات السائقين"
        ordering = ['created_at']
        indexes = [
            models.Index(fields=['conversation', 'created_at'], name='drvchatmsg_conv_created_idx'),
            models.Index(fields=['conversation', '-created_at'], name='drvchatmsg_conv_desc_idx'),
            models.Index(fields=['public_id'], name='drvchatmsg_public_idx'),
            models.Index(fields=['message_type'], name='drvchatmsg_type_idx'),
            models.Index(fields=['sender_type'], name='drvchatmsg_sender_idx'),
        ]

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        if not self.public_id:
            self.public_id = f"msg_{self.pk}"
            super().save(update_fields=['public_id'])

    def __str__(self):
        return f"{self.public_id}:{self.message_type}"


class DriverChatEvent(models.Model):
    shop_owner = models.ForeignKey(ShopOwner, on_delete=models.CASCADE, related_name='driver_chat_events', verbose_name="المتجر")
    conversation = models.ForeignKey(DriverChatConversation, on_delete=models.SET_NULL, null=True, blank=True, related_name='events', verbose_name="المحادثة")
    driver = models.ForeignKey(Driver, on_delete=models.SET_NULL, null=True, blank=True, related_name='driver_chat_events', verbose_name="السائق")
    event_id = models.CharField(max_length=64, unique=True, blank=True, verbose_name="معرف الحدث")
    event_type = models.CharField(max_length=120, verbose_name="نوع الحدث")
    payload = models.JSONField(verbose_name="البيانات")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="تاريخ الإنشاء")

    class Meta:
        verbose_name = "حدث محادثة سائق"
        verbose_name_plural = "أحداث محادثات السائقين"
        ordering = ['created_at']
        indexes = [
            models.Index(fields=['shop_owner', 'created_at'], name='drvchatevt_shop_created_idx'),
            models.Index(fields=['driver', 'created_at'], name='drvchatevt_driver_created_idx'),
            models.Index(fields=['event_id'], name='drvchatevt_event_id_idx'),
            models.Index(fields=['event_type'], name='drvchatevt_type_idx'),
        ]

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        if not self.event_id:
            self.event_id = f"evt_{self.pk}"
            super().save(update_fields=['event_id'])

    def __str__(self):
        return f"{self.event_id}:{self.event_type}"


class ChatMessage(models.Model):
    """نموذج رسائل المحادثة - يدعم الشات بين جميع الأطراف"""
    
    SENDER_TYPE_CHOICES = [
        ('customer', 'عميل'),
        ('shop_owner', 'صاحب المحل'),
        ('employee', 'موظف'),
        ('driver', 'سائق'),
    ]
    
    CHAT_TYPE_CHOICES = [
        ('shop_customer', 'محادثة المحل مع العميل'),
        ('driver_customer', 'محادثة السائق مع العميل'),
    ]
    
    MESSAGE_TYPE_CHOICES = [
        ('text', 'نص'),
        ('audio', 'صوت'),
        ('image', 'صورة'),
        ('location', 'موقع'),
        ('invoice_card', 'فاتورة'),
    ]
    
    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name='messages', verbose_name="الطلب")
    chat_type = models.CharField(max_length=20, choices=CHAT_TYPE_CHOICES, default='shop_customer', verbose_name="نوع المحادثة")
    sender_type = models.CharField(max_length=20, choices=SENDER_TYPE_CHOICES, verbose_name="نوع المرسل")
    
    # حقول المرسل - واحد فقط منهم سيكون له قيمة
    sender_customer = models.ForeignKey(Customer, on_delete=models.SET_NULL, null=True, blank=True, related_name='sent_messages', verbose_name="العميل المرسل")
    sender_shop_owner = models.ForeignKey(ShopOwner, on_delete=models.SET_NULL, null=True, blank=True, related_name='sent_messages', verbose_name="صاحب المحل المرسل")
    sender_employee = models.ForeignKey(Employee, on_delete=models.SET_NULL, null=True, blank=True, related_name='sent_messages', verbose_name="الموظف المرسل")
    sender_driver = models.ForeignKey(Driver, on_delete=models.SET_NULL, null=True, blank=True, related_name='sent_messages', verbose_name="السائق المرسل")
    
    message_type = models.CharField(max_length=20, choices=MESSAGE_TYPE_CHOICES, default='text', verbose_name="نوع الرسالة")
    content = models.TextField(blank=True, null=True, verbose_name="محتوى الرسالة")
    audio_file = models.FileField(upload_to='chat_audio/', blank=True, null=True, verbose_name="ملف صوتي")
    image_file = models.ImageField(upload_to='chat_images/', blank=True, null=True, verbose_name="صورة")
    
    # للرسائل من نوع location
    latitude = models.DecimalField(max_digits=10, decimal_places=7, blank=True, null=True, verbose_name="خط العرض")
    longitude = models.DecimalField(max_digits=10, decimal_places=7, blank=True, null=True, verbose_name="خط الطول")
    metadata = models.JSONField(blank=True, null=True, verbose_name="بيانات إضافية")
    
    is_read = models.BooleanField(default=False, verbose_name="مقروءة")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="تاريخ الإرسال")

    class Meta:
        verbose_name = "رسالة محادثة"
        verbose_name_plural = "رسائل المحادثات"
        ordering = ['created_at']
        indexes = [
            models.Index(fields=['order', 'chat_type', 'created_at']),
        ]

    @property
    def sender_name(self):
        """اسم المرسل"""
        if self.sender_type == 'customer' and self.sender_customer:
            return self.sender_customer.name
        elif self.sender_type == 'shop_owner' and self.sender_shop_owner:
            return self.sender_shop_owner.owner_name
        elif self.sender_type == 'employee' and self.sender_employee:
            return self.sender_employee.name
        elif self.sender_type == 'driver' and self.sender_driver:
            return self.sender_driver.name
        return "غير معروف"

    def __str__(self):
        return f"رسالة من {self.sender_name} ({self.get_sender_type_display()}) - طلب #{self.order.order_number}"


class CustomerSupportConversation(models.Model):
    """Standalone customer support chat with a shop without creating an order."""

    CONVERSATION_TYPE_CHOICES = [
        ('inquiry', 'استفسار'),
        ('complaint', 'شكوى'),
    ]

    STATUS_CHOICES = [
        ('open', 'مفتوحة'),
        ('closed', 'مغلقة'),
    ]

    shop_owner = models.ForeignKey(
        ShopOwner,
        on_delete=models.CASCADE,
        related_name='customer_support_conversations',
        verbose_name="صاحب المحل",
    )
    customer = models.ForeignKey(
        Customer,
        on_delete=models.CASCADE,
        related_name='support_conversations',
        verbose_name="العميل",
    )
    public_id = models.CharField(max_length=64, unique=True, blank=True, verbose_name="المعرف العام")
    conversation_type = models.CharField(
        max_length=20,
        choices=CONVERSATION_TYPE_CHOICES,
        verbose_name="نوع المحادثة",
    )
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default='open',
        verbose_name="الحالة",
    )
    unread_for_customer_count = models.PositiveIntegerField(default=0, verbose_name="غير المقروء للعميل")
    unread_for_shop_count = models.PositiveIntegerField(default=0, verbose_name="غير المقروء للمحل")
    last_message_preview = models.TextField(blank=True, null=True, verbose_name="معاينة آخر رسالة")
    last_message_at = models.DateTimeField(blank=True, null=True, verbose_name="وقت آخر رسالة")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="تاريخ الإنشاء")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="تاريخ التحديث")

    class Meta:
        verbose_name = "محادثة دعم عميل"
        verbose_name_plural = "محادثات دعم العملاء"
        ordering = ['-updated_at', '-created_at']
        indexes = [
            models.Index(fields=['customer', '-updated_at'], name='custsupconv_cust_upd_idx'),
            models.Index(fields=['shop_owner', '-updated_at'], name='custsupconv_shop_upd_idx'),
            models.Index(fields=['public_id'], name='custsupconv_public_idx'),
        ]

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        if not self.public_id:
            self.public_id = f"support_{self.pk}"
            super().save(update_fields=['public_id'])

    def __str__(self):
        return f"{self.public_id}:{self.conversation_type}"


class CustomerSupportMessage(models.Model):
    """Messages inside standalone customer support chats."""

    SENDER_TYPE_CHOICES = [
        ('customer', 'عميل'),
        ('shop_owner', 'صاحب المحل'),
        ('employee', 'موظف'),
    ]

    MESSAGE_TYPE_CHOICES = ChatMessage.MESSAGE_TYPE_CHOICES

    conversation = models.ForeignKey(
        CustomerSupportConversation,
        on_delete=models.CASCADE,
        related_name='messages',
        verbose_name="محادثة الدعم",
    )
    sender_type = models.CharField(max_length=20, choices=SENDER_TYPE_CHOICES, verbose_name="نوع المرسل")
    sender_customer = models.ForeignKey(
        Customer,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='sent_support_messages',
        verbose_name="العميل المرسل",
    )
    sender_shop_owner = models.ForeignKey(
        ShopOwner,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='sent_support_messages',
        verbose_name="صاحب المحل المرسل",
    )
    sender_employee = models.ForeignKey(
        Employee,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='sent_support_messages',
        verbose_name="الموظف المرسل",
    )
    message_type = models.CharField(max_length=20, choices=MESSAGE_TYPE_CHOICES, default='text', verbose_name="نوع الرسالة")
    content = models.TextField(blank=True, null=True, verbose_name="محتوى الرسالة")
    audio_file = models.FileField(upload_to='support_chat_audio/', blank=True, null=True, verbose_name="ملف صوتي")
    image_file = models.ImageField(upload_to='support_chat_images/', blank=True, null=True, verbose_name="صورة")
    latitude = models.DecimalField(max_digits=10, decimal_places=7, blank=True, null=True, verbose_name="خط العرض")
    longitude = models.DecimalField(max_digits=10, decimal_places=7, blank=True, null=True, verbose_name="خط الطول")
    is_read = models.BooleanField(default=False, verbose_name="مقروءة")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="تاريخ الإرسال")

    class Meta:
        verbose_name = "رسالة دعم عميل"
        verbose_name_plural = "رسائل دعم العملاء"
        ordering = ['created_at']
        indexes = [
            models.Index(fields=['conversation', 'created_at'], name='custsupmsg_conv_created_idx'),
        ]

    @property
    def sender_name(self):
        if self.sender_type == 'customer' and self.sender_customer:
            return self.sender_customer.name
        if self.sender_type == 'shop_owner' and self.sender_shop_owner:
            return self.sender_shop_owner.owner_name
        if self.sender_type == 'employee' and self.sender_employee:
            return self.sender_employee.name
        return "غير معروف"

    def __str__(self):
        return f"رسالة دعم من {self.sender_name} - {self.conversation.public_id}"


class ShopSupportTicket(models.Model):
    """Technical support ticket between a shop and the company support desk."""

    PRIORITY_CHOICES = [
        ('low', 'قليلة'),
        ('medium', 'متوسطة'),
        ('high', 'عالية'),
        ('urgent', 'عاجلة'),
    ]

    STATUS_CHOICES = [
        ('open', 'مفتوحة'),
        ('in_progress', 'قيد المتابعة'),
        ('waiting_shop', 'بانتظار المحل'),
        ('waiting_support', 'بانتظار الدعم'),
        ('resolved', 'تم الحل'),
        ('closed', 'مغلقة'),
    ]

    shop_owner = models.ForeignKey(
        ShopOwner,
        on_delete=models.CASCADE,
        related_name='support_tickets',
        verbose_name="المحل",
    )
    created_by_employee = models.ForeignKey(
        Employee,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='created_support_tickets',
        verbose_name="الموظف المنشئ",
    )
    assigned_admin = models.ForeignKey(
        'user.AdminDesktopUser',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='assigned_support_tickets',
        verbose_name="موظف الدعم المسؤول",
    )
    public_id = models.CharField(max_length=64, unique=True, blank=True, verbose_name="المعرف العام")
    subject = models.CharField(max_length=255, verbose_name="عنوان المشكلة")
    priority = models.CharField(max_length=20, choices=PRIORITY_CHOICES, default='medium', verbose_name="الأولوية")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='open', verbose_name="الحالة")
    unread_for_shop_count = models.PositiveIntegerField(default=0, verbose_name="غير المقروء للمحل")
    unread_for_admin_count = models.PositiveIntegerField(default=0, verbose_name="غير المقروء للدعم")
    last_message_preview = models.TextField(blank=True, null=True, verbose_name="معاينة آخر رسالة")
    last_message_at = models.DateTimeField(blank=True, null=True, verbose_name="وقت آخر رسالة")
    resolved_at = models.DateTimeField(blank=True, null=True, verbose_name="وقت الحل")
    closed_at = models.DateTimeField(blank=True, null=True, verbose_name="وقت الإغلاق")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="تاريخ الإنشاء")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="تاريخ التحديث")

    class Meta:
        verbose_name = "تذكرة دعم للمحل"
        verbose_name_plural = "تذاكر دعم المحلات"
        ordering = ['-updated_at', '-created_at']
        indexes = [
            models.Index(fields=['shop_owner', '-updated_at'], name='shopsupticket_shop_upd_idx'),
            models.Index(fields=['status', '-updated_at'], name='shopsupticket_status_upd_idx'),
            models.Index(fields=['priority', '-updated_at'], name='shopsupticket_priority_upd_idx'),
            models.Index(fields=['public_id'], name='shopsupticket_public_idx'),
        ]

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        if not self.public_id:
            self.public_id = f"ticket_{self.pk}"
            super().save(update_fields=['public_id'])

    def __str__(self):
        return f"{self.public_id}: {self.subject}"


class ShopSupportTicketMessage(models.Model):
    """Messages exchanged inside a technical support ticket."""

    SENDER_TYPE_CHOICES = [
        ('shop_owner', 'صاحب المحل'),
        ('employee', 'موظف المحل'),
        ('admin_desktop', 'الدعم الفني'),
        ('system', 'النظام'),
    ]

    MESSAGE_TYPE_CHOICES = [
        ('text', 'نصي'),
        ('image', 'صورة'),
        ('audio', 'صوت'),
        ('location', 'موقع'),
        ('system', 'نظام'),
    ]

    ticket = models.ForeignKey(
        ShopSupportTicket,
        on_delete=models.CASCADE,
        related_name='messages',
        verbose_name="التذكرة",
    )
    sender_type = models.CharField(max_length=20, choices=SENDER_TYPE_CHOICES, verbose_name="نوع المرسل")
    sender_shop_owner = models.ForeignKey(
        ShopOwner,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='sent_support_ticket_messages',
        verbose_name="صاحب المحل",
    )
    sender_employee = models.ForeignKey(
        Employee,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='sent_support_ticket_messages',
        verbose_name="الموظف",
    )
    sender_admin = models.ForeignKey(
        'user.AdminDesktopUser',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='sent_support_ticket_messages',
        verbose_name="موظف الدعم",
    )
    message_type = models.CharField(max_length=20, choices=MESSAGE_TYPE_CHOICES, default='text', verbose_name="نوع الرسالة")
    content = models.TextField(blank=True, null=True, verbose_name="المحتوى")
    image_url = models.TextField(blank=True, null=True, verbose_name="رابط الصورة")
    audio_url = models.TextField(blank=True, null=True, verbose_name="رابط الصوت")
    latitude = models.DecimalField(max_digits=10, decimal_places=7, blank=True, null=True, verbose_name="خط العرض")
    longitude = models.DecimalField(max_digits=10, decimal_places=7, blank=True, null=True, verbose_name="خط الطول")
    metadata = models.JSONField(default=dict, blank=True, verbose_name="بيانات إضافية")
    is_read = models.BooleanField(default=False, verbose_name="مقروءة")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="تاريخ الإرسال")

    class Meta:
        verbose_name = "رسالة تذكرة دعم"
        verbose_name_plural = "رسائل تذاكر الدعم"
        ordering = ['created_at']
        indexes = [
            models.Index(fields=['ticket', 'created_at'], name='shopsupmsg_ticket_created_idx'),
        ]

    @property
    def sender_name(self):
        if self.sender_type == 'shop_owner' and self.sender_shop_owner:
            return self.sender_shop_owner.owner_name
        if self.sender_type == 'employee' and self.sender_employee:
            return self.sender_employee.name
        if self.sender_type == 'admin_desktop' and self.sender_admin:
            return self.sender_admin.name
        return "النظام"

    def __str__(self):
        return f"رسالة {self.sender_name} - {self.ticket.public_id}"


class Invoice(models.Model):
    """نموذج الفاتورة"""
    shop_owner = models.ForeignKey(ShopOwner, on_delete=models.CASCADE, related_name='invoices', verbose_name="صاحب المحل")
    customer = models.ForeignKey(Customer, on_delete=models.CASCADE, related_name='invoices', verbose_name="العميل")
    order = models.OneToOneField(Order, on_delete=models.CASCADE, related_name='invoice', null=True, blank=True, verbose_name="الطلب")
    invoice_number = models.CharField(max_length=50, unique=True, verbose_name="رقم الفاتورة")
    items = models.TextField(verbose_name="الأصناف")
    total_amount = models.DecimalField(max_digits=10, decimal_places=2, verbose_name="المبلغ الإجمالي")
    delivery_fee = models.DecimalField(max_digits=10, decimal_places=2, default=0, verbose_name="رسوم التوصيل")
    address = models.TextField(verbose_name="العنوان الكامل")
    phone_number = models.CharField(max_length=20, verbose_name="رقم الهاتف")
    is_sent = models.BooleanField(default=False, verbose_name="تم الإرسال")
    sent_at = models.DateTimeField(null=True, blank=True, verbose_name="تاريخ الإرسال")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="تاريخ الإنشاء")

    class Meta:
        verbose_name = "فاتورة"
        verbose_name_plural = "الفواتير"
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['shop_owner', '-created_at']),
        ]

    def __str__(self):
        return f"فاتورة #{self.invoice_number} - {self.customer.name}"


class Category(models.Model):
    """نموذج التصنيفات للمنتجات"""
    shop_owner = models.ForeignKey(ShopOwner, on_delete=models.CASCADE, related_name='categories', verbose_name="صاحب المحل")
    name = models.CharField(max_length=100, verbose_name="اسم التصنيف")
    name_en = models.CharField(max_length=100, blank=True, null=True, verbose_name="الاسم بالإنجليزية")
    icon = models.CharField(max_length=50, blank=True, null=True, verbose_name="الأيقونة")
    image = models.ImageField(upload_to='category_images/', blank=True, null=True, verbose_name="صورة التصنيف")
    display_order = models.PositiveIntegerField(default=0, verbose_name="ترتيب العرض")
    is_active = models.BooleanField(default=True, verbose_name="نشط")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="تاريخ الإنشاء")

    class Meta:
        verbose_name = "تصنيف"
        verbose_name_plural = "التصنيفات"
        ordering = ['display_order', 'name']

    def __str__(self):
        return self.name


class Product(models.Model):
    """نموذج منتج/صنف في قائمة المنتجات (بروفايل المحل)"""
    shop_owner = models.ForeignKey(ShopOwner, on_delete=models.CASCADE, related_name='products', verbose_name="صاحب المحل")
    category = models.ForeignKey(Category, on_delete=models.SET_NULL, null=True, blank=True, related_name='products', verbose_name="التصنيف")
    name = models.CharField(max_length=200, verbose_name="اسم الصنف")
    description = models.TextField(blank=True, null=True, verbose_name="وصف الصنف")
    price = models.DecimalField(max_digits=10, decimal_places=2, verbose_name="السعر")
    discount_price = models.DecimalField(max_digits=10, decimal_places=2, blank=True, null=True, verbose_name="السعر بعد الخصم")
    image = models.ImageField(upload_to='product_images/', blank=True, null=True, verbose_name="صورة الصنف")
    display_order = models.PositiveIntegerField(default=0, verbose_name="ترتيب العرض")
    is_available = models.BooleanField(default=True, verbose_name="متاح")
    is_featured = models.BooleanField(default=False, verbose_name="مميز")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="تاريخ الإنشاء")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="تاريخ التحديث")

    class Meta:
        verbose_name = "منتج"
        verbose_name_plural = "قائمة المنتجات"
        ordering = ['display_order', 'name']
        indexes = [
            models.Index(fields=['shop_owner', 'is_available']),
            models.Index(fields=['category']),
        ]

    @property
    def final_price(self):
        return self.discount_price if self.discount_price else self.price

    def __str__(self):
        return f"{self.name} - {self.shop_owner.shop_name}"


class Offer(models.Model):
    """Independent marketing offer for the shop."""

    shop_owner = models.ForeignKey(ShopOwner, on_delete=models.CASCADE, related_name='offers', verbose_name="صاحب المحل")
    title = models.CharField(max_length=200, verbose_name="عنوان العرض")
    description = models.TextField(blank=True, null=True, verbose_name="وصف العرض")
    image = models.ImageField(upload_to='offer_images/', blank=True, null=True, verbose_name="صورة العرض")
    discount_percentage = models.DecimalField(max_digits=5, decimal_places=2, verbose_name="نسبة الخصم")
    start_date = models.DateField(verbose_name="تاريخ بداية العرض")
    end_date = models.DateField(verbose_name="تاريخ انتهاء العرض")
    views_count = models.PositiveIntegerField(default=0, verbose_name="عدد المشاهدات")
    likes_count = models.PositiveIntegerField(default=0, verbose_name="عدد الإعجابات")
    is_active = models.BooleanField(default=True, verbose_name="نشط")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="تاريخ الإنشاء")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="تاريخ التحديث")

    class Meta:
        verbose_name = "عرض"
        verbose_name_plural = "العروض"
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['shop_owner', 'is_active']),
            models.Index(fields=['start_date']),
            models.Index(fields=['end_date']),
            models.Index(fields=['views_count']),
        ]

    def clean(self):
        errors = {}

        if self.start_date and self.end_date and self.end_date < self.start_date:
            errors['end_date'] = "End date cannot be earlier than start date."

        if self.discount_percentage is not None and self.discount_percentage <= 0:
            errors['discount_percentage'] = "Discount percentage must be greater than zero."

        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)

    @property
    def status(self):
        today = timezone.localdate()
        if self.start_date > today:
            return 'scheduled'
        if self.end_date < today:
            return 'expired'
        return 'active'

    def __str__(self):
        return f"{self.title} - {self.shop_owner.shop_name}"


class OfferLike(models.Model):
    """Persistent likes for public offers."""

    offer = models.ForeignKey(Offer, on_delete=models.CASCADE, related_name='likes', verbose_name="العرض")
    user_identifier = models.CharField(max_length=100, verbose_name="معرف المستخدم")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="تاريخ الإعجاب")

    class Meta:
        verbose_name = "إعجاب على عرض"
        verbose_name_plural = "إعجابات العروض"
        constraints = [
            models.UniqueConstraint(fields=['offer', 'user_identifier'], name='unique_offer_like_per_user')
        ]
        indexes = [
            models.Index(fields=['offer', 'user_identifier']),
        ]

    def __str__(self):
        return f"{self.offer_id} - {self.user_identifier}"


class OrderRating(models.Model):
    """نموذج تقييم الطلب"""
    order = models.OneToOneField(Order, on_delete=models.CASCADE, related_name='rating', verbose_name="الطلب")
    customer = models.ForeignKey(Customer, on_delete=models.CASCADE, related_name='ratings', verbose_name="العميل")
    shop_rating = models.PositiveSmallIntegerField(verbose_name="تقييم المحل", help_text="من 1 إلى 5")
    driver_rating = models.PositiveSmallIntegerField(blank=True, null=True, verbose_name="تقييم السائق", help_text="من 1 إلى 5")
    food_rating = models.PositiveSmallIntegerField(blank=True, null=True, verbose_name="تقييم الطعام", help_text="من 1 إلى 5")
    comment = models.TextField(blank=True, null=True, verbose_name="تعليق")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="تاريخ التقييم")

    class Meta:
        verbose_name = "تقييم طلب"
        verbose_name_plural = "تقييمات الطلبات"
        ordering = ['-created_at']

    def __str__(self):
        return f"تقييم طلب #{self.order.order_number} - {self.shop_rating}/5"


class ShopReview(models.Model):
    """General shop review that does not require an order."""
    shop_owner = models.ForeignKey(ShopOwner, on_delete=models.CASCADE, related_name='shop_reviews', verbose_name="المحل")
    customer = models.ForeignKey(Customer, on_delete=models.CASCADE, related_name='shop_reviews', verbose_name="العميل")
    shop_rating = models.PositiveSmallIntegerField(verbose_name="تقييم المحل", help_text="من 1 إلى 5")
    comment = models.TextField(blank=True, null=True, verbose_name="تعليق")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="تاريخ التقييم")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="تاريخ التحديث")

    class Meta:
        verbose_name = "تقييم محل"
        verbose_name_plural = "تقييمات المحلات"
        ordering = ['-updated_at', '-created_at']
        unique_together = ['shop_owner', 'customer']
        indexes = [
            models.Index(fields=['shop_owner', 'customer']),
        ]

    def __str__(self):
        return f"تقييم {self.shop_owner.shop_name} - {self.shop_rating}/5"


class PaymentMethod(models.Model):
    """نموذج طرق الدفع المحفوظة للعميل"""
    TYPE_CHOICES = [
        ('visa', 'Visa'),
        ('mastercard', 'MasterCard'),
        ('mada', 'مدى'),
        ('apple_pay', 'Apple Pay'),
        ('stc_pay', 'STC Pay'),
    ]
    
    customer = models.ForeignKey(Customer, on_delete=models.CASCADE, related_name='payment_methods', verbose_name="العميل")
    card_type = models.CharField(max_length=20, choices=TYPE_CHOICES, verbose_name="نوع البطاقة")
    last_four_digits = models.CharField(max_length=4, verbose_name="آخر 4 أرقام")
    card_holder_name = models.CharField(max_length=100, verbose_name="اسم حامل البطاقة")
    expiry_month = models.CharField(max_length=2, verbose_name="شهر الانتهاء")
    expiry_year = models.CharField(max_length=4, verbose_name="سنة الانتهاء")
    is_default = models.BooleanField(default=False, verbose_name="البطاقة الافتراضية")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="تاريخ الإضافة")

    class Meta:
        verbose_name = "طريقة دفع"
        verbose_name_plural = "طرق الدفع"
        ordering = ['-is_default', '-created_at']

    def save(self, *args, **kwargs):
        if self.is_default:
            PaymentMethod.objects.filter(customer=self.customer, is_default=True).update(is_default=False)
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.card_type} **** {self.last_four_digits}"


class Notification(models.Model):
    """Notification record stored server-side for app inbox screens."""

    TYPE_CHOICES = [
        ('order_status', 'Order Status'),
        ('order_assigned', 'Order Assigned'),
        ('order_cancelled', 'Order Cancelled'),
        ('new_delivery_order', 'New Delivery Order'),
        ('store_invite', 'Store Invite'),
        ('general_notification', 'General Notification'),
        ('order_update', 'Order Update'),
        ('promotion', 'Promotion'),
        ('system', 'System'),
        ('chat_message', 'Chat Message'),
        ('chat', 'Chat Legacy'),
    ]

    customer = models.ForeignKey(Customer, on_delete=models.CASCADE, null=True, blank=True, related_name='notifications', verbose_name="Customer")
    shop_owner = models.ForeignKey(ShopOwner, on_delete=models.CASCADE, null=True, blank=True, related_name='notifications', verbose_name="Shop Owner")
    employee = models.ForeignKey(Employee, on_delete=models.CASCADE, null=True, blank=True, related_name='notifications', verbose_name="Employee")
    driver = models.ForeignKey(Driver, on_delete=models.CASCADE, null=True, blank=True, related_name='notifications', verbose_name="Driver")

    notification_type = models.CharField(max_length=20, choices=TYPE_CHOICES, default='system', verbose_name="Notification Type")
    title = models.CharField(max_length=200, verbose_name="Title")
    message = models.TextField(verbose_name="Message")
    order_id = models.PositiveBigIntegerField(null=True, blank=True, verbose_name="Order ID")
    store_id = models.PositiveBigIntegerField(null=True, blank=True, verbose_name="Store ID")
    image_url = models.TextField(blank=True, null=True, verbose_name="Image URL")
    reference_id = models.CharField(max_length=100, blank=True, null=True, verbose_name="Reference ID")
    idempotency_key = models.CharField(max_length=150, blank=True, null=True, verbose_name="Idempotency Key")
    data = models.JSONField(blank=True, null=True, verbose_name="Extra Data")
    is_read = models.BooleanField(default=False, verbose_name="Read")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Created At")

    class Meta:
        verbose_name = "Notification"
        verbose_name_plural = "Notifications"
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['customer', '-created_at']),
            models.Index(fields=['shop_owner', '-created_at']),
            models.Index(fields=['employee', '-created_at']),
            models.Index(fields=['driver', '-created_at']),
            models.Index(fields=['notification_type', '-created_at']),
            models.Index(fields=['reference_id', 'notification_type']),
            models.Index(fields=['idempotency_key']),
            models.Index(fields=['driver', 'order_id']),
            models.Index(fields=['driver', 'store_id']),
        ]

    def __str__(self):
        return f"{self.title} - {self.notification_type}"


class AccountModerationStatus(models.Model):
    """Tracks warnings and suspension state for reportable accounts."""

    customer = models.OneToOneField(
        Customer,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='moderation_status',
        verbose_name="العميل",
    )
    shop_owner = models.OneToOneField(
        ShopOwner,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='moderation_status',
        verbose_name="المحل",
    )
    driver = models.OneToOneField(
        Driver,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='moderation_status',
        verbose_name="الدليفري",
    )
    warnings_count = models.PositiveIntegerField(default=0, verbose_name="عدد التحذيرات")
    is_suspended = models.BooleanField(default=False, verbose_name="معلق")
    suspended_at = models.DateTimeField(null=True, blank=True, verbose_name="تاريخ التعليق")
    suspension_reason = models.TextField(blank=True, null=True, verbose_name="سبب التعليق")
    last_warning_at = models.DateTimeField(null=True, blank=True, verbose_name="تاريخ آخر تحذير")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="تاريخ الإنشاء")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="تاريخ التحديث")

    class Meta:
        verbose_name = "حالة الإشراف على الحساب"
        verbose_name_plural = "حالات الإشراف على الحسابات"
        indexes = [
            models.Index(fields=['is_suspended', '-updated_at'], name='acctmod_suspended_idx'),
        ]

    @property
    def target_type(self):
        if self.customer_id:
            return 'customer'
        if self.shop_owner_id:
            return 'shop_owner'
        if self.driver_id:
            return 'driver'
        return None

    @property
    def target(self):
        return self.customer or self.shop_owner or self.driver

    def clean(self):
        linked_targets = [self.customer_id, self.shop_owner_id, self.driver_id]
        if sum(1 for value in linked_targets if value) != 1:
            raise ValidationError("Exactly one moderation target must be linked.")

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.target_type or 'unknown'} moderation #{self.pk}"


class AbuseReport(models.Model):
    """Cross-party abuse report for customer, shop, and driver disputes."""

    REPORTER_TYPE_CHOICES = [
        ('customer', 'عميل'),
        ('shop_owner', 'محل'),
        ('employee', 'محل'),
        ('driver', 'دليفري'),
    ]
    TARGET_TYPE_CHOICES = [
        ('customer', 'عميل'),
        ('shop_owner', 'محل'),
        ('driver', 'دليفري'),
    ]
    STATUS_CHOICES = [
        ('pending_review', 'قيد المراجعة'),
        ('high_risk', 'خطير'),
        ('closed', 'مغلق'),
    ]
    ACTION_CHOICES = [
        ('warning', 'تحذير'),
        ('suspend', 'تعليق الحساب'),
        ('close_no_action', 'إغلاق بدون إجراء'),
    ]

    public_id = models.CharField(max_length=32, unique=True, blank=True, verbose_name="رقم البلاغ")
    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name='abuse_reports', verbose_name="الطلب")

    reporter_type = models.CharField(max_length=20, choices=REPORTER_TYPE_CHOICES, verbose_name="نوع المبلّغ")
    reporter_customer = models.ForeignKey(Customer, on_delete=models.SET_NULL, null=True, blank=True, related_name='submitted_abuse_reports', verbose_name="العميل المبلّغ")
    reporter_shop_owner = models.ForeignKey(ShopOwner, on_delete=models.SET_NULL, null=True, blank=True, related_name='submitted_abuse_reports', verbose_name="المحل المبلّغ")
    reporter_employee = models.ForeignKey(Employee, on_delete=models.SET_NULL, null=True, blank=True, related_name='submitted_abuse_reports', verbose_name="الموظف المبلّغ")
    reporter_driver = models.ForeignKey(Driver, on_delete=models.SET_NULL, null=True, blank=True, related_name='submitted_abuse_reports', verbose_name="الدليفري المبلّغ")

    target_type = models.CharField(max_length=20, choices=TARGET_TYPE_CHOICES, verbose_name="نوع المبلّغ عليه")
    target_customer = models.ForeignKey(Customer, on_delete=models.SET_NULL, null=True, blank=True, related_name='received_abuse_reports', verbose_name="العميل المبلّغ عليه")
    target_shop_owner = models.ForeignKey(ShopOwner, on_delete=models.SET_NULL, null=True, blank=True, related_name='received_abuse_reports', verbose_name="المحل المبلّغ عليه")
    target_driver = models.ForeignKey(Driver, on_delete=models.SET_NULL, null=True, blank=True, related_name='received_abuse_reports', verbose_name="الدليفري المبلّغ عليه")

    reason = models.CharField(max_length=120, verbose_name="سبب البلاغ")
    details = models.TextField(blank=True, null=True, verbose_name="تفاصيل البلاغ")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending_review', verbose_name="الحالة")
    resolution_action = models.CharField(max_length=20, choices=ACTION_CHOICES, null=True, blank=True, verbose_name="الإجراء النهائي")
    admin_notes = models.TextField(blank=True, null=True, verbose_name="ملاحظات الإدارة")
    reviewed_by_admin_id = models.IntegerField(null=True, blank=True, verbose_name="معرّف المراجع")
    reviewed_by_admin_name = models.CharField(max_length=120, blank=True, null=True, verbose_name="اسم المراجع")
    reviewed_at = models.DateTimeField(null=True, blank=True, verbose_name="تاريخ المراجعة")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="تاريخ الإنشاء")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="تاريخ التحديث")

    class Meta:
        verbose_name = "بلاغ إساءة"
        verbose_name_plural = "بلاغات الإساءة"
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['status', '-created_at'], name='abusereport_status_idx'),
            models.Index(fields=['reporter_type', '-created_at'], name='abusereport_reporter_idx'),
            models.Index(fields=['target_type', '-created_at'], name='abusereport_target_idx'),
        ]

    @property
    def reporter(self):
        return self.reporter_customer or self.reporter_shop_owner or self.reporter_employee or self.reporter_driver

    @property
    def target(self):
        return self.target_customer or self.target_shop_owner or self.target_driver

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        if not self.public_id:
            self.public_id = f"REP-{9000 + self.pk}"
            super().save(update_fields=['public_id'])

    def __str__(self):
        return self.public_id or f"Report #{self.pk}"


class Cart(models.Model):
    """نموذج سلة التسوق"""
    customer = models.ForeignKey(Customer, on_delete=models.CASCADE, related_name='carts', verbose_name="العميل")
    shop_owner = models.ForeignKey(ShopOwner, on_delete=models.CASCADE, related_name='carts', verbose_name="المحل")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="تاريخ الإنشاء")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="تاريخ التحديث")

    class Meta:
        verbose_name = "سلة تسوق"
        verbose_name_plural = "سلات التسوق"
        unique_together = ['customer', 'shop_owner']  # سلة واحدة لكل عميل لكل محل

    @property
    def total_items(self):
        return sum(item.quantity for item in self.items.all())

    @property
    def subtotal(self):
        return sum(item.total_price for item in self.items.all())

    def __str__(self):
        return f"سلة {self.customer.name} - {self.shop_owner.shop_name}"


class CartItem(models.Model):
    """نموذج عناصر سلة التسوق"""
    cart = models.ForeignKey(Cart, on_delete=models.CASCADE, related_name='items', verbose_name="السلة")
    product = models.ForeignKey(Product, on_delete=models.CASCADE, verbose_name="المنتج")
    quantity = models.PositiveIntegerField(default=1, verbose_name="الكمية")
    notes = models.TextField(blank=True, null=True, verbose_name="ملاحظات")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="تاريخ الإضافة")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="تاريخ التحديث")

    class Meta:
        verbose_name = "عنصر السلة"
        verbose_name_plural = "عناصر السلة"
        unique_together = ['cart', 'product']

    @property
    def unit_price(self):
        return self.product.final_price

    @property
    def total_price(self):
        return self.unit_price * self.quantity

    def __str__(self):
        return f"{self.product.name} x {self.quantity}"
