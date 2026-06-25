import math
from datetime import timedelta
from datetime import timezone as dt_timezone
from functools import lru_cache

from django.conf import settings
from django.db import transaction
from django.utils import timezone
from redis import Redis

from user.utils import resolve_customer_profile_image_url

from ..models import Customer, CustomerPresenceConnection, Order


CUSTOMER_PRESENCE_TIMEOUT_SECONDS = 75
CUSTOMER_PRESENCE_REDIS_TTL_SECONDS = 35
CUSTOMER_PRESENCE_PING_INTERVAL_SECONDS = 20
CUSTOMER_PRESENCE_REDIS_PREFIX = 'zaygo:presence:customer'


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


def get_customer_presence_redis_ttl_seconds():
    raw_value = getattr(settings, 'CUSTOMER_PRESENCE_REDIS_TTL_SECONDS', CUSTOMER_PRESENCE_REDIS_TTL_SECONDS)
    try:
        ttl_seconds = int(raw_value)
    except (TypeError, ValueError):
        ttl_seconds = CUSTOMER_PRESENCE_REDIS_TTL_SECONDS
    return max(ttl_seconds, 5)


def get_customer_presence_ping_interval_seconds():
    raw_value = getattr(settings, 'CUSTOMER_PRESENCE_PING_INTERVAL_SECONDS', CUSTOMER_PRESENCE_PING_INTERVAL_SECONDS)
    try:
        ping_interval = int(raw_value)
    except (TypeError, ValueError):
        ping_interval = CUSTOMER_PRESENCE_PING_INTERVAL_SECONDS
    return max(ping_interval, 5)


def _resolve_presence_redis_location():
    redis_url = str(getattr(settings, 'REDIS_URL', '') or '').strip()
    if redis_url:
        return redis_url

    channel_layers = getattr(settings, 'CHANNEL_LAYERS', {}) or {}
    default_layer = channel_layers.get('default', {}) or {}
    config = default_layer.get('CONFIG', {}) or {}
    hosts = config.get('hosts') or []
    if not hosts:
        return None
    first_host = hosts[0]
    if isinstance(first_host, str):
        return first_host
    if isinstance(first_host, (tuple, list)) and len(first_host) >= 2:
        host = first_host[0] or '127.0.0.1'
        port = int(first_host[1] or 6379)
        return f'redis://{host}:{port}/0'
    return None


@lru_cache(maxsize=1)
def _get_presence_redis_client():
    location = _resolve_presence_redis_location()
    if not location:
        return None
    try:
        client = Redis.from_url(location, decode_responses=True)
        client.ping()
        return client
    except Exception:
        return None


def _presence_redis_enabled():
    return _get_presence_redis_client() is not None


def _customer_presence_connection_key(channel_name):
    return f'{CUSTOMER_PRESENCE_REDIS_PREFIX}:conn:{channel_name}'


def _customer_presence_connection_index_key(channel_name):
    return f'{CUSTOMER_PRESENCE_REDIS_PREFIX}:index:{channel_name}'


def _customer_presence_connections_key(customer_id):
    return f'{CUSTOMER_PRESENCE_REDIS_PREFIX}:connections:{customer_id}'


def format_utc_iso8601(value):
    if not value:
        return None

    if timezone.is_naive(value):
        value = timezone.make_aware(value, dt_timezone.utc)

    value = timezone.localtime(value).replace(microsecond=0)
    return value.isoformat()


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


def _cleanup_stale_customer_connections_redis(customer_id):
    client = _get_presence_redis_client()
    if not client:
        return []

    set_key = _customer_presence_connections_key(customer_id)
    channel_names = list(client.smembers(set_key) or [])
    if not channel_names:
        return []

    pipeline = client.pipeline()
    for channel_name in channel_names:
        pipeline.exists(_customer_presence_connection_key(channel_name))
    exists_flags = pipeline.execute()

    active_channels = []
    stale_channels = []
    for channel_name, exists_flag in zip(channel_names, exists_flags):
        if exists_flag:
            active_channels.append(channel_name)
        else:
            stale_channels.append(channel_name)

    if stale_channels:
        cleanup = client.pipeline()
        cleanup.srem(set_key, *stale_channels)
        for channel_name in stale_channels:
            cleanup.delete(_customer_presence_connection_index_key(channel_name))
        if not active_channels:
            cleanup.delete(set_key)
        cleanup.execute()
    elif active_channels:
        client.expire(set_key, get_customer_presence_redis_ttl_seconds() * 2)

    return active_channels


def _register_customer_presence_redis(customer_id, channel_name):
    client = _get_presence_redis_client()
    if not client:
        return None

    active_before = _cleanup_stale_customer_connections_redis(customer_id)
    ttl_seconds = get_customer_presence_redis_ttl_seconds()
    set_key = _customer_presence_connections_key(customer_id)
    pipeline = client.pipeline()
    pipeline.set(_customer_presence_connection_key(channel_name), str(customer_id), ex=ttl_seconds)
    pipeline.set(_customer_presence_connection_index_key(channel_name), str(customer_id), ex=ttl_seconds * 2)
    pipeline.sadd(set_key, channel_name)
    pipeline.expire(set_key, ttl_seconds * 2)
    pipeline.execute()
    active_after = _cleanup_stale_customer_connections_redis(customer_id)
    return {
        'had_active_connections': bool(active_before),
        'has_active_connections': bool(active_after),
    }


def _unregister_customer_presence_redis(channel_name, customer_id=None):
    client = _get_presence_redis_client()
    if not client:
        return None

    if customer_id is None:
        customer_id = client.get(_customer_presence_connection_index_key(channel_name))
    if not customer_id:
        client.delete(_customer_presence_connection_key(channel_name))
        client.delete(_customer_presence_connection_index_key(channel_name))
        return {
            'customer_id': None,
            'has_active_connections': False,
        }

    set_key = _customer_presence_connections_key(customer_id)
    pipeline = client.pipeline()
    pipeline.delete(_customer_presence_connection_key(channel_name))
    pipeline.delete(_customer_presence_connection_index_key(channel_name))
    pipeline.srem(set_key, channel_name)
    pipeline.execute()
    active_after = _cleanup_stale_customer_connections_redis(customer_id)
    if not active_after:
        client.delete(set_key)
    return {
        'customer_id': int(customer_id),
        'has_active_connections': bool(active_after),
    }


def _touch_customer_presence_redis(channel_name, customer_id=None):
    client = _get_presence_redis_client()
    if not client:
        return None

    stored_customer_id = client.get(_customer_presence_connection_index_key(channel_name))
    if not stored_customer_id:
        return None
    if customer_id is not None and int(stored_customer_id) != int(customer_id):
        return None

    ttl_seconds = get_customer_presence_redis_ttl_seconds()
    set_key = _customer_presence_connections_key(stored_customer_id)
    pipeline = client.pipeline()
    pipeline.expire(_customer_presence_connection_key(channel_name), ttl_seconds)
    pipeline.expire(_customer_presence_connection_index_key(channel_name), ttl_seconds * 2)
    pipeline.sadd(set_key, channel_name)
    pipeline.expire(set_key, ttl_seconds * 2)
    exists_flag, _, _, _ = pipeline.execute()
    if not exists_flag:
        return None
    return int(stored_customer_id)


def _is_customer_online_redis(customer_id):
    client = _get_presence_redis_client()
    if not client:
        return None
    return bool(_cleanup_stale_customer_connections_redis(customer_id))


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
    if _presence_redis_enabled():
        with transaction.atomic():
            customer = Customer.objects.select_for_update().get(id=customer_id)
            redis_state = _register_customer_presence_redis(customer_id, channel_name) or {}
            changed = _apply_customer_presence_state(
                customer,
                redis_state.get('has_active_connections', True),
            )
            return {
                **serialize_customer_presence(customer),
                'changed': changed,
            }

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
    if _presence_redis_enabled():
        redis_state = _unregister_customer_presence_redis(channel_name)
        customer_id = (redis_state or {}).get('customer_id')
        if not customer_id:
            return None
        with transaction.atomic():
            customer = Customer.objects.select_for_update().get(id=customer_id)
            changed = _apply_customer_presence_state(
                customer,
                bool((redis_state or {}).get('has_active_connections')),
            )
            return {
                **serialize_customer_presence(customer),
                'changed': changed,
            }

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
    if _presence_redis_enabled():
        return _touch_customer_presence_redis(channel_name, customer_id)

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
    if _presence_redis_enabled():
        client = _get_presence_redis_client()
        if not client:
            return None
        if client.exists(_customer_presence_connection_key(channel_name)):
            return None
        redis_state = _unregister_customer_presence_redis(channel_name)
        customer_id = (redis_state or {}).get('customer_id')
        if not customer_id:
            return None
        with transaction.atomic():
            customer = Customer.objects.select_for_update().get(id=customer_id)
            changed = _apply_customer_presence_state(
                customer,
                bool((redis_state or {}).get('has_active_connections')),
            )
            return {
                **serialize_customer_presence(customer),
                'changed': changed,
                'timed_out': True,
            }

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
    if _presence_redis_enabled():
        is_online = _is_customer_online_redis(order.customer_id)
        if is_online is not None and order.customer.is_online != is_online:
            _apply_customer_presence_state(order.customer, is_online)
            order.customer.refresh_from_db(fields=['is_online', 'last_seen'])
        return serialize_customer_presence(order.customer, order_id=order.id)

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
