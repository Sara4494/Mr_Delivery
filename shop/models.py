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
    profile_image = models.ImageField(upload_to='driver_profiles/', blank=True, null=True, verbose_name="صورة السائق")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='offline', verbose_name="الحالة")
    current_orders_count = models.IntegerField(default=0, verbose_name="عدد الطلبات الحالية")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="تاريخ الإنشاء")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="تاريخ التحديث")

    class Meta:
        verbose_name = "سائق"
        verbose_name_plural = "السائقين"
        ordering = ['-updated_at']
        indexes = [
            models.Index(fields=['shop_owner', 'status']),
        ]

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
