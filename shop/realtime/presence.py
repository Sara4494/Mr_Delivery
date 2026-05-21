import math
from datetime import timedelta
from datetime import timezone as dt_timezone

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from user.utils import resolve_customer_profile_image_url

from ..models import Customer, CustomerPresenceConnection, Order


def get_customer_phone_reveal_delay_seconds():
    raw_value = getattr(settings, 'CUSTOMER_PHONE_REVEAL_DELAY_SECONDS', 120)
    try:
        delay_seconds = int(raw_value)
    except (TypeError, ValueError):
        delay_seconds = 120
    return max(delay_seconds, 0)


def format_utc_iso8601(value):
    if not value:
        return None

    if timezone.is_naive(value):
        value = timezone.make_aware(value, dt_timezone.utc)

    value = value.astimezone(dt_timezone.utc).replace(microsecond=0)
    return value.isoformat().replace('+00:00', 'Z')


def _apply_customer_presence_state(customer, is_online):
    changed = bool(customer.is_online) != bool(is_online)
    update_fields = []

    if changed:
        customer.is_online = bool(is_online)
        update_fields.append('is_online')

    if changed or customer.last_seen is None:
        customer.last_seen = timezone.now()
        update_fields.append('last_seen')

    if update_fields:
        update_fields.append('updated_at')
        customer.save(update_fields=update_fields)

    return changed


def serialize_customer_presence(customer, order_id=None):
    now = timezone.now()
    delay_seconds = get_customer_phone_reveal_delay_seconds()
    offline_since = customer.last_seen if not bool(customer.is_online) else None
    elapsed_seconds = 0.0
    if offline_since:
        elapsed_seconds = max(0.0, (now - offline_since).total_seconds())
    can_show_customer_phone = bool(
        customer.phone_number
        and not bool(customer.is_online)
        and elapsed_seconds >= delay_seconds
    )
    remaining_seconds = (
        delay_seconds
        if bool(customer.is_online)
        else max(0, int(math.ceil(delay_seconds - elapsed_seconds)))
    )
    phone_available_at = (
        offline_since + timedelta(seconds=delay_seconds)
        if offline_since
        else None
    )

    payload = {
        'customer_id': customer.id,
        'is_online': bool(customer.is_online),
        'customer_online_status': 'online' if bool(customer.is_online) else 'offline',
        'last_seen': format_utc_iso8601(customer.last_seen),
        'customer_last_seen': format_utc_iso8601(customer.last_seen),
        'offline_since': format_utc_iso8601(offline_since),
        'server_time': format_utc_iso8601(now),
        'phone_reveal_delay_seconds': delay_seconds,
        'phone_available_at': format_utc_iso8601(phone_available_at),
        'can_show_customer_phone': can_show_customer_phone,
        'customer_phone': customer.phone_number if can_show_customer_phone else None,
        'remaining_seconds': remaining_seconds,
        'profile_image_url': resolve_customer_profile_image_url(customer),
    }
    if order_id is not None:
        payload['order_id'] = order_id
    return payload


def mark_customer_websocket_connected(customer_id, channel_name, connection_type='websocket'):
    with transaction.atomic():
        customer = Customer.objects.select_for_update().get(id=customer_id)
        CustomerPresenceConnection.objects.get_or_create(
            channel_name=channel_name,
            defaults={
                'customer': customer,
                'connection_type': connection_type,
            },
        )
        has_connections = CustomerPresenceConnection.objects.filter(customer_id=customer_id).exists()
        changed = _apply_customer_presence_state(customer, has_connections)
        return {
            **serialize_customer_presence(customer),
            'changed': changed,
        }


def mark_customer_websocket_disconnected(channel_name):
    with transaction.atomic():
        connection = (
            CustomerPresenceConnection.objects
            .select_related('customer')
            .filter(channel_name=channel_name)
            .first()
        )
        if not connection:
            return None

        customer = Customer.objects.select_for_update().get(id=connection.customer_id)
        connection.delete()
        has_connections = CustomerPresenceConnection.objects.filter(customer_id=customer.id).exists()
        changed = _apply_customer_presence_state(customer, has_connections)
        return {
            **serialize_customer_presence(customer),
            'changed': changed,
        }


def get_order_customer_presence_snapshot(order_id):
    order = Order.objects.select_related('customer').filter(id=order_id).first()
    if not order or not order.customer_id:
        return None
    return serialize_customer_presence(order.customer, order_id=order.id)


def build_customer_presence_broadcast_batches(customer_id, is_online, last_seen):
    customer = Customer.objects.filter(id=customer_id).first()
    if not customer:
        return []

    orders = list(
        Order.objects
        .filter(customer_id=customer_id)
        .values('id', 'shop_owner_id', 'driver_id')
    )

    batches = []
    for order in orders:
        payload = serialize_customer_presence(customer, order_id=order['id'])
        group_names = {
            f'chat_order_{order["id"]}_shop_customer',
            f'customer_orders_{customer_id}',
        }

        if order['shop_owner_id']:
            group_names.add(f'shop_orders_{order["shop_owner_id"]}')

        if order['driver_id']:
            group_names.add(f'chat_order_{order["id"]}_driver_customer')
            group_names.add(f'driver_{order["driver_id"]}')

        batches.append({
            'group_names': list(group_names),
            'data': payload,
        })

    return batches
