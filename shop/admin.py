from django.contrib import admin
from .models import ShopStatus, Customer, Driver, Order, ChatMessage, Invoice


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
    list_display = ('name', 'phone_number', 'shop_owner', 'is_online', 'created_at')
    list_filter = ('is_online', 'created_at')
    search_fields = ('name', 'phone_number', 'shop_owner__shop_name')
    readonly_fields = ('created_at', 'updated_at')


@admin.register(Driver)
class DriverAdmin(admin.ModelAdmin):
    """إدارة السائقين"""
    list_display = ('name', 'phone_number', 'shop_owner', 'status', 'current_orders_count', 'updated_at')
    list_filter = ('status', 'created_at')
    search_fields = ('name', 'phone_number', 'shop_owner__shop_name')
    readonly_fields = ('created_at', 'updated_at')


@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    """إدارة الطلبات"""
    list_display = ('order_number', 'customer', 'driver', 'status', 'total_amount', 'created_at')
    list_filter = ('status', 'created_at')
    search_fields = ('order_number', 'customer__name', 'customer__phone_number')
    readonly_fields = ('order_number', 'created_at', 'updated_at')
    fieldsets = (
        ('معلومات أساسية', {
            'fields': ('shop_owner', 'order_number', 'customer', 'driver', 'status')
        }),
        ('تفاصيل الطلب', {
            'fields': ('items', 'total_amount', 'delivery_fee', 'address', 'notes')
        }),
        ('معلومات إضافية', {
            'fields': ('unread_messages_count', 'created_at', 'updated_at')
        }),
    )


@admin.register(ChatMessage)
class ChatMessageAdmin(admin.ModelAdmin):
    """إدارة رسائل المحادثة"""
    list_display = ('order', 'sender_type', 'message_type', 'is_read', 'created_at')
    list_filter = ('sender_type', 'message_type', 'is_read', 'created_at')
    search_fields = ('order__order_number', 'content')
    readonly_fields = ('created_at',)


@admin.register(Invoice)
class InvoiceAdmin(admin.ModelAdmin):
    """إدارة الفواتير"""
    list_display = ('invoice_number', 'customer', 'total_amount', 'is_sent', 'created_at')
    list_filter = ('is_sent', 'created_at')
    search_fields = ('invoice_number', 'customer__name', 'phone_number')
    readonly_fields = ('invoice_number', 'sent_at', 'created_at')
