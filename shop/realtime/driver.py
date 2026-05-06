import json

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.utils import timezone
from django.db.models import Q

from user.utils import build_absolute_file_url, resolve_base_url, resolve_customer_profile_image_url

from ..models import Driver, DriverOrderRejection, Order, ShopDriver
from ..fcm.service import send_driver_new_order_notification, send_driver_order_update_notification
from .presence import format_utc_iso8601


DRIVER_AVAILABLE_ORDER_STATUSES = frozenset({'confirmed', 'preparing'})
DRIVER_ASSIGNED_ORDER_STATUSES = frozenset({'confirmed', 'preparing', 'on_way'})


def _to_float_or_none(value):
    try:
        if value in (None, ''):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _parse_order_items(items_value):
    parsed_items = items_value
    if isinstance(items_value, str):
        try:
            parsed_items = json.loads(items_value)
        except (TypeError, ValueError):
            parsed_items = [items_value]

    if not isinstance(parsed_items, list):
        parsed_items = [parsed_items]

    results = []
    for index, item in enumerate(parsed_items, start=1):
        if isinstance(item, dict):
            name = str(
                item.get('name')
                or item.get('title')
                or item.get('product_name')
                or item.get('item_name')
                or f'بند {index}'
            ).strip()
            quantity = item.get('quantity', item.get('qty', item.get('count', 1)))
            try:
                quantity = int(float(quantity))
            except (TypeError, ValueError):
                quantity = 1
            quantity = max(quantity, 1)

        else:
            name = str(item or '').strip()
            if not name:
                continue
            quantity = 1

        results.append({
            'name': name,
            'quantity': quantity,
        })

    return results


def _build_branch_label(shop_owner):
    description = str(getattr(shop_owner, 'description', '') or '').strip()
    if description:
        return description

    category = getattr(shop_owner, 'shop_category', None)
    if category and getattr(category, 'name', None):
        return category.name

    phone_number = str(getattr(shop_owner, 'phone_number', '') or '').strip()
    if phone_number:
        return phone_number

    return getattr(shop_owner, 'shop_number', None)


def _build_address_text(order):
    raw_address = str(getattr(order, 'address', '') or '').strip()
    if raw_address:
        return raw_address

    delivery_address = getattr(order, 'delivery_address', None)
    if not delivery_address:
        return ''

    parts = [
        str(delivery_address.full_address or '').strip(),
        str(delivery_address.city or '').strip(),
        str(delivery_address.area or '').strip(),
        str(delivery_address.street_name or '').strip(),
    ]
    return next((part for part in parts if part), '')


def _build_payment_method_payload(order):
    method_map = dict(getattr(Order, 'PAYMENT_METHOD_CHOICES', []))
    return {
        'code': order.payment_method,
        'label': method_map.get(order.payment_method, order.payment_method),
    }


def _build_delivery_address_payload(order):
    delivery_address = getattr(order, 'delivery_address', None)
    if not delivery_address:
        return {
            'id': None,
            'text': _build_address_text(order),
            'latitude': None,
            'longitude': None,
            'landmark': None,
            'city': None,
            'area': None,
            'street_name': None,
            'building_number': None,
            'floor': None,
            'apartment': None,
            'notes': None,
        }

    return {
        'id': delivery_address.id,
        'text': _build_address_text(order),
        'latitude': _to_float_or_none(delivery_address.latitude),
        'longitude': _to_float_or_none(delivery_address.longitude),
        'landmark': delivery_address.landmark,
        'city': delivery_address.city,
        'area': delivery_address.area,
        'street_name': delivery_address.street_name,
        'building_number': delivery_address.building_number,
        'floor': delivery_address.floor,
        'apartment': delivery_address.apartment,
        'notes': delivery_address.notes,
    }


def _build_invoice_payload(order):
    items = _parse_order_items(order.items)
    collection_amount = _to_float_or_none(order.total_amount) or 0.0
    delivery_fee = _to_float_or_none(order.delivery_fee) or 0.0
    subtotal = round(max(collection_amount - delivery_fee, 0.0), 2)
    return {
        'items': items,
        'subtotal': subtotal,
        'delivery_fee': delivery_fee,
        'total': collection_amount,
    }


def normalize_driver_status(order):
    assigned_driver_id = get_assigned_driver_id(order)
    if order.status == 'cancelled':
        return 'cancelled'
    if assigned_driver_id:
        if not has_driver_accepted(order):
            return 'pending_acceptance'
        if order.status == 'on_way':
            return 'in_delivery'
        if order.status in {'confirmed', 'preparing'}:
            return 'assigned'
        if order.status in DRIVER_ASSIGNED_ORDER_STATUSES:
            return 'assigned'
    if assigned_driver_id is None and order.status in DRIVER_AVAILABLE_ORDER_STATUSES:
        return 'pending'
    return order.status


def get_assigned_driver_id(order):
    assigned_driver_id = getattr(order, 'assigned_driver_id', None)
    if assigned_driver_id is not None:
        return assigned_driver_id

    driver_id = getattr(order, 'driver_id', None)
    if driver_id is not None:
        return driver_id

    driver = getattr(order, 'driver', None)
    return getattr(driver, 'id', None)


def has_driver_accepted(order):
    return getattr(order, 'driver_accepted_at', None) is not None


def is_available_order(order):
    if order.status not in DRIVER_AVAILABLE_ORDER_STATUSES:
        return False
    if get_assigned_driver_id(order) is None:
        return True
    return not has_driver_accepted(order)


def is_available_order_for_driver(driver, order):
    assigned_driver_id = get_assigned_driver_id(order)
    if order.status not in DRIVER_AVAILABLE_ORDER_STATUSES or has_driver_accepted(order):
        return False
    if assigned_driver_id is None:
        return True
    return assigned_driver_id == getattr(driver, 'id', None)


def is_assigned_order(order):
    return (
        get_assigned_driver_id(order) is not None
        and has_driver_accepted(order)
        and order.status in DRIVER_ASSIGNED_ORDER_STATUSES
    )


def is_assigned_order_for_driver(driver, order):
    return get_assigned_driver_id(order) == getattr(driver, 'id', None) and is_assigned_order(order)


def build_driver_order_payload(order, *, request=None, scope=None, base_url=None):
    base_url = resolve_base_url(request=request, scope=scope, base_url=base_url)
    customer = getattr(order, 'customer', None)
    shop_owner = getattr(order, 'shop_owner', None)
    conversation_id = f'order_{order.id}_driver_customer'

    return {
        'order_id': order.id,
        'order_number': order.order_number,
        'status': order.status,
        'driver_status': normalize_driver_status(order),
        'assigned_driver_id': get_assigned_driver_id(order),
        'accepted_at': format_utc_iso8601(getattr(order, 'driver_accepted_at', None)),
        'assigned_at': format_utc_iso8601(getattr(order, 'driver_assigned_at', None)),
        'shop': {
            'id': getattr(shop_owner, 'id', None),
            'name': getattr(shop_owner, 'shop_name', None),
            'logo_url': build_absolute_file_url(
                getattr(shop_owner, 'profile_image', None),
                request=request,
                scope=scope,
                base_url=base_url,
            ),
            'branch_label': _build_branch_label(shop_owner) if shop_owner else None,
        },
        'customer': {
            'id': getattr(customer, 'id', None),
            'name': getattr(customer, 'name', None),
            'phone_number': getattr(customer, 'phone_number', None),
            'profile_image_url': resolve_customer_profile_image_url(
                customer,
                request=request,
                scope=scope,
                base_url=base_url,
            ),
            'is_online': bool(getattr(customer, 'is_online', False)),
            'last_seen': format_utc_iso8601(getattr(customer, 'last_seen', None)),
        },
        'delivery_address': _build_delivery_address_payload(order),
        'distance_km': None,
        'payment_method': _build_payment_method_payload(order),
        'collection_amount': _to_float_or_none(order.total_amount) or 0.0,
        'invoice': _build_invoice_payload(order),
        'chat': {
            'conversation_id': conversation_id,
            'chat_type': 'driver_customer',
            'can_open': has_driver_accepted(order),
            'ws_path': f'/ws/chat/order/{order.id}/?chat_type=driver_customer',
        },
        'transfer': {
            'can_transfer': has_driver_accepted(order),
        },
        'timestamps': {
            'created_at': format_utc_iso8601(order.created_at),
            'updated_at': format_utc_iso8601(order.updated_at),
            'accepted_at': format_utc_iso8601(getattr(order, 'driver_accepted_at', None)),
            'assigned_at': format_utc_iso8601(getattr(order, 'driver_assigned_at', None)),
            'delivered_at': format_utc_iso8601(getattr(order, 'delivered_at', None)),
        },
    }


def get_shop_active_driver_ids(shop_owner_id):
    return list(
        ShopDriver.objects.filter(shop_owner_id=shop_owner_id, status='active')
        .values_list('driver_id', flat=True)
        .distinct()
    )


def driver_can_receive_new_orders(driver):
    if not driver:
        return False
    snapshot = driver.get_availability_snapshot()
    return bool(snapshot.get('can_receive_orders'))


def get_shop_receiving_driver_ids(shop_owner_id):
    drivers = list(
        Driver.objects.filter(
            id__in=ShopDriver.objects.filter(
                shop_owner_id=shop_owner_id,
                status='active',
            ).values_list('driver_id', flat=True),
        ).distinct()
    )
    return [driver.id for driver in drivers if driver_can_receive_new_orders(driver)]


def get_available_orders_queryset(driver):
    availability_filter = Q(driver=driver, driver_accepted_at__isnull=True)
    if driver_can_receive_new_orders(driver):
        availability_filter |= Q(driver__isnull=True, driver_accepted_at__isnull=True)

    return (
        Order.objects
        .filter(
            shop_owner__shop_drivers__driver=driver,
            shop_owner__shop_drivers__status='active',
            status__in=DRIVER_AVAILABLE_ORDER_STATUSES,
        )
        .filter(
            availability_filter
        )
        .exclude(driver_rejections__driver=driver)
        .select_related('shop_owner', 'shop_owner__shop_category', 'customer', 'delivery_address')
        .distinct()
        .order_by('-updated_at', '-created_at')
    )


def get_assigned_orders_queryset(driver):
    return (
        Order.objects
        .filter(driver=driver, driver_accepted_at__isnull=False, status__in=DRIVER_ASSIGNED_ORDER_STATUSES)
        .select_related('shop_owner', 'shop_owner__shop_category', 'customer', 'delivery_address')
        .order_by('-updated_at', '-created_at')
    )


def list_available_orders_payloads(driver, *, request=None, scope=None, base_url=None):
    return [
        build_driver_order_payload(order, request=request, scope=scope, base_url=base_url)
        for order in get_available_orders_queryset(driver)
    ]


def list_assigned_orders_payloads(driver, *, request=None, scope=None, base_url=None):
    return [
        build_driver_order_payload(order, request=request, scope=scope, base_url=base_url)
        for order in get_assigned_orders_queryset(driver)
    ]


def build_driver_snapshot_events(driver, *, request=None, scope=None, base_url=None):
    sent_at = format_utc_iso8601(timezone.now())
    return [
        {
            'type': 'driver.available_orders.snapshot',
            'sent_at': sent_at,
            'data': {
                'results': list_available_orders_payloads(
                    driver,
                    request=request,
                    scope=scope,
                    base_url=base_url,
                ),
            },
        },
        {
            'type': 'driver.assigned_orders.snapshot',
            'sent_at': sent_at,
            'data': {
                'results': list_assigned_orders_payloads(
                    driver,
                    request=request,
                    scope=scope,
                    base_url=base_url,
                ),
            },
        },
    ]


def _send_driver_event(driver_id, event_type, data):
    channel_layer = get_channel_layer()
    if not channel_layer or not driver_id:
        return
    async_to_sync(channel_layer.group_send)(
        f'driver_{driver_id}',
        {
            'type': 'driver_realtime_event',
            'payload': {
                'type': event_type,
                'sent_at': format_utc_iso8601(timezone.now()),
                'data': data,
            },
        },
    )


def emit_available_order_upsert(driver_id, order_payload):
    _send_driver_event(driver_id, 'driver.available_orders.upsert', {'order': order_payload})


def emit_available_order_remove(driver_id, order_id, reason):
    _send_driver_event(driver_id, 'driver.available_orders.remove', {'order_id': order_id, 'reason': reason})


def emit_assigned_order_upsert(driver_id, order_payload):
    _send_driver_event(driver_id, 'driver.assigned_orders.upsert', {'order': order_payload})


def emit_assigned_order_remove(driver_id, order_id, reason):
    _send_driver_event(driver_id, 'driver.assigned_orders.remove', {'order_id': order_id, 'reason': reason})


def emit_order_updated(driver_id, order_payload):
    _send_driver_event(driver_id, 'driver.order.updated', {'order': order_payload})


def emit_order_accepted(driver_id, order_payload):
    _send_driver_event(driver_id, 'driver.order.accepted', {'order': order_payload})


def emit_order_rejected(driver_id, order_id, reason='rejected_by_driver'):
    _send_driver_event(driver_id, 'driver.order.rejected', {'order_id': order_id, 'reason': reason})


def emit_order_transferred(
    driver_id,
    order_id,
    reason_key=None,
    note=None,
    *,
    old_driver_id=None,
    new_driver_id=None,
    transferred_by=None,
    status='transferred',
):
    data = {
        'order_id': order_id,
        'reason_key': reason_key,
        'note': note,
    }
    if old_driver_id is not None:
        data['old_driver_id'] = old_driver_id
    if new_driver_id is not None:
        data['new_driver_id'] = new_driver_id
    if transferred_by is not None:
        data['transferred_by'] = transferred_by
    if status is not None:
        data['status'] = status
    _send_driver_event(driver_id, 'driver.order.transferred', data)


def emit_order_transfer_requested(
    driver_id,
    order_id,
    *,
    requested_by_driver_id,
    reason_key=None,
    note=None,
    status='pending_store_approval',
):
    _send_driver_event(
        driver_id,
        'driver.order.transfer_requested',
        {
            'order_id': order_id,
            'requested_by_driver_id': requested_by_driver_id,
            'reason_key': reason_key,
            'note': note,
            'status': status,
        },
    )


def emit_order_cancelled(driver_id, order_id):
    _send_driver_event(driver_id, 'driver.order.cancelled', {'order_id': order_id})


def upsert_available_order_for_all(order, *, request=None, scope=None, base_url=None, exclude_driver_ids=None):
    exclude_driver_ids = set(exclude_driver_ids or [])
    order_payload = build_driver_order_payload(order, request=request, scope=scope, base_url=base_url)
    target_driver_ids = (
        [get_assigned_driver_id(order)]
        if get_assigned_driver_id(order) and not has_driver_accepted(order)
        else get_shop_receiving_driver_ids(order.shop_owner_id)
    )
    for driver_id in target_driver_ids:
        if driver_id in exclude_driver_ids:
            continue
        emit_available_order_upsert(driver_id, order_payload)


def push_available_order_for_all(order, *, request=None, scope=None, base_url=None, exclude_driver_ids=None):
    exclude_driver_ids = set(exclude_driver_ids or [])
    target_driver_ids = (
        [get_assigned_driver_id(order)]
        if get_assigned_driver_id(order) and not has_driver_accepted(order)
        else get_shop_receiving_driver_ids(order.shop_owner_id)
    )
    drivers = Driver.objects.filter(id__in=[driver_id for driver_id in target_driver_ids if driver_id not in exclude_driver_ids])
    for driver in drivers:
        try:
            send_driver_new_order_notification(driver, order, request=request, scope=scope, base_url=base_url)
        except Exception:
            continue


def remove_available_order_for_all(order, reason, *, driver_ids=None):
    target_driver_ids = driver_ids or get_shop_active_driver_ids(order.shop_owner_id)
    for driver_id in target_driver_ids:
        emit_available_order_remove(driver_id, order.id, reason)


def record_driver_rejection(order, driver, reason=''):
    DriverOrderRejection.objects.update_or_create(
        order=order,
        driver=driver,
        defaults={'reason': str(reason or '').strip() or None},
    )


def clear_driver_rejection(order, driver):
    DriverOrderRejection.objects.filter(order=order, driver=driver).delete()


def clear_all_driver_rejections(order):
    DriverOrderRejection.objects.filter(order=order).delete()


def is_driver_eligible_for_available_order(driver, order):
    return driver_can_receive_new_orders(driver) and ShopDriver.objects.filter(
        shop_owner_id=order.shop_owner_id,
        driver=driver,
        status='active',
    ).exists()


def get_available_order_for_driver(driver, order_id, *, lock=False):
    queryset = get_available_orders_queryset(driver).filter(id=order_id)
    if lock:
        queryset = queryset.select_for_update()
    return queryset.first()


def get_driver_order_unavailable_reason(driver, order):
    if not order:
        return 'no_longer_available'
    if order.status == 'cancelled':
        return 'cancelled'

    assigned_driver_id = get_assigned_driver_id(order)
    driver_id = getattr(driver, 'id', None)
    if assigned_driver_id and assigned_driver_id != driver_id:
        if has_driver_accepted(order):
            return 'accepted_by_other_driver'
        return 'transferred_to_other_driver'

    if order.status not in DRIVER_AVAILABLE_ORDER_STATUSES and not is_assigned_order_for_driver(driver, order):
        return 'no_longer_available'

    return 'no_longer_available'


def sync_unavailable_order_for_driver(driver, order_id, *, order=None):
    reason = get_driver_order_unavailable_reason(driver, order)
    driver_id = getattr(driver, 'id', None)
    emit_available_order_remove(driver_id, order_id, reason)
    emit_assigned_order_remove(driver_id, order_id, reason)
    return reason


def sync_driver_order_state(
    order,
    *,
    previous_status=None,
    previous_driver_id=None,
    previous_driver_accepted_at=None,
    request=None,
    scope=None,
    base_url=None,
):
    current_is_available = is_available_order(order)
    current_is_assigned = is_assigned_order(order)
    was_available = previous_driver_id is None and previous_status in DRIVER_AVAILABLE_ORDER_STATUSES

    if current_is_assigned:
        remove_available_order_for_all(order, 'assigned_to_driver')
        payload = build_driver_order_payload(order, request=request, scope=scope, base_url=base_url)
        emit_assigned_order_upsert(order.driver_id, payload)
        emit_order_updated(order.driver_id, payload)
        if order.driver_id:
            try:
                send_driver_order_update_notification(
                    order.driver,
                    order,
                    update_kind='assigned_order_update',
                    body=f'تم تحديث الطلب #{order.order_number}.',
                    request=request,
                    scope=scope,
                    base_url=base_url,
                )
            except Exception:
                pass
        if previous_driver_id and previous_driver_id != order.driver_id:
            emit_assigned_order_remove(previous_driver_id, order.id, 'reassigned_to_another_driver')
        return

    if previous_driver_id:
        removal_reason = 'cancelled' if order.status == 'cancelled' else 'removed_from_driver'
        if previous_driver_accepted_at is not None:
            emit_assigned_order_remove(previous_driver_id, order.id, removal_reason)
        else:
            emit_available_order_remove(previous_driver_id, order.id, removal_reason)
        if order.status == 'cancelled':
            emit_order_cancelled(previous_driver_id, order.id)

    if current_is_available:
        should_push_new_order = previous_driver_id is not None or not was_available
        if previous_driver_id is not None or not was_available:
            clear_all_driver_rejections(order)
        assigned_driver_id = get_assigned_driver_id(order)
        if assigned_driver_id and not has_driver_accepted(order):
            other_driver_ids = [driver_id for driver_id in get_shop_active_driver_ids(order.shop_owner_id) if driver_id != assigned_driver_id]
            if previous_driver_accepted_at is None and previous_driver_id in other_driver_ids:
                other_driver_ids.remove(previous_driver_id)
            if other_driver_ids:
                remove_available_order_for_all(order, 'reserved_for_other_driver', driver_ids=other_driver_ids)
        upsert_available_order_for_all(order, request=request, scope=scope, base_url=base_url)
        if should_push_new_order:
            push_available_order_for_all(order, request=request, scope=scope, base_url=base_url)
        return
    removal_reason = 'cancelled' if order.status == 'cancelled' else 'unavailable'
    remove_available_order_for_all(order, removal_reason)
    if previous_driver_id and order.status == 'cancelled':
        previous_driver = Driver.objects.filter(id=previous_driver_id).first()
        if previous_driver:
            try:
                send_driver_order_update_notification(
                    previous_driver,
                    order,
                    update_kind='order_cancelled',
                    body=f'تم إلغاء الطلب #{order.order_number}.',
                    request=request,
                    scope=scope,
                    base_url=base_url,
                )
            except Exception:
                pass
