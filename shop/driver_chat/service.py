import base64
import json
import logging
from datetime import timedelta
from datetime import timezone as dt_timezone
from typing import Optional

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from user.models import ShopOwner
from user.utils import build_absolute_file_url

from ..models import (
    Driver,
    DriverChatCall,
    DriverChatConversation,
    DriverChatEvent,
    DriverChatMessage,
    DriverChatOrder,
    DriverPresenceConnection,
    Order,
    ShopDriver,
)
from ..realtime.presence import format_utc_iso8601


logger = logging.getLogger(__name__)

DRIVER_CHAT_MESSAGE_PAGE_SIZE = 20
CALL_TIMEOUT_SECONDS = 30
DRIVER_PRESENCE_TIMEOUT_SECONDS = 75


def shop_driver_chats_group(shop_owner_id):
    return f'driver_chats_shop_{shop_owner_id}'


def driver_driver_chats_group(driver_id):
    return f'driver_chats_driver_{driver_id}'


def _parse_order_items(raw_value):
    if not raw_value:
        return []

    parsed = raw_value
    if isinstance(raw_value, str):
        try:
            parsed = json.loads(raw_value)
        except (TypeError, ValueError):
            parsed = [raw_value]

    if not isinstance(parsed, list):
        parsed = [parsed]

    normalized = []
    for index, item in enumerate(parsed, start=1):
        if isinstance(item, dict):
            normalized.append({
                'id': str(item.get('id') or f'item_{index}'),
                'name': item.get('name') or item.get('title') or item.get('product_name') or f'Item {index}',
                'price': float(item.get('price') or item.get('amount') or 0),
                'quantity': int(item.get('quantity') or 1),
            })
        else:
            normalized.append({
                'id': f'item_{index}',
                'name': str(item),
                'price': 0.0,
                'quantity': 1,
            })
    return normalized


def _message_preview(message: DriverChatMessage):
    if message.message_type == 'voice':
        return 'رسالة صوتية'
    if message.message_type == 'image':
        return 'صورة'
    if message.message_type == 'invoice':
        order_number = getattr(getattr(message.conversation_order, 'order', None), 'order_number', None)
        return f'فاتورة الطلب #{order_number}' if order_number else 'فاتورة جديدة'
    if message.message_type == 'call':
        return 'مكالمة'
    if (message.metadata or {}).get('card_type') == 'transfer_request':
        order_number = getattr(getattr(message.conversation_order, 'order', None), 'order_number', None)
        return f'طلب تحويل الأوردر #{order_number}' if order_number else 'طلب تحويل الأوردر'
    text = str(message.text or '').strip()
    if text:
        return text[:120]
    return 'رسالة جديدة'


def _driver_presence_status(driver: Driver):
    has_trip = driver.orders.filter(status__in=['preparing', 'on_way']).exists()
    if not bool(getattr(driver, 'is_online', False)):
        return 'offline'
    if has_trip:
        return 'on_trip'
    if driver.status == 'busy':
        return 'busy'
    return 'online'


def _driver_is_online(driver: Driver):
    return bool(getattr(driver, 'is_online', False))


def serialize_driver_chat_driver(driver: Driver, *, request=None, scope=None, base_url=None):
    vehicle_label = str(driver.vehicle_label or '').strip() or (
        driver.get_vehicle_type_display() if getattr(driver, 'vehicle_type', None) else None
    )
    return {
        'id': str(driver.id),
        'name': driver.name,
        'phone': driver.phone_number,
        'avatar_url': build_absolute_file_url(driver.profile_image, request=request, scope=scope, base_url=base_url),
        'rating': float(driver.rating or 0),
        'vehicle_label': vehicle_label,
        'plate_number': driver.plate_number,
        'is_online': _driver_is_online(driver),
        'presence_status': _driver_presence_status(driver),
        'last_seen_at': format_utc_iso8601(driver.last_seen_at),
    }


def serialize_driver_chat_shop(shop_owner: ShopOwner):
    return {
        'id': str(shop_owner.id),
        'shop_name': shop_owner.shop_name,
        'shop_number': shop_owner.shop_number,
        'owner_name': shop_owner.owner_name,
    }


def serialize_driver_chat_order(link: DriverChatOrder):
    order = link.order
    customer = getattr(order, 'customer', None)
    delivery_address = None
    if getattr(order, 'delivery_address_id', None) and getattr(order.delivery_address, 'full_address', None):
        delivery_address = order.delivery_address.full_address
    delivery_address = delivery_address or order.address
    items = _parse_order_items(order.items)
    return {
        'id': f'order_{order.id}',
        'order_number': f'#{order.order_number}',
        'customer': {
            'id': f'c_{customer.id}' if customer else None,
            'name': customer.name if customer else None,
            'phone': customer.phone_number if customer else None,
        },
        'delivery_address': delivery_address,
        'total_amount': float(order.total_amount or 0),
        'currency': 'EGP',
        'items_count': len(items),
        'created_at': format_utc_iso8601(order.created_at),
        'delivery_note': order.notes,
        'status': link.status,
        'items': items,
        'delivery_fee': float(order.delivery_fee or 0),
        'assigned_driver_name': link.conversation.driver.name if link.conversation_id else None,
        'transfer_reason': link.transfer_reason,
    }


def serialize_driver_chat_message(message: DriverChatMessage, *, request=None, scope=None, base_url=None):
    payload = {
        'id': message.public_id or f'msg_{message.pk}',
        'type': message.message_type,
        'sender': message.sender_type,
        'sent_at': format_utc_iso8601(message.created_at),
        'text': message.text,
        'audio_url': build_absolute_file_url(message.audio_url, request=request, scope=scope, base_url=base_url),
        'image_url': (message.metadata or {}).get('image_url'),
        'voice_duration_seconds': message.voice_duration_seconds,
        'invoice_order': serialize_driver_chat_order(message.conversation_order) if message.conversation_order_id else None,
        'client_message_id': message.client_message_id,
        'delivery_status': 'read' if message.is_read else message.delivery_status,
        'metadata': message.metadata or None,
    }
    if message.call_id:
        payload['call_id'] = message.call.public_id
    return payload


def serialize_driver_chat_call(call: DriverChatCall):
    return {
        'call_id': call.public_id or f'call_{call.pk}',
        'conversation_id': call.conversation.public_id if call.conversation_id else None,
        'driver_id': str(call.conversation.driver_id) if call.conversation_id else None,
        'initiated_by': call.initiated_by,
        'status': call.status,
        'created_at': format_utc_iso8601(call.created_at),
        'answered_at': format_utc_iso8601(call.answered_at),
        'ended_at': format_utc_iso8601(call.ended_at),
        'duration_seconds': call.duration_seconds,
        'reason': call.reason,
        'channel_name': call.channel_name,
        'rtc_token': call.rtc_token,
    }


def serialize_driver_chat_conversation(conversation: DriverChatConversation, *, include_messages=True, request=None, scope=None, base_url=None):
    orders_qs = (
        conversation.orders
        .select_related('order', 'order__customer', 'order__driver', 'order__delivery_address')
        .order_by('-updated_at', '-created_at')
    )
    orders = [serialize_driver_chat_order(item) for item in orders_qs]
    messages = []
    next_cursor = None
    if include_messages:
        messages_page = get_conversation_messages_page(conversation, base_url=base_url, request=request, scope=scope)
        messages = messages_page['messages']
        next_cursor = messages_page['next_cursor']

    return {
        'id': conversation.public_id or f'conv_{conversation.pk}',
        'shop': serialize_driver_chat_shop(conversation.shop_owner),
        'driver': serialize_driver_chat_driver(conversation.driver, request=request, scope=scope, base_url=base_url),
        'orders': orders,
        'status': conversation.status,
        'updated_at': format_utc_iso8601(conversation.updated_at),
        'unread_count': conversation.unread_count,
        'last_message_preview': conversation.last_message_preview,
        'messages': messages,
        'messages_next_cursor': next_cursor,
    }


def _extract_numeric_id(raw_value):
    raw_text = str(raw_value or '').strip()
    if not raw_text:
        return None
    if '_' in raw_text:
        tail = raw_text.rsplit('_', 1)[-1]
        if tail.isdigit():
            return int(tail)
    return int(raw_text) if raw_text.isdigit() else None


def get_conversation_by_public_id(conversation_id, *, shop_owner=None, driver=None):
    qs = DriverChatConversation.objects.select_related('driver', 'shop_owner')
    if shop_owner is not None:
        qs = qs.filter(shop_owner=shop_owner)
    if driver is not None:
        qs = qs.filter(driver=driver)
    numeric_id = _extract_numeric_id(conversation_id)
    if numeric_id is not None:
        return qs.filter(Q(pk=numeric_id) | Q(public_id=str(conversation_id))).first()
    return qs.filter(public_id=str(conversation_id)).first()


def get_message_by_public_id(message_id, *, conversation=None):
    qs = DriverChatMessage.objects.select_related('conversation', 'conversation_order', 'call')
    if conversation is not None:
        qs = qs.filter(conversation=conversation)
    numeric_id = _extract_numeric_id(message_id)
    if numeric_id is not None:
        return qs.filter(Q(pk=numeric_id) | Q(public_id=str(message_id))).first()
    return qs.filter(public_id=str(message_id)).first()


def get_call_by_public_id(call_id, *, conversation=None):
    qs = DriverChatCall.objects.select_related('conversation', 'conversation__driver')
    if conversation is not None:
        qs = qs.filter(conversation=conversation)
    numeric_id = _extract_numeric_id(call_id)
    if numeric_id is not None:
        return qs.filter(Q(pk=numeric_id) | Q(public_id=str(call_id))).first()
    return qs.filter(public_id=str(call_id)).first()


def get_order_for_conversation(conversation: DriverChatConversation, order_id):
    numeric_id = _extract_numeric_id(order_id)
    qs = DriverChatOrder.objects.select_related('order', 'order__customer', 'order__driver', 'order__delivery_address').filter(
        conversation=conversation
    )
    if numeric_id is not None:
        return qs.filter(Q(order_id=numeric_id) | Q(order__id=numeric_id)).first()
    return None


def _encode_cursor(message: DriverChatMessage):
    payload = {
        'message_id': message.pk,
        'created_at': format_utc_iso8601(message.created_at),
    }
    return base64.urlsafe_b64encode(json.dumps(payload).encode('utf-8')).decode('utf-8')


def _decode_cursor(cursor):
    if not cursor:
        return None
    try:
        decoded = base64.urlsafe_b64decode(str(cursor).encode('utf-8')).decode('utf-8')
        payload = json.loads(decoded)
        created_at = payload.get('created_at')
        message_id = int(payload.get('message_id'))
        created_dt = timezone.datetime.fromisoformat(created_at.replace('Z', '+00:00'))
        if timezone.is_naive(created_dt):
            created_dt = timezone.make_aware(created_dt, dt_timezone.utc)
        return {
            'created_at': created_dt,
            'message_id': message_id,
        }
    except Exception:
        return None


def get_conversation_messages_page(conversation: DriverChatConversation, *, cursor=None, limit=DRIVER_CHAT_MESSAGE_PAGE_SIZE, request=None, scope=None, base_url=None):
    qs = (
        conversation.messages
        .select_related('conversation_order', 'conversation_order__order', 'conversation_order__order__customer', 'call')
        .order_by('-created_at', '-pk')
    )
    cursor_data = _decode_cursor(cursor)
    if cursor_data:
        qs = qs.filter(
            Q(created_at__lt=cursor_data['created_at']) |
            Q(created_at=cursor_data['created_at'], pk__lt=cursor_data['message_id'])
        )

    batch = list(qs[:limit + 1])
    has_more = len(batch) > limit
    batch = batch[:limit]
    messages = [
        serialize_driver_chat_message(item, request=request, scope=scope, base_url=base_url)
        for item in reversed(batch)
    ]
    next_cursor = _encode_cursor(batch[-1]) if has_more and batch else None
    return {
        'messages': messages,
        'next_cursor': next_cursor,
    }


def _derive_conversation_status(conversation: DriverChatConversation):
    active_link = (
        conversation.orders
        .filter(is_active=True)
        .order_by('-updated_at', '-created_at')
        .first()
    )
    if active_link:
        return active_link.status

    latest_link = conversation.orders.order_by('-updated_at', '-created_at').first()
    if latest_link:
        return latest_link.status
    return 'waiting_reply'


def refresh_conversation_snapshot(conversation: DriverChatConversation):
    latest_message = conversation.messages.order_by('-created_at', '-pk').first()
    conversation.status = _derive_conversation_status(conversation)
    conversation.updated_at = timezone.now()
    if latest_message:
        conversation.last_message_preview = _message_preview(latest_message)
        conversation.last_message_at = latest_message.created_at
    conversation.save(update_fields=['status', 'updated_at', 'last_message_preview', 'last_message_at', 'unread_count'])
    return conversation


def ensure_conversation(shop_owner, driver):
    conversation, created = DriverChatConversation.objects.get_or_create(
        shop_owner=shop_owner,
        driver=driver,
        defaults={'status': 'waiting_reply'},
    )
    return conversation, created


def ensure_conversation_order(conversation: DriverChatConversation, order: Order, *, status='waiting_reply', transfer_reason=None, is_active=True):
    link, created = DriverChatOrder.objects.get_or_create(
        conversation=conversation,
        order=order,
        defaults={
            'status': status,
            'transfer_reason': transfer_reason,
            'is_active': is_active,
        },
    )
    changed_fields = []
    if link.status != status:
        link.status = status
        changed_fields.append('status')
    if link.transfer_reason != transfer_reason:
        link.transfer_reason = transfer_reason
        changed_fields.append('transfer_reason')
    if link.is_active != is_active:
        link.is_active = is_active
        changed_fields.append('is_active')
    if changed_fields:
        changed_fields.append('updated_at')
        link.save(update_fields=changed_fields)
    return link, created


def _event_envelope(event_type, *, data=None, request_id=None, success=True, event_id=None):
    payload = {
        'type': event_type,
        'success': success,
        'data': data or {},
        'sent_at': format_utc_iso8601(timezone.now()),
    }
    if request_id:
        payload['request_id'] = request_id
    if event_id:
        payload['event_id'] = event_id
    return payload


def _group_send(group_name, payload):
    channel_layer = get_channel_layer()
    if not channel_layer:
        return
    async_to_sync(channel_layer.group_send)(
        group_name,
        {
            'type': 'driver_chat_event',
            'payload': payload,
        }
    )


def publish_driver_chat_event(*, shop_owner_id, event_type, data=None, request_id=None, conversation=None, driver=None, persist=True, send_to_shop=True, send_to_driver=True):
    event_obj = None
    if persist and shop_owner_id:
        event_obj = DriverChatEvent.objects.create(
            shop_owner_id=shop_owner_id,
            conversation=conversation,
            driver=driver,
            event_type=event_type,
            payload={},
        )

    payload = _event_envelope(
        event_type,
        data=data,
        request_id=request_id,
        success=True,
        event_id=event_obj.event_id if event_obj else None,
    )

    if event_obj:
        event_obj.payload = payload
        event_obj.save(update_fields=['payload'])

    if send_to_shop and shop_owner_id:
        _group_send(shop_driver_chats_group(shop_owner_id), payload)
    target_driver = driver or getattr(conversation, 'driver', None)
    if send_to_driver and target_driver is not None:
        _group_send(driver_driver_chats_group(target_driver.id), payload)
    return payload


def emit_driver_chat_error(*, shop_owner_id=None, driver_id=None, code='UNKNOWN_ERROR', message='حدث خطأ', request_id=None):
    data = {
        'code': code,
        'message': message,
    }
    payload = _event_envelope('driver_chat.error', data=data, request_id=request_id, success=False)
    if shop_owner_id:
        _group_send(shop_driver_chats_group(shop_owner_id), payload)
    if driver_id:
        _group_send(driver_driver_chats_group(driver_id), payload)
    return payload


def broadcast_conversation_snapshot(conversation: DriverChatConversation, *, request=None, scope=None, base_url=None, created=False):
    refresh_conversation_snapshot(conversation)
    serialized = serialize_driver_chat_conversation(conversation, request=request, scope=scope, base_url=base_url)
    event_type = 'driver_chat.conversation_created' if created else 'driver_chat.conversation_updated'
    publish_driver_chat_event(
        shop_owner_id=conversation.shop_owner_id,
        event_type=event_type,
        data={'conversation': serialized},
        conversation=conversation,
        driver=conversation.driver,
    )
    return serialized


def broadcast_message_created(message: DriverChatMessage, *, request=None, scope=None, base_url=None):
    serialized = serialize_driver_chat_message(message, request=request, scope=scope, base_url=base_url)
    publish_driver_chat_event(
        shop_owner_id=message.conversation.shop_owner_id,
        event_type='driver_chat.message_created',
        data={
            'conversation_id': message.conversation.public_id,
            'message': serialized,
        },
        conversation=message.conversation,
        driver=message.conversation.driver,
    )
    return serialized


def broadcast_order_updated(link: DriverChatOrder):
    publish_driver_chat_event(
        shop_owner_id=link.conversation.shop_owner_id,
        event_type='driver_chat.order_updated',
        data={
            'conversation_id': link.conversation.public_id,
            'order': serialize_driver_chat_order(link),
        },
        conversation=link.conversation,
        driver=link.conversation.driver,
    )


def broadcast_unread_updated(conversation: DriverChatConversation):
    publish_driver_chat_event(
        shop_owner_id=conversation.shop_owner_id,
        event_type='driver_chat.unread_updated',
        data={
            'conversation_id': conversation.public_id,
            'unread_count': conversation.unread_count,
        },
        conversation=conversation,
        driver=conversation.driver,
    )


def create_message(
    *,
    conversation: DriverChatConversation,
    sender_type,
    message_type,
    text=None,
    audio_url=None,
    voice_duration_seconds=None,
    client_message_id=None,
    conversation_order: Optional[DriverChatOrder] = None,
    call: Optional[DriverChatCall] = None,
    metadata=None,
):
    with transaction.atomic():
        message = DriverChatMessage.objects.create(
            conversation=conversation,
            sender_type=sender_type,
            message_type=message_type,
            text=text,
            audio_url=audio_url,
            voice_duration_seconds=voice_duration_seconds,
            client_message_id=client_message_id,
            conversation_order=conversation_order,
            call=call,
            metadata=metadata or None,
            is_read=sender_type == 'store',
        )
        if sender_type == 'driver':
            conversation.unread_count = conversation.messages.filter(
                sender_type='driver',
                is_read=False,
            ).count()
        refresh_conversation_snapshot(conversation)
    return message


def mark_conversation_read(conversation: DriverChatConversation, actor):
    with transaction.atomic():
        if actor == 'store':
            DriverChatMessage.objects.filter(
                conversation=conversation,
                sender_type='driver',
                is_read=False,
            ).update(is_read=True, delivery_status='read', updated_at=timezone.now())
            conversation.unread_count = 0
            refresh_conversation_snapshot(conversation)
        else:
            DriverChatMessage.objects.filter(
                conversation=conversation,
                sender_type__in=['store', 'system'],
                is_read=False,
            ).update(is_read=True, delivery_status='read', updated_at=timezone.now())
    broadcast_unread_updated(conversation)
    broadcast_conversation_snapshot(conversation)


def _map_order_status_to_driver_chat_status(order: Order):
    if order.status == 'cancelled':
        return 'cancelled'
    if order.status == 'delivered':
        return 'delivered'
    if order.status == 'on_way':
        return 'driver_on_way'
    if order.status in {'confirmed', 'preparing'}:
        return 'awaiting_driver_acceptance'
    return 'waiting_reply'


def sync_order_status_to_driver_chats(order: Order):
    target_status = _map_order_status_to_driver_chat_status(order)
    affected_driver_ids = set()
    links = list(
        DriverChatOrder.objects.select_related('conversation', 'conversation__driver', 'order', 'order__customer', 'order__delivery_address')
        .filter(order=order)
    )
    for link in links:
        affected_driver_ids.add(link.conversation.driver_id)
        if link.status == 'transferred_to_another_driver':
            continue
        changed_fields = []
        if link.status != target_status:
            link.status = target_status
            changed_fields.append('status')
        if target_status in {'cancelled', 'delivered'} and link.is_active:
            link.is_active = False
            changed_fields.append('is_active')
        if changed_fields:
            changed_fields.append('updated_at')
            link.save(update_fields=changed_fields)
        refresh_conversation_snapshot(link.conversation)
        broadcast_order_updated(link)
        broadcast_conversation_snapshot(link.conversation)
    for driver_id in affected_driver_ids:
        broadcast_driver_presence_update(driver_id)


def _log_sensitive(action, **context):
    logger.info("driver_chat.%s %s", action, json.dumps(context, ensure_ascii=False, default=str))


def _deactivate_other_order_links(order: Order, active_conversation: DriverChatConversation, *, request=None, scope=None, base_url=None):
    other_links = list(
        DriverChatOrder.objects
        .select_related('conversation', 'conversation__driver', 'order')
        .filter(order=order, is_active=True)
        .exclude(conversation=active_conversation)
    )
    for link in other_links:
        link.status = 'transferred_to_another_driver'
        link.is_active = False
        link.save(update_fields=['status', 'is_active', 'updated_at'])
        system_message = create_message(
            conversation=link.conversation,
            sender_type='system',
            message_type='system',
            text=f'تم تحويل الأوردر إلى السائق {active_conversation.driver.name}',
            conversation_order=link,
        )
        broadcast_order_updated(link)
        broadcast_message_created(system_message, request=request, scope=scope, base_url=base_url)
        broadcast_conversation_snapshot(link.conversation, request=request, scope=scope, base_url=base_url)
        broadcast_driver_presence_update(link.conversation.driver_id)


def assign_order_to_driver_conversation(order: Order, driver: Driver, *, transfer_reason=None, request=None, scope=None, base_url=None):
    conversation, created = ensure_conversation(order.shop_owner, driver)
    link, _ = ensure_conversation_order(
        conversation,
        order,
        status='awaiting_driver_acceptance',
        transfer_reason=transfer_reason,
        is_active=True,
    )
    _deactivate_other_order_links(order, conversation, request=request, scope=scope, base_url=base_url)
    invoice_message = create_message(
        conversation=conversation,
        sender_type='store',
        message_type='invoice',
        text=f'تم إرسال فاتورة الطلب #{order.order_number}',
        conversation_order=link,
    )
    driver.current_orders_count = driver.orders.filter(status__in=['new', 'preparing', 'on_way']).count()
    driver.save(update_fields=['current_orders_count', 'updated_at'])
    broadcast_order_updated(link)
    broadcast_message_created(invoice_message, request=request, scope=scope, base_url=base_url)
    broadcast_conversation_snapshot(conversation, request=request, scope=scope, base_url=base_url, created=created)
    broadcast_driver_presence_update(driver.id)
    return conversation, link, invoice_message


def transfer_order_between_drivers(order: Order, *, source_driver: Driver, target_driver: Driver, request=None, scope=None, base_url=None):
    source_conversation, _ = ensure_conversation(order.shop_owner, source_driver)
    source_link, _ = ensure_conversation_order(
        source_conversation,
        order,
        status='transferred_to_another_driver',
        transfer_reason=None,
        is_active=False,
    )
    source_message = create_message(
        conversation=source_conversation,
        sender_type='system',
        message_type='system',
        text=f'تم تحويل الأوردر إلى السائق {target_driver.name}',
        conversation_order=source_link,
    )
    broadcast_order_updated(source_link)
    broadcast_message_created(source_message, request=request, scope=scope, base_url=base_url)
    broadcast_conversation_snapshot(source_conversation, request=request, scope=scope, base_url=base_url)

    order.driver = target_driver
    order.driver_assigned_at = timezone.now()
    order.driver_accepted_at = None
    order.driver_chat_opened_at = None
    order.save(update_fields=['driver', 'driver_assigned_at', 'driver_accepted_at', 'driver_chat_opened_at', 'updated_at'])
    source_driver.current_orders_count = source_driver.orders.filter(status__in=['new', 'preparing', 'on_way']).count()
    source_driver.save(update_fields=['current_orders_count', 'updated_at'])
    target_driver.current_orders_count = target_driver.orders.filter(status__in=['new', 'preparing', 'on_way']).count()
    target_driver.save(update_fields=['current_orders_count', 'updated_at'])

    target_conversation, _, _ = assign_order_to_driver_conversation(
        order,
        target_driver,
        request=request,
        scope=scope,
        base_url=base_url,
    )
    _log_sensitive(
        'transfer_to_driver',
        order_id=order.id,
        source_driver_id=source_driver.id,
        target_driver_id=target_driver.id,
        source_conversation_id=source_conversation.public_id,
        target_conversation_id=target_conversation.public_id,
    )
    return source_conversation, target_conversation


def sync_order_assignment_change(order: Order, *, old_driver: Optional[Driver], new_driver: Optional[Driver], request=None, scope=None, base_url=None):
    if old_driver and new_driver and old_driver.id != new_driver.id:
        return transfer_order_between_drivers(
            order,
            source_driver=old_driver,
            target_driver=new_driver,
            request=request,
            scope=scope,
            base_url=base_url,
        )
    if not old_driver and new_driver:
        assign_order_to_driver_conversation(order, new_driver, request=request, scope=scope, base_url=base_url)
        _log_sensitive('assign_driver', order_id=order.id, driver_id=new_driver.id)
        return
    sync_order_status_to_driver_chats(order)


def store_send_text(*, conversation: DriverChatConversation, text, client_message_id=None, request=None, scope=None, base_url=None):
    message = create_message(
        conversation=conversation,
        sender_type='store',
        message_type='text',
        text=text,
        client_message_id=client_message_id,
    )
    broadcast_message_created(message, request=request, scope=scope, base_url=base_url)
    broadcast_conversation_snapshot(conversation, request=request, scope=scope, base_url=base_url)
    return message


def store_send_voice(*, conversation: DriverChatConversation, audio_url, voice_duration_seconds=None, client_message_id=None, request=None, scope=None, base_url=None):
    message = create_message(
        conversation=conversation,
        sender_type='store',
        message_type='voice',
        audio_url=audio_url,
        voice_duration_seconds=voice_duration_seconds,
        client_message_id=client_message_id,
    )
    broadcast_message_created(message, request=request, scope=scope, base_url=base_url)
    broadcast_conversation_snapshot(conversation, request=request, scope=scope, base_url=base_url)
    return message


def store_send_image(*, conversation: DriverChatConversation, image_url, text=None, client_message_id=None, request=None, scope=None, base_url=None):
    message = create_message(
        conversation=conversation,
        sender_type='store',
        message_type='image',
        text=str(text or '').strip() or None,
        client_message_id=client_message_id,
        metadata={'image_url': image_url},
    )
    broadcast_message_created(message, request=request, scope=scope, base_url=base_url)
    broadcast_conversation_snapshot(conversation, request=request, scope=scope, base_url=base_url)
    return message


def driver_send_text(*, conversation: DriverChatConversation, text, client_message_id=None, request=None, scope=None, base_url=None):
    message = create_message(
        conversation=conversation,
        sender_type='driver',
        message_type='text',
        text=text,
        client_message_id=client_message_id,
    )
    broadcast_message_created(message, request=request, scope=scope, base_url=base_url)
    broadcast_unread_updated(conversation)
    broadcast_conversation_snapshot(conversation, request=request, scope=scope, base_url=base_url)
    return message


def driver_send_voice(*, conversation: DriverChatConversation, audio_url, voice_duration_seconds=None, client_message_id=None, request=None, scope=None, base_url=None):
    message = create_message(
        conversation=conversation,
        sender_type='driver',
        message_type='voice',
        audio_url=audio_url,
        voice_duration_seconds=voice_duration_seconds,
        client_message_id=client_message_id,
    )
    broadcast_message_created(message, request=request, scope=scope, base_url=base_url)
    broadcast_unread_updated(conversation)
    broadcast_conversation_snapshot(conversation, request=request, scope=scope, base_url=base_url)
    return message


def driver_send_image(*, conversation: DriverChatConversation, image_url, text=None, client_message_id=None, request=None, scope=None, base_url=None):
    message = create_message(
        conversation=conversation,
        sender_type='driver',
        message_type='image',
        text=str(text or '').strip() or None,
        client_message_id=client_message_id,
        metadata={'image_url': image_url},
    )
    broadcast_message_created(message, request=request, scope=scope, base_url=base_url)
    broadcast_unread_updated(conversation)
    broadcast_conversation_snapshot(conversation, request=request, scope=scope, base_url=base_url)
    return message


def driver_accept_order(*, conversation: DriverChatConversation, conversation_order: DriverChatOrder, request=None, scope=None, base_url=None):
    order = conversation_order.order
    conversation_order.status = 'driver_on_way'
    conversation_order.transfer_reason = None
    conversation_order.save(update_fields=['status', 'transfer_reason', 'updated_at'])
    order.status = 'on_way'
    order.save(update_fields=['status', 'updated_at'])
    system_message = create_message(
        conversation=conversation,
        sender_type='system',
        message_type='system',
        text='تم قبول الأوردر من السائق',
        conversation_order=conversation_order,
    )
    broadcast_order_updated(conversation_order)
    broadcast_message_created(system_message, request=request, scope=scope, base_url=base_url)
    broadcast_conversation_snapshot(conversation, request=request, scope=scope, base_url=base_url)
    broadcast_driver_presence_update(conversation.driver_id)
    _log_sensitive('accept_order', order_id=order.id, conversation_id=conversation.public_id, driver_id=conversation.driver_id)
    return conversation_order


def driver_mark_busy(*, conversation: DriverChatConversation, conversation_order: DriverChatOrder, request=None, scope=None, base_url=None):
    conversation.driver.status = 'busy'
    conversation.driver.save(update_fields=['status', 'updated_at'])
    conversation_order.status = 'driver_busy'
    conversation_order.save(update_fields=['status', 'updated_at'])
    system_message = create_message(
        conversation=conversation,
        sender_type='system',
        message_type='system',
        text='السائق أبلغ أنه مشغول',
        conversation_order=conversation_order,
    )
    broadcast_order_updated(conversation_order)
    broadcast_message_created(system_message, request=request, scope=scope, base_url=base_url)
    broadcast_conversation_snapshot(conversation, request=request, scope=scope, base_url=base_url)
    broadcast_driver_presence_update(conversation.driver)
    _log_sensitive('mark_busy', order_id=conversation_order.order_id, conversation_id=conversation.public_id, driver_id=conversation.driver_id)
    return conversation_order


def driver_request_transfer(*, conversation: DriverChatConversation, conversation_order: DriverChatOrder, reason, request=None, scope=None, base_url=None):
    conversation_order.status = 'transfer_requested'
    conversation_order.transfer_reason = reason
    conversation_order.save(update_fields=['status', 'transfer_reason', 'updated_at'])
    transfer_request_message = create_message(
        conversation=conversation,
        sender_type='driver',
        message_type='system',
        text=None,
        conversation_order=conversation_order,
        metadata={
            'card_type': 'transfer_request',
            'render_mode': 'order_card_only',
            'title': 'طلب تحويل الأوردر',
            'subtitle': 'مرسل من الدليفري للمتجر',
            'reason': reason,
        },
    )
    broadcast_order_updated(conversation_order)
    broadcast_message_created(transfer_request_message, request=request, scope=scope, base_url=base_url)
    broadcast_unread_updated(conversation)
    broadcast_conversation_snapshot(conversation, request=request, scope=scope, base_url=base_url)
    _log_sensitive('request_transfer', order_id=conversation_order.order_id, conversation_id=conversation.public_id, driver_id=conversation.driver_id, reason=reason)
    return conversation_order
    message = create_message(
        conversation=conversation,
        sender_type='driver',
        message_type='text',
        text=f'طلب تحويل الأوردر بسبب: {reason}',
        conversation_order=conversation_order,
    )
    broadcast_order_updated(conversation_order)
    broadcast_message_created(message, request=request, scope=scope, base_url=base_url)
    broadcast_unread_updated(conversation)
    broadcast_conversation_snapshot(conversation, request=request, scope=scope, base_url=base_url)
    _log_sensitive('request_transfer', order_id=conversation_order.order_id, conversation_id=conversation.public_id, driver_id=conversation.driver_id, reason=reason)
    return conversation_order


def request_transfer_for_order(*, order: Order, driver: Driver, reason, request=None, scope=None, base_url=None):
    conversation, _ = ensure_conversation(order.shop_owner, driver)
    link, _ = ensure_conversation_order(
        conversation,
        order,
        status='waiting_reply',
        transfer_reason=None,
        is_active=True,
    )
    return driver_request_transfer(
        conversation=conversation,
        conversation_order=link,
        reason=reason,
        request=request,
        scope=scope,
        base_url=base_url,
    )


def get_available_transfer_drivers(shop_owner, *, exclude_driver_id=None):
    exclude_numeric_id = _extract_numeric_id(exclude_driver_id) or 0
    qs = (
        Driver.objects
        .filter(driver_shops__shop_owner=shop_owner, driver_shops__status='active')
        .exclude(id=exclude_numeric_id)
        .distinct()
        .order_by('name')
    )
    return [serialize_driver_chat_driver(driver) for driver in qs]


def get_shop_snapshot(shop_owner, *, request=None, scope=None, base_url=None):
    conversations = (
        DriverChatConversation.objects
        .filter(shop_owner=shop_owner)
        .select_related('driver', 'shop_owner')
        .order_by('-updated_at', '-created_at')
    )
    latest_event = (
        DriverChatEvent.objects
        .filter(shop_owner=shop_owner)
        .order_by('-created_at', '-pk')
        .first()
    )
    return {
        'conversations': [
            serialize_driver_chat_conversation(item, request=request, scope=scope, base_url=base_url)
            for item in conversations
        ],
        'last_event_id': latest_event.event_id if latest_event else None,
    }


def get_driver_snapshot(driver, *, request=None, scope=None, base_url=None):
    conversations = (
        DriverChatConversation.objects
        .filter(driver=driver)
        .select_related('driver', 'shop_owner')
        .order_by('-updated_at', '-created_at')
    )
    return {
        'conversations': [
            serialize_driver_chat_conversation(item, request=request, scope=scope, base_url=base_url)
            for item in conversations
        ],
    }


def get_resync_events(shop_owner, last_event_id):
    base_qs = DriverChatEvent.objects.filter(shop_owner=shop_owner).order_by('created_at', 'pk')
    if not last_event_id:
        return [event.payload for event in base_qs]
    last_event = base_qs.filter(event_id=last_event_id).first()
    if not last_event:
        return None
    next_events = base_qs.filter(Q(created_at__gt=last_event.created_at) | Q(created_at=last_event.created_at, pk__gt=last_event.pk))
    return [event.payload for event in next_events]


def _driver_presence_payload(driver: Driver):
    return {
        'driver_id': str(driver.id),
        'is_online': _driver_is_online(driver),
        'presence_status': _driver_presence_status(driver),
        'last_seen_at': format_utc_iso8601(driver.last_seen_at),
        'active_connections_count': int(getattr(driver, 'active_connections_count', 0) or 0),
        'driver': serialize_driver_chat_driver(driver),
    }


def _apply_driver_presence_state(driver: Driver, has_connections: bool):
    now = timezone.now()
    update_fields = []
    changed = bool(driver.is_online) != bool(has_connections)

    if changed:
        driver.is_online = bool(has_connections)
        update_fields.append('is_online')

    if has_connections:
        if driver.last_seen_at is None:
            driver.last_seen_at = now
            update_fields.append('last_seen_at')
    else:
        driver.last_seen_at = now
        update_fields.append('last_seen_at')

    if update_fields:
        update_fields.append('updated_at')
        driver.save(update_fields=update_fields)

    return changed


def _stale_driver_presence_cutoff(timeout_seconds=DRIVER_PRESENCE_TIMEOUT_SECONDS):
    return timezone.now() - timedelta(seconds=int(timeout_seconds))


def _cleanup_stale_driver_connections(*, driver_id=None, timeout_seconds=DRIVER_PRESENCE_TIMEOUT_SECONDS):
    stale_qs = DriverPresenceConnection.objects.filter(
        last_heartbeat_at__lt=_stale_driver_presence_cutoff(timeout_seconds)
    )
    if driver_id is not None:
        stale_qs = stale_qs.filter(driver_id=driver_id)
    stale_qs.delete()


def _driver_presence_group_batches(driver: Driver, payload):
    order_rows = list(
        Order.objects
        .filter(driver_id=driver.id)
        .values('id', 'customer_id', 'shop_owner_id')
    )

    standard_groups = {f'driver_{driver.id}'}
    driver_chat_groups = {driver_driver_chats_group(driver.id)}

    active_shop_ids = list(
        ShopDriver.objects
        .filter(driver=driver, status='active')
        .values_list('shop_owner_id', flat=True)
        .distinct()
    )
    for shop_id in active_shop_ids:
        standard_groups.add(f'shop_orders_{shop_id}')
        driver_chat_groups.add(shop_driver_chats_group(shop_id))

    for order in order_rows:
        standard_groups.add(f'chat_order_{order["id"]}_driver_customer')
        if order['customer_id']:
            standard_groups.add(f'customer_orders_{order["customer_id"]}')
        if order['shop_owner_id']:
            standard_groups.add(f'shop_orders_{order["shop_owner_id"]}')
            driver_chat_groups.add(shop_driver_chats_group(order['shop_owner_id']))

    return {
        'standard_groups': sorted(standard_groups),
        'driver_chat_groups': sorted(driver_chat_groups),
        'data': payload,
    }


def mark_driver_connected(driver_id, channel_name, connection_type='driver_chat'):
    with transaction.atomic():
        driver = Driver.objects.select_for_update().get(id=driver_id)
        _cleanup_stale_driver_connections(driver_id=driver.id)
        connection, _ = DriverPresenceConnection.objects.get_or_create(
            channel_name=channel_name,
            defaults={
                'driver': driver,
                'connection_type': connection_type,
                'last_heartbeat_at': timezone.now(),
            },
        )
        if connection.driver_id != driver.id:
            connection.driver = driver
            connection.connection_type = connection_type
        connection.last_heartbeat_at = timezone.now()
        connection.save(update_fields=['driver', 'connection_type', 'last_heartbeat_at'])
        active_connections_count = DriverPresenceConnection.objects.filter(driver_id=driver.id).count()
        driver.active_connections_count = active_connections_count
        has_connections = active_connections_count > 0
        changed = _apply_driver_presence_state(driver, has_connections)
        return {
            **_driver_presence_payload(driver),
            'changed': changed,
        }


def mark_driver_disconnected(channel_name):
    with transaction.atomic():
        connection = (
            DriverPresenceConnection.objects
            .select_related('driver')
            .filter(channel_name=channel_name)
            .first()
        )
        if not connection:
            return None
        driver = Driver.objects.select_for_update().get(id=connection.driver_id)
        connection.delete()
        _cleanup_stale_driver_connections(driver_id=driver.id)
        active_connections_count = DriverPresenceConnection.objects.filter(driver_id=driver.id).count()
        driver.active_connections_count = active_connections_count
        has_connections = active_connections_count > 0
        changed = _apply_driver_presence_state(driver, has_connections)
        return {
            **_driver_presence_payload(driver),
            'changed': changed,
        }


def touch_driver_presence(channel_name, driver_id=None):
    with transaction.atomic():
        connection = (
            DriverPresenceConnection.objects
            .select_related('driver')
            .filter(channel_name=channel_name)
            .first()
        )
        if not connection:
            return None
        if driver_id is not None and int(connection.driver_id) != int(driver_id):
            return None
        connection.last_heartbeat_at = timezone.now()
        connection.save(update_fields=['last_heartbeat_at'])
        driver = connection.driver
        _cleanup_stale_driver_connections(driver_id=driver.id)
        driver.active_connections_count = DriverPresenceConnection.objects.filter(driver_id=driver.id).count()
        return _driver_presence_payload(driver)


def mark_driver_connection_timed_out(channel_name, timeout_seconds=DRIVER_PRESENCE_TIMEOUT_SECONDS):
    with transaction.atomic():
        connection = (
            DriverPresenceConnection.objects
            .select_related('driver')
            .filter(channel_name=channel_name)
            .first()
        )
        if not connection:
            return None
        last_heartbeat_at = connection.last_heartbeat_at or connection.created_at
        if last_heartbeat_at and last_heartbeat_at >= _stale_driver_presence_cutoff(timeout_seconds):
            return None

        driver = Driver.objects.select_for_update().get(id=connection.driver_id)
        connection.delete()
        _cleanup_stale_driver_connections(driver_id=driver.id, timeout_seconds=timeout_seconds)
        active_connections_count = DriverPresenceConnection.objects.filter(driver_id=driver.id).count()
        driver.active_connections_count = active_connections_count
        changed = _apply_driver_presence_state(driver, active_connections_count > 0)
        return {
            **_driver_presence_payload(driver),
            'changed': changed,
            'timed_out': True,
        }


def get_driver_presence_snapshot(driver_or_id):
    driver = driver_or_id if isinstance(driver_or_id, Driver) else Driver.objects.filter(id=driver_or_id).first()
    if not driver:
        return None
    _cleanup_stale_driver_connections(driver_id=driver.id)
    driver.active_connections_count = DriverPresenceConnection.objects.filter(driver_id=driver.id).count()
    if driver.is_online and driver.active_connections_count == 0:
        _apply_driver_presence_state(driver, False)
        driver.refresh_from_db(fields=['is_online', 'last_seen_at', 'status'])
        driver.active_connections_count = 0
    return _driver_presence_payload(driver)


def broadcast_driver_presence_update(driver_or_id):
    driver = driver_or_id if isinstance(driver_or_id, Driver) else Driver.objects.filter(id=driver_or_id).first()
    if not driver:
        return None
    _cleanup_stale_driver_connections(driver_id=driver.id)
    driver.active_connections_count = DriverPresenceConnection.objects.filter(driver_id=driver.id).count()
    if driver.is_online and driver.active_connections_count == 0:
        _apply_driver_presence_state(driver, False)
    payload = _driver_presence_payload(driver)
    batches = _driver_presence_group_batches(driver, payload)

    for group_name in batches['standard_groups']:
        _group_send(group_name, {'type': 'presence_update', 'data': payload})

    for group_name in batches['driver_chat_groups']:
        _group_send(group_name, _event_envelope('driver_chat.driver_presence_updated', data=payload))
    return payload


def start_call(*, conversation: DriverChatConversation, initiated_by='store'):
    call = DriverChatCall.objects.create(
        conversation=conversation,
        initiated_by=initiated_by,
        status='initiated',
        channel_name=f"driver_chat_room_{conversation.pk}_{timezone.now().strftime('%H%M%S')}",
        metadata={'timeout_seconds': CALL_TIMEOUT_SECONDS},
    )
    payload = {'call': serialize_driver_chat_call(call)}
    publish_driver_chat_event(
        shop_owner_id=conversation.shop_owner_id,
        event_type='driver_chat.call_initiated',
        data=payload,
        conversation=conversation,
        driver=conversation.driver,
    )
    call = update_call_status(call, status_value='ringing')
    _log_sensitive('call_start', conversation_id=conversation.public_id, driver_id=conversation.driver_id, call_id=call.public_id)
    return call


def update_call_status(call: DriverChatCall, *, status_value, reason=None):
    call.status = status_value
    if reason:
        call.reason = reason
    if status_value == 'accepted' and not call.answered_at:
        call.answered_at = timezone.now()
    if status_value in {'ended', 'cancelled', 'rejected', 'missed', 'timeout', 'failed'}:
        if not call.ended_at:
            call.ended_at = timezone.now()
        if call.answered_at and call.ended_at:
            call.duration_seconds = max(0, int((call.ended_at - call.answered_at).total_seconds()))
    call.save(update_fields=['status', 'reason', 'answered_at', 'ended_at', 'duration_seconds', 'updated_at'])
    payload = {'call': serialize_driver_chat_call(call)}
    if reason:
        payload['reason'] = reason
    publish_driver_chat_event(
        shop_owner_id=call.conversation.shop_owner_id,
        event_type=f'driver_chat.call_{status_value}',
        data=payload,
        conversation=call.conversation,
        driver=call.conversation.driver,
    )
    _log_sensitive(f'call_{status_value}', conversation_id=call.conversation.public_id, driver_id=call.conversation.driver_id, call_id=call.public_id, reason=reason)
    return call


def relay_typing_event(*, conversation: DriverChatConversation, sender, is_typing):
    publish_driver_chat_event(
        shop_owner_id=conversation.shop_owner_id,
        event_type='driver_chat.typing',
        data={
            'conversation_id': conversation.public_id,
            'sender': sender,
            'is_typing': bool(is_typing),
        },
        conversation=conversation,
        driver=conversation.driver,
        persist=False,
    )


def relay_webrtc_event(*, conversation: DriverChatConversation, event_type, data):
    publish_driver_chat_event(
        shop_owner_id=conversation.shop_owner_id,
        event_type=event_type,
        data=data,
        conversation=conversation,
        driver=conversation.driver,
        persist=False,
    )
