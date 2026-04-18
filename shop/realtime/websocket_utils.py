"""
WebSocket Utility Functions
للإرسال من REST APIs إلى WebSocket Channels
"""

import logging

from channels.layers import get_channel_layer
from asgiref.sync import async_to_sync
from ..models import Driver, Order
from ..serializers import DriverSerializer, OrderSerializer
from .customer_app import (
    broadcast_customer_order_changed,
    broadcast_customer_support_changed,
)
from ..driver_chat.service import broadcast_driver_presence_update
from ..fcm.service import send_order_chat_push_fallback


logger = logging.getLogger(__name__)


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


def _serialize_order_snapshot(order, request=None, base_url=None):
    context = {}
    if request is not None:
        context['request'] = request
    if base_url:
        context['base_url'] = base_url
    return OrderSerializer(order, context=context).data


def _serialize_driver_snapshot(driver, request=None, base_url=None):
    context = {}
    if request is not None:
        context['request'] = request
    if base_url:
        context['base_url'] = base_url
    return DriverSerializer(driver, context=context).data


def _build_message_notification_payload(order, chat_type, message_payload, request=None, base_url=None):
    return {
        'order_id': order.id,
        'order_number': order.order_number,
        'chat_type': chat_type,
        'message': message_payload,
        'order': _serialize_order_snapshot(order, request=request, base_url=base_url),
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

    if customer_id and order_data.get('id'):
        broadcast_customer_order_changed(
            order_data['id'],
            customer_id=customer_id,
            shop_owner_id=shop_owner_id,
            include_order=True,
            include_shop=True,
            include_on_way=True,
            include_history=True,
        )

    if driver_id:
        send_to_group(f'driver_{driver_id}', 'order_update', order_data)


def notify_driver_assigned(driver_id, order_data):
    """إشعار السائق بطلب توصيل جديد"""
    send_to_group(f'driver_{driver_id}', 'new_order', order_data)


def broadcast_chat_message(order_id, chat_type, message_payload, request=None, base_url=None):
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

    notification_payload = _build_message_notification_payload(
        order,
        chat_type,
        message_payload,
        request=request,
        base_url=base_url,
    )
    for group_name in _get_message_target_groups(order, chat_type):
        send_to_group(group_name, 'new_message', notification_payload)

    try:
        send_order_chat_push_fallback(
            order.id,
            chat_type,
            message_payload,
            request=request,
            base_url=base_url,
        )
    except Exception as exc:
        logger.exception('fcm chat fallback failed for order_id=%s chat_type=%s: %s', order.id, chat_type, exc)


def broadcast_chat_message_to_order(order_id, message_payload, request=None, base_url=None):
    """
    إرسال رسالة شات إلى مجموعة طلب (لظهورها فوراً عند العميل والمحل).
    message_payload: dict مثل {'id', 'sender_type', 'sender_name', 'message_type', 'content', 'created_at', ...}
    """
    broadcast_chat_message(order_id, 'shop_customer', message_payload, request=request, base_url=base_url)


def broadcast_chat_message_to_customer(order_id, chat_type, message_payload, request=None, base_url=None):
    """
    إرسال رسالة تلقائية للعميل:
    - تظهر داخل غرفة الشات الحالية
    - وتظهر على قناة customer_orders فقط
    - بدون دفع new_message إلى لوحة المحل
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

    notification_payload = _build_message_notification_payload(
        order,
        chat_type,
        message_payload,
        request=request,
        base_url=base_url,
    )
    if order.customer_id and chat_type == 'shop_customer':
        broadcast_customer_order_changed(
            order.id,
            customer_id=order.customer_id,
            shop_owner_id=order.shop_owner_id,
            include_order=True,
            include_shop=True,
            include_on_way=False,
            include_history=True,
            base_url=base_url,
        )

    try:
        send_order_chat_push_fallback(
            order.id,
            chat_type,
            message_payload,
            request=request,
            base_url=base_url,
        )
    except Exception as exc:
        logger.exception('fcm customer chat fallback failed for order_id=%s chat_type=%s: %s', order.id, chat_type, exc)


def broadcast_support_chat_message(conversation_id, message_payload):
    """Send a support chat message to the standalone support chat room."""
    channel_layer = get_channel_layer()
    if channel_layer:
        async_to_sync(channel_layer.group_send)(
            f'support_chat_{conversation_id}',
            {'type': 'chat_message', 'message': message_payload}
        )


def notify_support_conversation_update(shop_owner_id, customer_id, conversation_data):
    """Notify shop/customer channels that a support conversation was created or updated."""
    if shop_owner_id:
        send_to_group(f'shop_orders_{shop_owner_id}', 'support_conversation_update', conversation_data)
    if customer_id:
        broadcast_customer_support_changed(
            conversation_data.get('support_conversation_id'),
            customer_id=customer_id,
            shop_owner_id=shop_owner_id,
            include_shop=True,
            include_history=True,
        )


def notify_support_message(shop_owner_id, customer_id, message_data):
    """Notify shop/customer dashboard channels about a new support message."""
    if shop_owner_id:
        send_to_group(f'shop_orders_{shop_owner_id}', 'support_message', message_data)
    if customer_id:
        broadcast_customer_support_changed(
            message_data.get('support_conversation_id') or message_data.get('thread_id'),
            customer_id=customer_id,
            shop_owner_id=shop_owner_id,
            include_shop=True,
            include_history=True,
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

    try:
        broadcast_driver_presence_update(driver_obj)
    except Exception as exc:
        print(f"driver_chat presence broadcast error: {exc}")
