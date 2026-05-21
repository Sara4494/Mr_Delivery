import math
from datetime import timedelta
from datetime import timezone as dt_timezone

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from user.utils import resolve_customer_profile_image_url

from ..models import Customer, CustomerPresenceConnection, Order


CUSTOMER_PRESENCE_TIMEOUT_SECONDS = 75


def get_customer_phone_reveal_delay_seconds():
    raw_value = getattr(settings, 'CUSTOMER_PHONE_REVEAL_DELAY_SECONDS', 120)
    try:
        delay_seconds = int(raw_value)
    except (TypeError, ValueError):
        delay_seconds = 120
    return max(delay_seconds, 0)


def get_customer_presence_timeout_seconds():
    raw_value = getattr(settings, 'CUSTOMER_PRESENCE_TIMEOUT_SECONDS', CUSTOMER_PRESENCE_TIMEOUT_SECONDS)
    try:
        timeout_seconds = int(raw_value)
    except (TypeError, ValueError):
        timeout_seconds = CUSTOMER_PRESENCE_TIMEOUT_SECONDS
    return max(timeout_seconds, 15)


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


def _stale_customer_presence_cutoff(timeout_seconds=None):
    return timezone.now() - timedelta(seconds=int(timeout_seconds or get_customer_presence_timeout_seconds()))


def _cleanup_stale_customer_connections(*, customer_id=None, timeout_seconds=None):
    stale_qs = CustomerPresenceConnection.objects.filter(
        last_heartbeat_at__lt=_stale_customer_presence_cutoff(timeout_seconds)
    )
    if customer_id is not None:
        stale_qs = stale_qs.filter(customer_id=customer_id)
    stale_qs.delete()


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
        _cleanup_stale_customer_connections(customer_id=customer.id)
        connection, _ = CustomerPresenceConnection.objects.get_or_create(
            channel_name=channel_name,
            defaults={
                'customer': customer,
                'connection_type': connection_type,
                'last_heartbeat_at': timezone.now(),
            },
        )
        if connection.customer_id != customer.id:
            connection.customer = customer
            connection.connection_type = connection_type
        connection.last_heartbeat_at = timezone.now()
        connection.save(update_fields=['customer', 'connection_type', 'last_heartbeat_at'])
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
        _cleanup_stale_customer_connections(customer_id=customer.id)
        has_connections = CustomerPresenceConnection.objects.filter(customer_id=customer.id).exists()
        changed = _apply_customer_presence_state(customer, has_connections)
        return {
            **serialize_customer_presence(customer),
            'changed': changed,
        }


def touch_customer_presence(channel_name, customer_id=None):
    with transaction.atomic():
        connection = (
            CustomerPresenceConnection.objects
            .select_related('customer')
            .filter(channel_name=channel_name)
            .first()
        )
        if not connection:
            return None
        if customer_id is not None and int(connection.customer_id) != int(customer_id):
            return None
        connection.last_heartbeat_at = timezone.now()
        connection.save(update_fields=['last_heartbeat_at'])
        customer = connection.customer
        _cleanup_stale_customer_connections(customer_id=customer.id)
        has_connections = CustomerPresenceConnection.objects.filter(customer_id=customer.id).exists()
        if customer.is_online != has_connections:
            _apply_customer_presence_state(customer, has_connections)
            customer.refresh_from_db(fields=['is_online', 'last_seen'])
        return serialize_customer_presence(customer)


def mark_customer_connection_timed_out(channel_name, timeout_seconds=None):
    timeout_seconds = timeout_seconds or get_customer_presence_timeout_seconds()
    with transaction.atomic():
        connection = (
            CustomerPresenceConnection.objects
            .select_related('customer')
            .filter(channel_name=channel_name)
            .first()
        )
        if not connection:
            return None
        last_heartbeat_at = connection.last_heartbeat_at or connection.created_at
        if last_heartbeat_at and last_heartbeat_at >= _stale_customer_presence_cutoff(timeout_seconds):
            return None

        customer = Customer.objects.select_for_update().get(id=connection.customer_id)
        connection.delete()
        _cleanup_stale_customer_connections(customer_id=customer.id, timeout_seconds=timeout_seconds)
        has_connections = CustomerPresenceConnection.objects.filter(customer_id=customer.id).exists()
        changed = _apply_customer_presence_state(customer, has_connections)
        return {
            **serialize_customer_presence(customer),
            'changed': changed,
            'timed_out': True,
        }


def get_order_customer_presence_snapshot(order_id):
    order = Order.objects.select_related('customer').filter(id=order_id).first()
    if not order or not order.customer_id:
        return None
    _cleanup_stale_customer_connections(customer_id=order.customer_id)
    has_connections = CustomerPresenceConnection.objects.filter(customer_id=order.customer_id).exists()
    if order.customer.is_online != has_connections:
        _apply_customer_presence_state(order.customer, has_connections)
        order.customer.refresh_from_db(fields=['is_online', 'last_seen'])
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
