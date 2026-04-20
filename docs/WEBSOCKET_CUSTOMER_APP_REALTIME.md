# Customer App Realtime Channel

## Endpoint

Canonical route:

```text
/ws/customer/app/{customer_id}/?token=<JWT>&lang=ar
```

Compatibility alias:

```text
/ws/orders/customer/{customer_id}/?token=<JWT>&lang=ar
```

Rules:

- `token` is mandatory.
- The authenticated token user must be a `customer`.
- `customer_id` in the path must match the authenticated customer.
- On failure the server sends an `error` event and closes the socket.
- On every reconnect the server sends fresh DB snapshots.

## Connection Order

After a successful connection the server sends, in this exact order:

1. `connection`
2. `orders_snapshot`
3. `shops_snapshot`
4. `on_way_snapshot`
5. `order_history_snapshot`

Example:

```json
{
  "type": "connection",
  "scope": "customer_app_realtime",
  "customer_id": 6,
  "message": "connected"
}
```

## Event Contract

### `orders_snapshot`

```json
{
  "type": "orders_snapshot",
  "data": {
    "count": 1,
    "results": [
      {
        "id": 135,
        "order_number": "OD000135",
        "shop_id": 3,
        "shop_name": "زايجو سوبر ماركت",
        "shop_logo_url": "https://example.com/media/shop_profiles/shop.png",
        "status": "new",
        "status_display": "جديد",
        "items_summary": "1x Cola, 1x Chips",
        "item_count": 2,
        "total_amount": "150.00",
        "delivery_fee": "20.00",
        "address": "شارع السنترال",
        "notes": "",
        "unread_messages_count": 1,
        "has_unread_messages": true,
        "chat": {
          "thread_id": "135",
          "order_id": 135,
          "chat_type": "shop_customer",
          "shop_id": 3
        },
        "last_message": {
          "id": 841,
          "chat_type": "shop_customer",
          "sender_type": "shop_owner",
          "sender_name": "محمد أحمد",
          "message_type": "text",
          "content": "تم استلام طلبك",
          "is_read": false,
          "created_at": "2026-04-03T08:00:38Z"
        },
        "created_at": "2026-04-03T08:00:00Z",
        "updated_at": "2026-04-03T08:00:00Z"
      }
    ]
  },
  "message": "orders synced"
}
```

### `order_upsert`

```json
{
  "type": "order_upsert",
  "data": {
    "...": "same shape as one item inside orders_snapshot.data.results[]"
  }
}
```

### `order_remove`

```json
{
  "type": "order_remove",
  "data": {
    "id": 135
  }
}
```

### `shops_snapshot`

```json
{
  "type": "shops_snapshot",
  "data": {
    "count": 1,
    "results": [
      {
        "shop_id": 3,
        "shop_name": "زايجو سوبر ماركت",
        "shop_logo_url": "https://example.com/media/shop_profiles/shop.png",
        "subtitle": "استفسار",
        "last_message_preview": "استفسار",
        "updated_at": "2026-04-03T08:01:02Z",
        "unread_messages_count": 0,
        "has_unread_messages": false,
        "chat": {
          "thread_id": "support_17",
          "support_conversation_id": "support_17",
          "order_id": null,
          "chat_type": "support_customer",
          "conversation_type": "inquiry",
          "shop_id": 3
        },
        "support_conversation": {
          "support_conversation_id": "support_17",
          "conversation_type": "inquiry",
          "conversation_type_display": "استفسار",
          "status": "open",
          "status_display": "مفتوحة",
          "shop_id": 3,
          "shop_name": "زايجو سوبر ماركت",
          "shop_logo_url": "https://example.com/media/shop_profiles/shop.png",
          "customer_id": 6,
          "subtitle": "استفسار",
          "last_message_preview": "استفسار",
          "last_message_at": "2026-04-03T08:01:02Z",
          "unread_for_customer_count": 0,
          "unread_for_shop_count": 1,
          "created_at": "2026-04-03T08:01:02Z",
          "updated_at": "2026-04-03T08:01:02Z",
          "chat": {
            "thread_id": "support_17",
            "support_conversation_id": "support_17",
            "order_id": null,
            "chat_type": "support_customer",
            "conversation_type": "inquiry",
            "shop_id": 3
          }
        }
      }
    ]
  },
  "message": "shops synced"
}
```

### `shop_upsert`

```json
{
  "type": "shop_upsert",
  "data": {
    "...": "same shape as one item inside shops_snapshot.data.results[]"
  }
}
```

### `shop_remove`

```json
{
  "type": "shop_remove",
  "data": {
    "shop_id": 3
  }
}
```

### `on_way_snapshot`

```json
{
  "type": "on_way_snapshot",
  "data": {
    "count": 1,
    "results": [
      {
        "order_id": 135,
        "order_number": "OD000135",
        "shop_id": 3,
        "shop_name": "زايجو سوبر ماركت",
        "shop_logo_url": "https://example.com/media/shop_profiles/shop.png",
        "driver_id": 9,
        "driver_name": "أحمد علي",
        "driver_image_url": "https://example.com/media/driver_profiles/driver.png",
        "driver_role_label": "مندوب",
        "status_key": "on_way",
        "status_label": "في الطريق",
        "last_delivery_update_at": "2026-04-03T08:15:00Z",
        "chat": {
          "thread_id": "delivery_135",
          "order_id": 135,
          "chat_type": "driver_customer",
          "can_open": true
        }
      }
    ]
  },
  "message": "on way synced"
}
```

### `on_way_upsert`

```json
{
  "type": "on_way_upsert",
  "data": {
    "...": "same shape as one item inside on_way_snapshot.data.results[]"
  }
}
```

### `on_way_remove`

```json
{
  "type": "on_way_remove",
  "data": {
    "order_id": 135
  }
}
```

### `order_history_snapshot`

```json
{
  "type": "order_history_snapshot",
  "data": {
    "count": 2,
    "results": [
      {
        "id": "order_135",
        "entry_type": "order",
        "ordered_at": "2026-04-03T08:00:38Z",
        "shop_id": 3,
        "store_name": "زايجو سوبر ماركت",
        "shop_logo_url": "https://example.com/media/shop_profiles/shop.png",
        "has_unread_messages": true,
        "order": {
          "order_id": 135,
          "order_number": "OD000135",
          "items_summary": "1x Cola, 1x Chips",
          "item_count": 2,
          "total_amount": "150.00",
          "status_key": "new",
          "status_label": "جديد",
          "history_status": "in_progress",
          "chat_type": "shop_customer"
        }
      },
      {
        "id": "support_17",
        "entry_type": "chat",
        "ordered_at": "2026-04-03T08:01:02Z",
        "shop_id": 3,
        "store_name": "زايجو سوبر ماركت",
        "shop_logo_url": "https://example.com/media/shop_profiles/shop.png",
        "has_unread_messages": false,
        "chat": {
          "support_conversation_id": "support_17",
          "chat_type": "support_customer",
          "conversation_type": "inquiry",
          "conversation_type_display": "استفسار",
          "chat_status": "waiting_reply",
          "chat_status_display": "بانتظار الرد",
          "title": "استفسار",
          "preview": "استفسار",
          "order_id": null,
          "order_number": null
        }
      }
    ]
  },
  "message": "order history synced"
}
```

### `order_history_entry_upsert`

```json
{
  "type": "order_history_entry_upsert",
  "data": {
    "...": "same shape as one item inside order_history_snapshot.data.results[]"
  }
}
```

### `order_history_entry_remove`

```json
{
  "type": "order_history_entry_remove",
  "data": {
    "id": "support_17",
    "entry_type": "chat"
  }
}
```

## Client Commands

Supported client-to-server commands:

```json
{"type": "refresh_orders"}
{"type": "refresh_shops"}
{"type": "refresh_on_way"}
{"type": "refresh_order_history"}
{"type": "refresh_all"}
```

Legacy aliases kept for compatibility:

```json
{"type": "sync_dashboard"}
{"type": "refresh_dashboard"}
```

## Trigger Matrix

- New order: `order_upsert`, `shop_upsert`, `order_history_entry_upsert`, and `on_way_upsert` only if the new order already qualifies as on-way.
- Order update/status/driver change: `order_upsert` or `order_remove`, `on_way_upsert` or `on_way_remove`, `shop_upsert`, `order_history_entry_upsert`.
- Order deletion: `order_remove`, `on_way_remove`, `order_history_entry_remove`, plus `shop_upsert` or `shop_remove` depending on remaining latest interaction for that shop.
- New `shop_customer` order chat message: `order_upsert`, `shop_upsert`, `order_history_entry_upsert`.
- Customer reads `shop_customer` order chat: `order_upsert`, `shop_upsert`, `order_history_entry_upsert`.
- New inquiry / complaint: `shop_upsert`, `order_history_entry_upsert`.
- New support message: `shop_upsert`, `order_history_entry_upsert`.
- Customer reads support chat: `shop_upsert`, `order_history_entry_upsert`.

## Serializers Used

- `CustomerAppRealtimeOrderSerializer`
- `CustomerAppRealtimeOrderShopEntrySerializer`
- `CustomerAppRealtimeSupportConversationSerializer`
- `CustomerAppRealtimeSupportShopEntrySerializer`
- `CustomerAppRealtimeOnWaySerializer`
- `CustomerAppRealtimeOrderHistoryOrderEntrySerializer`
- `CustomerAppRealtimeOrderHistoryChatEntrySerializer`

Source files:

- `shop/realtime_serializers.py`
- `shop/customer_app_realtime.py`

## Tests Added

File:

- `shop/tests/test_customer_app_realtime.py`

Coverage:

- initial snapshot order
- create order delta push
- create inquiry delta push
- create complaint delta push
- order chat message delta push
- support chat message delta push
- enter on-way delta
- leave on-way delta
- reconnect snapshot correctness
- latest interaction dedupe per shop
- customer unread counts correctness
- order history ordering
- `refresh_all` command order

## Reconnect And Missed Events

- There is no replay buffer and no event sequence cursor in this implementation.
- The socket treats reconnect as full resync.
- On reconnect the backend sends fresh snapshots from the latest database state.
- Frontend should treat snapshots as source of truth and apply upserts/removes idempotently between reconnects.

## Assumptions And Current Limits

- The current database model exposes order statuses `new`, `pending_customer_confirm`, `confirmed`, `preparing`, `on_way`, `delivered`, `cancelled`. Therefore the realtime `on_way` stream currently maps the delivery-active set to `confirmed`, `preparing`, and `on_way`.
- Customer unread counts in this channel are computed from `shop_customer` order messages for the customer side, not from the legacy `Order.unread_messages_count` field that is maintained for shop-side unread counts.
- Driver chat metadata is included inside `on_way` items, but driver chat deltas are not injected into `orders`, `shops`, or `order_history`.
