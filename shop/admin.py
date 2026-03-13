from django.contrib import admin
from .models import (
    ShopStatus, Customer, CustomerAddress, Driver, Order, ChatMessage,
    Invoice, Employee, Product, Category, Offer, OfferLike, OrderRating, PaymentMethod,
    Notification, Cart, CartItem, ShopDriver
)


@admin.register(ShopStatus)
class ShopStatusAdmin(admin.ModelAdmin):
    """إدارة حالة المتجر"""
    list_display = ('shop_owner', 'status', 'updated_at')
    list_filter = ('status', 'updated_at')
    search_fields = ('shop_owner__shop_name',)
    readonly_fields = ('updated_at',)


@admin.register(Customer)
class CustomerAdmin(admin.ModelAdmin):
    """إدارة العملاء"""
    list_display = ('name', 'phone_number', 'is_online', 'is_verified', 'created_at')
    list_filter = ('is_online', 'is_verified', 'created_at')
    search_fields = ('name', 'phone_number', )
    readonly_fields = ('created_at', 'updated_at')


@admin.register(CustomerAddress)
class CustomerAddressAdmin(admin.ModelAdmin):
    """إدارة عناوين العملاء"""
    list_display = ('customer', 'title', 'address_type', 'is_default', 'created_at')
    list_filter = ('address_type', 'is_default')
    search_fields = ('customer__name', 'title', 'full_address')
    readonly_fields = ('created_at',)


class ShopDriverInline(admin.TabularInline):
    model = ShopDriver
    extra = 1


@admin.register(Driver)
class DriverAdmin(admin.ModelAdmin):
    """إدارة السائقين"""
    list_display = ('name', 'phone_number', 'shop_owner', 'status', 'rating', 'total_rides', 'current_orders_count')
    list_filter = ('status', 'created_at')
    search_fields = ('name', 'phone_number', 'shops__shop_name')
    readonly_fields = ('created_at', 'updated_at', 'location_updated_at')
    inlines = [ShopDriverInline]
    fieldsets = (
        ('معلومات أساسية', {
            'fields': ('name', 'phone_number', 'profile_image', 'status')
        }),
        ('الإحصائيات', {
            'fields': ('rating', 'total_rides', 'current_orders_count')
        }),
        ('الموقع', {
            'fields': ('current_latitude', 'current_longitude', 'location_updated_at')
        }),
        ('الأمان', {
            'fields': ('password',)
        }),
        ('تواريخ', {
            'fields': ('created_at', 'updated_at')
        }),
    )


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    """إدارة التصنيفات"""
    list_display = ('name', 'shop_owner', 'display_order', 'is_active', 'created_at')
    list_filter = ('is_active', 'shop_owner')
    search_fields = ('name', 'name_en', 'shop_owner__shop_name')
    readonly_fields = ('created_at',)


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    """إدارة قائمة المنتجات"""
    list_display = ('name', 'shop_owner', 'category', 'price', 'discount_price', 'is_available', 'is_featured')
    list_filter = ('is_available', 'is_featured', 'category', 'shop_owner')
    search_fields = ('name', 'shop_owner__shop_name')
    readonly_fields = ('created_at', 'updated_at')


@admin.register(Offer)
class OfferAdmin(admin.ModelAdmin):
    """Offer management."""

    list_display = (
        'title', 'shop_owner', 'status_display', 'discount_percentage',
        'views_count', 'likes_count', 'start_date', 'end_date', 'is_active'
    )
    list_filter = ('is_active', 'start_date', 'end_date', 'shop_owner')
    search_fields = ('title', 'description', 'shop_owner__shop_name')
    readonly_fields = ('views_count', 'likes_count', 'created_at', 'updated_at')

    def status_display(self, obj):
        return obj.status

    status_display.short_description = 'Status'


@admin.register(OfferLike)
class OfferLikeAdmin(admin.ModelAdmin):
    list_display = ('offer', 'user_identifier', 'created_at')
    search_fields = ('offer__title', 'offer__shop_owner__shop_name', 'user_identifier')
    readonly_fields = ('created_at',)


@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    """إدارة الطلبات"""
    list_display = ('order_number', 'customer', 'driver', 'status', 'payment_method', 'is_paid', 'total_amount', 'created_at')
    list_filter = ('status', 'payment_method', 'is_paid', 'created_at')
    search_fields = ('order_number', 'customer__name', 'customer__phone_number')
    readonly_fields = ('order_number', 'created_at', 'updated_at')
    fieldsets = (
        ('معلومات أساسية', {
            'fields': ('shop_owner', 'order_number', 'customer', 'employee', 'driver', 'status')
        }),
        ('تفاصيل الطلب', {
            'fields': ('items', 'total_amount', 'delivery_fee', 'address', 'delivery_address', 'notes')
        }),
        ('الدفع', {
            'fields': ('payment_method', 'is_paid')
        }),
        ('التوصيل', {
            'fields': ('estimated_delivery_time', 'delivered_at')
        }),
        ('معلومات إضافية', {
            'fields': ('unread_messages_count', 'created_at', 'updated_at')
        }),
    )


@admin.register(OrderRating)
class OrderRatingAdmin(admin.ModelAdmin):
    """إدارة تقييمات الطلبات"""
    list_display = ('order', 'customer', 'shop_rating', 'driver_rating', 'food_rating', 'created_at')
    list_filter = ('shop_rating', 'driver_rating', 'created_at')
    search_fields = ('order__order_number', 'customer__name')
    readonly_fields = ('created_at',)


@admin.register(ChatMessage)
class ChatMessageAdmin(admin.ModelAdmin):
    """إدارة رسائل المحادثة"""
    list_display = ('order', 'chat_type', 'sender_type', 'sender_name', 'message_type', 'is_read', 'created_at')
    list_filter = ('chat_type', 'sender_type', 'message_type', 'is_read', 'created_at')
    search_fields = ('order__order_number', 'content')
    readonly_fields = ('created_at', 'sender_name')
    fieldsets = (
        ('معلومات أساسية', {
            'fields': ('order', 'chat_type', 'sender_type')
        }),
        ('المرسل', {
            'fields': ('sender_customer', 'sender_shop_owner', 'sender_employee', 'sender_driver')
        }),
        ('الرسالة', {
            'fields': ('message_type', 'content', 'audio_file', 'image_file')
        }),
        ('الموقع (اختياري)', {
            'fields': ('latitude', 'longitude')
        }),
        ('الحالة', {
            'fields': ('is_read', 'created_at')
        }),
    )


@admin.register(Invoice)
class InvoiceAdmin(admin.ModelAdmin):
    """إدارة الفواتير"""
    list_display = ('invoice_number', 'customer', 'total_amount', 'is_sent', 'created_at')
    list_filter = ('is_sent', 'created_at')
    search_fields = ('invoice_number', 'customer__name', 'phone_number')
    readonly_fields = ('invoice_number', 'sent_at', 'created_at')


@admin.register(Employee)
class EmployeeAdmin(admin.ModelAdmin):
    """إدارة الموظفين"""
    list_display = ('name', 'phone_number', 'shop_owner', 'role', 'custody_amount', 'is_active', 'created_at')
    list_filter = ('role', 'is_active', 'created_at')
    search_fields = ('name', 'phone_number', 'shop_owner__shop_name')
    readonly_fields = ('created_at', 'updated_at')
    fieldsets = (
        ('معلومات أساسية', {
            'fields': ('shop_owner', 'name', 'phone_number', 'role', 'profile_image')
        }),
        ('العهدة والأمان', {
            'fields': ('custody_amount', 'password', 'is_active')
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


@admin.register(PaymentMethod)
class PaymentMethodAdmin(admin.ModelAdmin):
    """إدارة طرق الدفع"""
    list_display = ('customer', 'card_type', 'last_four_digits', 'is_default', 'created_at')
    list_filter = ('card_type', 'is_default')
    search_fields = ('customer__name', 'card_holder_name')
    readonly_fields = ('created_at',)


@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    """إدارة الإشعارات"""
    list_display = ('title', 'notification_type', 'customer', 'shop_owner', 'is_read', 'created_at')
    list_filter = ('notification_type', 'is_read', 'created_at')
    search_fields = ('title', 'message')
    readonly_fields = ('created_at',)


@admin.register(Cart)
class CartAdmin(admin.ModelAdmin):
    """إدارة سلات التسوق"""
    list_display = ('customer', 'shop_owner', 'total_items', 'subtotal', 'updated_at')
    search_fields = ('customer__name', 'shop_owner__shop_name')
    readonly_fields = ('created_at', 'updated_at')


@admin.register(CartItem)
class CartItemAdmin(admin.ModelAdmin):
    """إدارة عناصر السلة"""
    list_display = ('cart', 'product', 'quantity', 'total_price', 'created_at')
    search_fields = ('cart__customer__name', 'product__name')
    readonly_fields = ('created_at', 'updated_at')
