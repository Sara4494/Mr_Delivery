from datetime import timezone as dt_timezone

from django.db import transaction
from django.utils import timezone

from user.utils import resolve_customer_profile_image_url

from ..models import Customer, CustomerPresenceConnection, Order


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
    payload = {
        'customer_id': customer.id,
        'is_online': bool(customer.is_online),
        'last_seen': format_utc_iso8601(customer.last_seen),
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
    orders = list(
        Order.objects
        .filter(customer_id=customer_id)
        .values('id', 'shop_owner_id', 'driver_id')
    )

    batches = []
    for order in orders:
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
            'data': {
                'order_id': order['id'],
                'customer_id': customer_id,
                'is_online': bool(is_online),
                'last_seen': last_seen,
            },
        })

    return batches
