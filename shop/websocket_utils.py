"""
WebSocket Utility Functions
للإرسال من REST APIs إلى WebSocket Channels
"""

from channels.layers import get_channel_layer
from asgiref.sync import async_to_sync


def send_to_group(group_name, message_type, data):
    """
    إرسال رسالة إلى مجموعة WebSocket
    
    Args:
        group_name: اسم المجموعة (مثل: 'shop_orders_1')
        message_type: نوع الرسالة (مثل: 'new_order', 'order_update')
        data: البيانات المراد إرسالها
    """
    channel_layer = get_channel_layer()
    if channel_layer:
        async_to_sync(channel_layer.group_send)(
            group_name,
            {
                'type': message_type,
                'data': data
            }
        )


# ==================== Order Notifications ====================

def notify_new_order(shop_owner_id, order_data):
    """إشعار صاحب المحل بطلب جديد"""
    send_to_group(f'shop_orders_{shop_owner_id}', 'new_order', order_data)


def notify_order_update(shop_owner_id, customer_id, driver_id, order_data):
    """إشعار جميع الأطراف بتحديث الطلب"""
    if shop_owner_id:
        send_to_group(f'shop_orders_{shop_owner_id}', 'order_update', order_data)
    
    if customer_id:
        send_to_group(f'customer_orders_{customer_id}', 'order_update', order_data)
    
    if driver_id:
        send_to_group(f'driver_{driver_id}', 'order_update', order_data)


def notify_driver_assigned(driver_id, order_data):
    """إشعار السائق بطلب توصيل جديد"""
    send_to_group(f'driver_{driver_id}', 'new_order', order_data)


def broadcast_chat_message_to_order(order_id, message_payload):
    """
    إرسال رسالة شات إلى مجموعة طلب (لظهورها فوراً عند العميل والمحل).
    message_payload: dict مثل {'id', 'sender_type', 'sender_name', 'message_type', 'content', 'created_at', ...}
    """
    channel_layer = get_channel_layer()
    if channel_layer:
        async_to_sync(channel_layer.group_send)(
            f'chat_order_{order_id}_shop_customer',
            {'type': 'chat_message', 'message': message_payload}
        )


# ==================== Driver Location ====================

def broadcast_driver_location(driver_id, customer_ids, latitude, longitude):
    """
    إرسال موقع السائق للعملاء
    
    Args:
        driver_id: معرف السائق
        customer_ids: قائمة معرفات العملاء
        latitude: خط العرض
        longitude: خط الطول
    """
    from django.utils import timezone
    
    location_data = {
        'driver_id': driver_id,
        'latitude': str(latitude),
        'longitude': str(longitude),
        'updated_at': timezone.now().isoformat()
    }
    
    for customer_id in customer_ids:
        send_to_group(f'customer_orders_{customer_id}', 'driver_location', location_data)
