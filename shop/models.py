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
    shop_owner = models.ForeignKey(ShopOwner, on_delete=models.CASCADE, related_name='customers', verbose_name="صاحب المحل", null=True, blank=True)
    name = models.CharField(max_length=100, verbose_name="اسم العميل")
    phone_number = models.CharField(max_length=20, unique=True, verbose_name="رقم الهاتف")
    password = models.CharField(max_length=128, blank=True, null=True, verbose_name="كلمة المرور")
    profile_image = models.ImageField(upload_to='customer_profiles/', blank=True, null=True, verbose_name="صورة العميل")
    is_online = models.BooleanField(default=False, verbose_name="متصل الآن")
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
        return f"{self.name} - {self.phone_number}"


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
        ('offline', 'غير متصل'),
    ]
    
    # تم تغيير العلاقة لدعم تعدد المتاجر، السائق يمكنه العمل في أكثر من محل
    shops = models.ManyToManyField(ShopOwner, through='ShopDriver', related_name='drivers', verbose_name="المتاجر")
    
    name = models.CharField(max_length=100, verbose_name="اسم السائق")
    phone_number = models.CharField(max_length=20, unique=True, verbose_name="رقم الهاتف")
    password = models.CharField(max_length=128, verbose_name="كلمة المرور", blank=True, null=True)  # إضافة password للسائق
    profile_image = models.ImageField(upload_to='driver_profiles/', blank=True, null=True, verbose_name="صورة السائق")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='offline', verbose_name="الحالة التشغيلية")
    current_orders_count = models.IntegerField(default=0, verbose_name="عدد الطلبات الحالية")
    rating = models.DecimalField(max_digits=3, decimal_places=2, default=0.0, verbose_name="التقييم")
    total_rides = models.IntegerField(default=0, verbose_name="إجمالي الرحلات")
    # حقول تتبع الموقع
    current_latitude = models.DecimalField(max_digits=10, decimal_places=7, blank=True, null=True, verbose_name="خط العرض الحالي")
    current_longitude = models.DecimalField(max_digits=10, decimal_places=7, blank=True, null=True, verbose_name="خط الطول الحالي")
    location_updated_at = models.DateTimeField(blank=True, null=True, verbose_name="آخر تحديث للموقع")
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
    """نموذج الإشعارات"""
    TYPE_CHOICES = [
        ('order_status', 'حالة الطلب'),
        ('promotion', 'عرض'),
        ('system', 'النظام'),
        ('chat', 'محادثة'),
    ]
    
    # يمكن أن يكون للعميل أو صاحب المحل أو الموظف أو السائق
    customer = models.ForeignKey(Customer, on_delete=models.CASCADE, null=True, blank=True, related_name='notifications', verbose_name="العميل")
    shop_owner = models.ForeignKey(ShopOwner, on_delete=models.CASCADE, null=True, blank=True, related_name='notifications', verbose_name="صاحب المحل")
    employee = models.ForeignKey(Employee, on_delete=models.CASCADE, null=True, blank=True, related_name='notifications', verbose_name="الموظف")
    driver = models.ForeignKey(Driver, on_delete=models.CASCADE, null=True, blank=True, related_name='notifications', verbose_name="السائق")
    
    notification_type = models.CharField(max_length=20, choices=TYPE_CHOICES, default='system', verbose_name="نوع الإشعار")
    title = models.CharField(max_length=200, verbose_name="العنوان")
    message = models.TextField(verbose_name="الرسالة")
    data = models.JSONField(blank=True, null=True, verbose_name="بيانات إضافية")
    is_read = models.BooleanField(default=False, verbose_name="مقروء")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="تاريخ الإنشاء")

    class Meta:
        verbose_name = "إشعار"
        verbose_name_plural = "الإشعارات"
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['customer', '-created_at']),
            models.Index(fields=['shop_owner', '-created_at']),
        ]

    def __str__(self):
        return f"{self.title} - {self.notification_type}"


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
