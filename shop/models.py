from django.db import models
from user.models import ShopOwner


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
    shop_owner = models.ForeignKey(ShopOwner, on_delete=models.CASCADE, related_name='customers', verbose_name="صاحب المحل")
    name = models.CharField(max_length=100, verbose_name="اسم العميل")
    phone_number = models.CharField(max_length=20, verbose_name="رقم الهاتف")
    address = models.TextField(blank=True, null=True, verbose_name="العنوان")
    profile_image = models.ImageField(upload_to='customer_profiles/', blank=True, null=True, verbose_name="صورة العميل")
    is_online = models.BooleanField(default=False, verbose_name="متصل الآن")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="تاريخ الإنشاء")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="تاريخ التحديث")

    class Meta:
        verbose_name = "عميل"
        verbose_name_plural = "العملاء"
        unique_together = ['shop_owner', 'phone_number']  # نفس الرقم لا يمكن أن يكون لعميلين مختلفين لنفس المحل
        ordering = ['-updated_at']
        indexes = [
            models.Index(fields=['shop_owner', '-updated_at']),
        ]

    def __str__(self):
        return f"{self.name} - {self.phone_number}"


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
        """عدد الطلبات التي تعامل معها الموظف (يمكن حسابها من Orders)"""
        # يمكن إضافة relation لاحقاً أو حسابها من Order.employee
        return 0
    
    @property
    def total_amount(self):
        """إجمالي المبلغ في العهدة (يمكن حسابها من Orders)"""
        # يمكن إضافة relation لاحقاً أو حسابها من Order.employee
        return 0

    def __str__(self):
        return f"{self.name} - {self.get_role_display()} ({self.phone_number})"


class Driver(models.Model):
    """نموذج السائق"""
    STATUS_CHOICES = [
        ('available', 'متاح'),
        ('busy', 'مشغول'),
        ('offline', 'غير متصل'),
    ]
    
    shop_owner = models.ForeignKey(ShopOwner, on_delete=models.CASCADE, related_name='drivers', verbose_name="صاحب المحل")
    name = models.CharField(max_length=100, verbose_name="اسم السائق")
    phone_number = models.CharField(max_length=20, verbose_name="رقم الهاتف")
    password = models.CharField(max_length=128, verbose_name="كلمة المرور", blank=True, null=True)  # إضافة password للسائق
    profile_image = models.ImageField(upload_to='driver_profiles/', blank=True, null=True, verbose_name="صورة السائق")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='offline', verbose_name="الحالة")
    current_orders_count = models.IntegerField(default=0, verbose_name="عدد الطلبات الحالية")
    rating = models.DecimalField(max_digits=3, decimal_places=2, default=0.0, verbose_name="التقييم")  # إضافة rating
    total_rides = models.IntegerField(default=0, verbose_name="إجمالي الرحلات")  # إضافة total_rides
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="تاريخ الإنشاء")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="تاريخ التحديث")

    class Meta:
        verbose_name = "سائق"
        verbose_name_plural = "السائقين"
        unique_together = ['shop_owner', 'phone_number']  # إضافة unique constraint
        ordering = ['-updated_at']
        indexes = [
            models.Index(fields=['shop_owner', 'status']),
        ]

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


class Order(models.Model):
    """نموذج الطلب"""
    STATUS_CHOICES = [
        ('new', 'جديد'),
        ('preparing', 'قيد التحضير'),
        ('on_way', 'في الطريق'),
        ('delivered', 'تم التسليم'),
        ('cancelled', 'ملغي'),
    ]
    
    shop_owner = models.ForeignKey(ShopOwner, on_delete=models.CASCADE, related_name='orders', verbose_name="صاحب المحل")
    customer = models.ForeignKey(Customer, on_delete=models.CASCADE, related_name='orders', verbose_name="العميل")
    driver = models.ForeignKey(Driver, on_delete=models.SET_NULL, null=True, blank=True, related_name='orders', verbose_name="السائق")
    order_number = models.CharField(max_length=50, unique=True, verbose_name="رقم الطلب")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='new', verbose_name="حالة الطلب")
    items = models.TextField(verbose_name="الأصناف")  # JSON string أو text
    total_amount = models.DecimalField(max_digits=10, decimal_places=2, verbose_name="المبلغ الإجمالي")
    delivery_fee = models.DecimalField(max_digits=10, decimal_places=2, default=0, verbose_name="رسوم التوصيل")
    address = models.TextField(verbose_name="العنوان الكامل")
    notes = models.TextField(blank=True, null=True, verbose_name="ملاحظات")
    unread_messages_count = models.IntegerField(default=0, verbose_name="عدد الرسائل غير المقروءة")
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


class ChatMessage(models.Model):
    """نموذج رسائل المحادثة"""
    MESSAGE_TYPE_CHOICES = [
        ('text', 'نص'),
        ('audio', 'صوت'),
        ('image', 'صورة'),
    ]
    
    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name='messages', verbose_name="الطلب")
    sender_type = models.CharField(max_length=20, choices=[('customer', 'عميل'), ('shop', 'المحل')], verbose_name="نوع المرسل")
    message_type = models.CharField(max_length=20, choices=MESSAGE_TYPE_CHOICES, default='text', verbose_name="نوع الرسالة")
    content = models.TextField(verbose_name="محتوى الرسالة")
    audio_file = models.FileField(upload_to='chat_audio/', blank=True, null=True, verbose_name="ملف صوتي")
    image_file = models.ImageField(upload_to='chat_images/', blank=True, null=True, verbose_name="صورة")
    is_read = models.BooleanField(default=False, verbose_name="مقروءة")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="تاريخ الإرسال")

    class Meta:
        verbose_name = "رسالة محادثة"
        verbose_name_plural = "رسائل المحادثات"
        ordering = ['created_at']
        indexes = [
            models.Index(fields=['order', 'created_at']),
        ]

    def __str__(self):
        return f"رسالة من {self.sender_type} - {self.order.order_number}"


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
