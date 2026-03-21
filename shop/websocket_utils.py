"""
WebSocket Utility Functions
للإرسال من REST APIs إلى WebSocket Channels
"""

from channels.layers import get_channel_layer
from asgiref.sync import async_to_sync
from .models import Driver, Order
from .serializers import DriverSerializer, OrderSerializer


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


def _serialize_order_snapshot(order):
    return OrderSerializer(order).data


def _serialize_driver_snapshot(driver):
    return DriverSerializer(driver).data


def _build_message_notification_payload(order, chat_type, message_payload):
    return {
        'order_id': order.id,
        'order_number': order.order_number,
        'chat_type': chat_type,
        'message': message_payload,
        'order': _serialize_order_snapshot(order),
    }


def _get_message_target_groups(order, chat_type):
    group_names = set()

    if chat_type == 'shop_customer':
        if order.shop_owner_id:
            group_names.add(f'shop_orders_{order.shop_owner_id}')
        if order.customer_id:
            group_names.add(f'customer_orders_{order.customer_id}')
    elif chat_type == 'driver_customer':
        if order.customer_id:
            group_names.add(f'customer_orders_{order.customer_id}')
        if order.driver_id:
            group_names.add(f'driver_{order.driver_id}')

    return list(group_names)


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


def broadcast_chat_message(order_id, chat_type, message_payload):
    """
    إرسال رسالة شات إلى مجموعة الطلب حسب نوع المحادثة.
    chat_type: shop_customer | driver_customer
    """
    channel_layer = get_channel_layer()
    if channel_layer:
        async_to_sync(channel_layer.group_send)(
            f'chat_order_{order_id}_{chat_type}',
            {'type': 'chat_message', 'message': message_payload}
        )

    try:
        order = Order.objects.select_related('customer', 'employee', 'driver').get(id=order_id)
    except Order.DoesNotExist:
        return

    notification_payload = _build_message_notification_payload(order, chat_type, message_payload)
    for group_name in _get_message_target_groups(order, chat_type):
        send_to_group(group_name, 'new_message', notification_payload)


def broadcast_chat_message_to_order(order_id, message_payload):
    """
    إرسال رسالة شات إلى مجموعة طلب (لظهورها فوراً عند العميل والمحل).
    message_payload: dict مثل {'id', 'sender_type', 'sender_name', 'message_type', 'content', 'created_at', ...}
    """
    broadcast_chat_message(order_id, 'shop_customer', message_payload)


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


def notify_shop_status_updated(shop_owner_id, status_data):
    """إشعار لوحة المتجر بتحديث حالة المتجر."""
    send_to_group(f'shop_orders_{shop_owner_id}', 'store_status_updated', status_data)


def notify_driver_status_updated(driver):
    """إشعار لوحات المتاجر المرتبطة بتحديث حالة السائق."""
    driver_obj = driver if isinstance(driver, Driver) else Driver.objects.filter(id=driver).first()
    if not driver_obj:
        return

    shop_owner_ids = list(driver_obj.shops.values_list('id', flat=True).distinct())
    payload = {
        'shop_owner_ids': shop_owner_ids,
        'driver': _serialize_driver_snapshot(driver_obj),
    }

    for shop_owner_id in shop_owner_ids:
        send_to_group(f'shop_orders_{shop_owner_id}', 'driver_status_updated', payload)
