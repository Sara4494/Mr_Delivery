from django.db import models
from user.models import ShopOwner


class WorkSchedule(models.Model):
    """نموذج مواعيد عمل المحل"""
    shop_owner = models.OneToOneField(ShopOwner, on_delete=models.CASCADE, related_name='work_schedule', verbose_name="صاحب المحل")
    work_days = models.CharField(max_length=100, default="الأحد - الخميس", verbose_name="أيام العمل")
    work_hours = models.CharField(max_length=50, default="9:00 صباحاً - 5:00 مساءً", verbose_name="ساعات العمل")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="تاريخ الإنشاء")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="تاريخ التحديث")

    class Meta:
        verbose_name = "مواعيد العمل"
        verbose_name_plural = "مواعيد العمل"
    
    def __str__(self):
        return f"مواعيد عمل {self.shop_owner.shop_name}"


class GalleryImage(models.Model):
    """نموذج صور معرض المحل"""
    STATUS_CHOICES = [
        ('draft', 'مسودة'),
        ('published', 'منشور'),
    ]
    
    shop_owner = models.ForeignKey(ShopOwner, on_delete=models.CASCADE, related_name='gallery_images', verbose_name="صاحب المحل")
    image = models.ImageField(upload_to='gallery_images/', verbose_name="الصورة")
    description = models.TextField(blank=True, null=True, verbose_name="وصف الصورة")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='draft', verbose_name="الحالة")
    uploaded_at = models.DateTimeField(auto_now_add=True, verbose_name="تاريخ الرفع")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="تاريخ التحديث")
    likes_count = models.IntegerField(default=0, verbose_name="عدد الإعجابات")

    class Meta:
        verbose_name = "صورة المعرض"
        verbose_name_plural = "صور المعرض"
        ordering = ['-uploaded_at']
        indexes = [
            models.Index(fields=['shop_owner', 'status']),
            models.Index(fields=['-uploaded_at']),
        ]

    def __str__(self):
        return f"صورة {self.shop_owner.shop_name} - {self.get_status_display()}"


class ImageLike(models.Model):
    """نموذج إعجابات الصور"""
    image = models.ForeignKey(GalleryImage, on_delete=models.CASCADE, related_name='likes', verbose_name="الصورة")
    user_identifier = models.CharField(max_length=100, verbose_name="معرف المستخدم")  # يمكن أن يكون رقم هاتف أو أي معرف
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="تاريخ الإعجاب")

    class Meta:
        verbose_name = "إعجاب"
        verbose_name_plural = "الإعجابات"
        unique_together = ['image', 'user_identifier']  # منع الإعجاب المكرر
        ordering = ['-created_at']

    def __str__(self):
        return f"إعجاب على صورة {self.image.id} من {self.user_identifier}"
