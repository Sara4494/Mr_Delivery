from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.db.models import Prefetch

from .models import ChatMessage, CustomerSupportConversation, CustomerSupportMessage, Order
from .realtime_serializers import (
    SHOP_ORDER_MESSAGES_ATTR,
    SUPPORT_MESSAGES_ATTR,
    CustomerAppRealtimeOnWaySerializer,
    CustomerAppRealtimeOrderHistoryChatEntrySerializer,
    CustomerAppRealtimeOrderHistoryOrderEntrySerializer,
    CustomerAppRealtimeOrderSerializer,
    CustomerAppRealtimeOrderShopEntrySerializer,
    CustomerAppRealtimeSupportShopEntrySerializer,
    get_on_way_sort_key,
    get_order_shop_interaction_at,
    get_order_sort_key,
    get_support_interaction_at,
    is_customer_active_order,
    is_customer_on_way_order,
)


CUSTOMER_APP_REALTIME_SCOPE = 'customer_app_realtime'


ORDER_SHOP_MESSAGES_PREFETCH = Prefetch(
    'messages',
    queryset=ChatMessage.objects.filter(chat_type='shop_customer')
    .select_related(
        'sender_customer',
        'sender_shop_owner',
        'sender_employee',
        'sender_driver',
    )
    .order_by('-created_at'),
    to_attr=SHOP_ORDER_MESSAGES_ATTR,
)

SUPPORT_MESSAGES_PREFETCH = Prefetch(
    'messages',
    queryset=CustomerSupportMessage.objects.select_related(
        'sender_customer',
        'sender_shop_owner',
        'sender_employee',
    ).order_by('-created_at'),
    to_attr=SUPPORT_MESSAGES_ATTR,
)


def customer_app_group_name(customer_id):
    return f'customer_orders_{customer_id}'


def _serializer_context(*, lang=None, scope=None, base_url=None):
    context = {}
    if lang is not None:
        context['lang'] = lang
    if scope is not None:
        context['scope'] = scope
    if base_url:
        context['base_url'] = base_url
    return context


def _order_queryset(customer_id):
    return (
        Order.objects.filter(customer_id=customer_id)
        .select_related('shop_owner', 'driver')
        .prefetch_related(ORDER_SHOP_MESSAGES_PREFETCH)
    )


def _support_queryset(customer_id):
    return (
        CustomerSupportConversation.objects.filter(customer_id=customer_id)
        .select_related('shop_owner', 'customer')
        .prefetch_related(SUPPORT_MESSAGES_PREFETCH)
    )


def _sorted_active_orders(orders):
    return sorted(
        (order for order in orders if is_customer_active_order(order)),
        key=get_order_sort_key,
        reverse=True,
    )


def _sorted_on_way_orders(orders):
    return sorted(
        (order for order in orders if is_customer_on_way_order(order)),
        key=get_on_way_sort_key,
        reverse=True,
    )


def build_orders_snapshot(customer_id, *, lang=None, scope=None, base_url=None, orders=None):
    orders = list(orders) if orders is not None else list(_order_queryset(customer_id))
    results = CustomerAppRealtimeOrderSerializer(
        _sorted_active_orders(orders),
        many=True,
        context=_serializer_context(lang=lang, scope=scope, base_url=base_url),
    ).data
    return {
        'count': len(results),
        'results': results,
    }


def _build_latest_shop_entry(orders, conversations, *, lang=None, scope=None, base_url=None):
    context = _serializer_context(lang=lang, scope=scope, base_url=base_url)
    grouped = {}

    for order in orders:
        if not order.shop_owner_id:
            continue

        candidate = (
            get_order_shop_interaction_at(order),
            CustomerAppRealtimeOrderShopEntrySerializer(order, context=context).data,
        )
        current = grouped.get(order.shop_owner_id)
        if current is None or candidate[0] >= current[0]:
            grouped[order.shop_owner_id] = candidate

    for conversation in conversations:
        if not conversation.shop_owner_id:
            continue

        candidate = (
            get_support_interaction_at(conversation),
            CustomerAppRealtimeSupportShopEntrySerializer(
                conversation,
                context=context,
            ).data,
        )
        current = grouped.get(conversation.shop_owner_id)
        if current is None or candidate[0] >= current[0]:
            grouped[conversation.shop_owner_id] = candidate

    return [
        payload
        for _, payload in sorted(
            grouped.values(),
            key=lambda item: item[0],
            reverse=True,
        )
        if payload is not None
    ]


def build_shops_snapshot(customer_id, *, lang=None, scope=None, base_url=None, orders=None, conversations=None):
    orders = list(orders) if orders is not None else list(_order_queryset(customer_id))
    conversations = (
        list(conversations) if conversations is not None else list(_support_queryset(customer_id))
    )
    results = _build_latest_shop_entry(
        orders,
        conversations,
        lang=lang,
        scope=scope,
        base_url=base_url,
    )
    return {
        'count': len(results),
        'results': results,
    }


def build_on_way_snapshot(customer_id, *, lang=None, scope=None, base_url=None, orders=None):
    orders = list(orders) if orders is not None else list(_order_queryset(customer_id))
    results = CustomerAppRealtimeOnWaySerializer(
        _sorted_on_way_orders(orders),
        many=True,
        context=_serializer_context(lang=lang, scope=scope, base_url=base_url),
    ).data
    return {
        'count': len(results),
        'results': results,
    }


def build_order_history_snapshot(
    customer_id,
    *,
    lang=None,
    scope=None,
    base_url=None,
    orders=None,
    conversations=None,
):
    orders = list(orders) if orders is not None else list(_order_queryset(customer_id))
    conversations = (
        list(conversations) if conversations is not None else list(_support_queryset(customer_id))
    )
    context = _serializer_context(lang=lang, scope=scope, base_url=base_url)
    items = []

    for order in orders:
        items.append(
            (
                order.created_at,
                CustomerAppRealtimeOrderHistoryOrderEntrySerializer(
                    order,
                    context=context,
                ).data,
            )
        )

    for conversation in conversations:
        items.append(
            (
                conversation.created_at,
                CustomerAppRealtimeOrderHistoryChatEntrySerializer(
                    conversation,
                    context=context,
                ).data,
            )
        )

    results = [
        payload
        for _, payload in sorted(
            items,
            key=lambda item: item[0],
            reverse=True,
        )
    ]
    return {
        'count': len(results),
        'results': results,
    }


def build_all_snapshots(customer_id, *, lang=None, scope=None, base_url=None):
    orders = list(_order_queryset(customer_id))
    conversations = list(_support_queryset(customer_id))
    return {
        'orders_snapshot': build_orders_snapshot(
            customer_id,
            lang=lang,
            scope=scope,
            base_url=base_url,
            orders=orders,
        ),
        'shops_snapshot': build_shops_snapshot(
            customer_id,
            lang=lang,
            scope=scope,
            base_url=base_url,
            orders=orders,
            conversations=conversations,
        ),
        'on_way_snapshot': build_on_way_snapshot(
            customer_id,
            lang=lang,
            scope=scope,
            base_url=base_url,
            orders=orders,
        ),
        'order_history_snapshot': build_order_history_snapshot(
            customer_id,
            lang=lang,
            scope=scope,
            base_url=base_url,
            orders=orders,
            conversations=conversations,
        ),
    }


def _shop_event_for_shop(customer_id, shop_owner_id, *, lang=None, scope=None, base_url=None):
    if not shop_owner_id:
        return None

    orders = list(_order_queryset(customer_id).filter(shop_owner_id=shop_owner_id))
    conversations = list(_support_queryset(customer_id).filter(shop_owner_id=shop_owner_id))
    results = _build_latest_shop_entry(
        orders,
        conversations,
        lang=lang,
        scope=scope,
        base_url=base_url,
    )
    if results:
        return {
            'type': 'shop_upsert',
            'data': results[0],
        }
    return {
        'type': 'shop_remove',
        'data': {
            'shop_id': shop_owner_id,
        },
    }


def _lookup_order_targets(order_id):
    order = Order.objects.filter(id=order_id).only('id', 'customer_id', 'shop_owner_id').first()
    if not order:
        return None, None
    return order.customer_id, order.shop_owner_id


def _lookup_support_targets(conversation_id):
    conversation = (
        CustomerSupportConversation.objects.filter(public_id=conversation_id)
        .only('public_id', 'customer_id', 'shop_owner_id')
        .first()
    )
    if not conversation:
        return None, None
    return conversation.customer_id, conversation.shop_owner_id


def build_order_delta_events(
    customer_id,
    order_id,
    *,
    shop_owner_id=None,
    include_order=True,
    include_shop=True,
    include_on_way=True,
    include_history=True,
    lang=None,
    scope=None,
    base_url=None,
):
    order = (
        _order_queryset(customer_id)
        .filter(id=order_id)
        .first()
    )
    if not order:
        return []

    context = _serializer_context(lang=lang, scope=scope, base_url=base_url)
    events = []

    if include_order:
        if is_customer_active_order(order):
            events.append(
                {
                    'type': 'order_upsert',
                    'data': CustomerAppRealtimeOrderSerializer(order, context=context).data,
                }
            )
        else:
            events.append(
                {
                    'type': 'order_remove',
                    'data': {'id': order.id},
                }
            )

    if include_shop:
        events.append(
            _shop_event_for_shop(
                customer_id,
                shop_owner_id or order.shop_owner_id,
                lang=lang,
                scope=scope,
                base_url=base_url,
            )
        )

    if include_on_way:
        if is_customer_on_way_order(order):
            events.append(
                {
                    'type': 'on_way_upsert',
                    'data': CustomerAppRealtimeOnWaySerializer(order, context=context).data,
                }
            )
        else:
            events.append(
                {
                    'type': 'on_way_remove',
                    'data': {'order_id': order.id},
                }
            )

    if include_history:
        events.append(
            {
                'type': 'order_history_entry_upsert',
                'data': CustomerAppRealtimeOrderHistoryOrderEntrySerializer(
                    order,
                    context=context,
                ).data,
            }
        )

    return [event for event in events if event]


def build_order_remove_events(
    customer_id,
    order_id,
    *,
    shop_owner_id=None,
    include_shop=True,
    include_on_way=True,
    include_history=True,
    lang=None,
    scope=None,
    base_url=None,
):
    events = [
        {
            'type': 'order_remove',
            'data': {'id': order_id},
        }
    ]

    if include_shop and shop_owner_id:
        events.append(
            _shop_event_for_shop(
                customer_id,
                shop_owner_id,
                lang=lang,
                scope=scope,
                base_url=base_url,
            )
        )

    if include_on_way:
        events.append(
            {
                'type': 'on_way_remove',
                'data': {'order_id': order_id},
            }
        )

    if include_history:
        events.append(
            {
                'type': 'order_history_entry_remove',
                'data': {
                    'id': f'order_{order_id}',
                    'entry_type': 'order',
                },
            }
        )

    return [event for event in events if event]


def build_support_delta_events(
    customer_id,
    conversation_id,
    *,
    shop_owner_id=None,
    include_shop=True,
    include_history=True,
    lang=None,
    scope=None,
    base_url=None,
):
    conversation = (
        _support_queryset(customer_id)
        .filter(public_id=conversation_id)
        .first()
    )
    if not conversation:
        return []

    context = _serializer_context(lang=lang, scope=scope, base_url=base_url)
    events = []

    if include_shop:
        events.append(
            _shop_event_for_shop(
                customer_id,
                shop_owner_id or conversation.shop_owner_id,
                lang=lang,
                scope=scope,
                base_url=base_url,
            )
        )

    if include_history:
        events.append(
            {
                'type': 'order_history_entry_upsert',
                'data': CustomerAppRealtimeOrderHistoryChatEntrySerializer(
                    conversation,
                    context=context,
                ).data,
            }
        )

    return [event for event in events if event]


def build_support_remove_events(
    customer_id,
    conversation_id,
    *,
    shop_owner_id=None,
    include_shop=True,
    include_history=True,
    lang=None,
    scope=None,
    base_url=None,
):
    events = []

    if include_shop and shop_owner_id:
        events.append(
            _shop_event_for_shop(
                customer_id,
                shop_owner_id,
                lang=lang,
                scope=scope,
                base_url=base_url,
            )
        )

    if include_history:
        events.append(
            {
                'type': 'order_history_entry_remove',
                'data': {
                    'id': conversation_id,
                    'entry_type': 'chat',
                },
            }
        )

    return [event for event in events if event]


async def dispatch_customer_events_async(channel_layer, customer_id, events):
    if not channel_layer or not customer_id:
        return

    group_name = customer_app_group_name(customer_id)
    for event in events or []:
        await channel_layer.group_send(
            group_name,
            {
                'type': event['type'],
                'data': event['data'],
            },
        )


def dispatch_customer_events(customer_id, events):
    channel_layer = get_channel_layer()
    if not channel_layer or not customer_id:
        return

    group_name = customer_app_group_name(customer_id)
    for event in events or []:
        async_to_sync(channel_layer.group_send)(
            group_name,
            {
                'type': event['type'],
                'data': event['data'],
            },
        )


def broadcast_customer_order_changed(
    order_id,
    *,
    customer_id=None,
    shop_owner_id=None,
    include_order=True,
    include_shop=True,
    include_on_way=True,
    include_history=True,
    lang=None,
    scope=None,
    base_url=None,
):
    resolved_customer_id, resolved_shop_owner_id = _lookup_order_targets(order_id)
    target_customer_id = customer_id or resolved_customer_id
    target_shop_owner_id = shop_owner_id or resolved_shop_owner_id
    if not target_customer_id:
        return

    dispatch_customer_events(
        target_customer_id,
        build_order_delta_events(
            target_customer_id,
            order_id,
            shop_owner_id=target_shop_owner_id,
            include_order=include_order,
            include_shop=include_shop,
            include_on_way=include_on_way,
            include_history=include_history,
            lang=lang,
            scope=scope,
            base_url=base_url,
        ),
    )


def broadcast_customer_order_removed(
    customer_id,
    order_id,
    *,
    shop_owner_id=None,
    include_shop=True,
    include_on_way=True,
    include_history=True,
    lang=None,
    scope=None,
    base_url=None,
):
    if not customer_id:
        return

    dispatch_customer_events(
        customer_id,
        build_order_remove_events(
            customer_id,
            order_id,
            shop_owner_id=shop_owner_id,
            include_shop=include_shop,
            include_on_way=include_on_way,
            include_history=include_history,
            lang=lang,
            scope=scope,
            base_url=base_url,
        ),
    )


def broadcast_customer_support_changed(
    conversation_id,
    *,
    customer_id=None,
    shop_owner_id=None,
    include_shop=True,
    include_history=True,
    lang=None,
    scope=None,
    base_url=None,
):
    resolved_customer_id, resolved_shop_owner_id = _lookup_support_targets(conversation_id)
    target_customer_id = customer_id or resolved_customer_id
    target_shop_owner_id = shop_owner_id or resolved_shop_owner_id
    if not target_customer_id:
        return

    dispatch_customer_events(
        target_customer_id,
        build_support_delta_events(
            target_customer_id,
            conversation_id,
            shop_owner_id=target_shop_owner_id,
            include_shop=include_shop,
            include_history=include_history,
            lang=lang,
            scope=scope,
            base_url=base_url,
        ),
    )


def broadcast_customer_support_removed(
    customer_id,
    conversation_id,
    *,
    shop_owner_id=None,
    include_shop=True,
    include_history=True,
    lang=None,
    scope=None,
    base_url=None,
):
    if not customer_id:
        return

    dispatch_customer_events(
        customer_id,
        build_support_remove_events(
            customer_id,
            conversation_id,
            shop_owner_id=shop_owner_id,
            include_shop=include_shop,
            include_history=include_history,
            lang=lang,
            scope=scope,
            base_url=base_url,
        ),
    )
