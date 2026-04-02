# Customer WebSocket Contract

This document is the dedicated source of truth for the customer-side realtime integration only.

It covers:

- Customer orders socket
- Customer chat with shop
- Customer chat with driver
- Customer support chat with shop for `inquiry` / `complaint`
- Driver live location updates
- Dashboard snapshots for customer tabs
- Ring / nudge notifications
- Event names and payload shapes
- Reconnect behavior
- Customer-side action mapping

The backend uses native WebSocket, not Socket.IO.

## 1. Socket Type

- Protocol: native WebSocket
- HTTP environments: `ws://<host>/ws/`
- HTTPS environments: `wss://<host>/ws/`

## 2. Authentication

All customer sockets require a JWT access token in the query string:

```text
?token=<JWT_ACCESS_TOKEN>
```

Optional query parameters:

- `lang=ar` or `lang=en`
- `chat_type=shop_customer` or `chat_type=driver_customer` on order chat sockets only

Connection close codes used by the backend:

- `4401`: missing or invalid token, or wrong authenticated customer for the orders socket
- `4403`: authenticated user does not have access to this order/chat
- `1011`: unexpected server error during connect

Supported customer-side authenticated user:

- `customer`

## 3. Customer Channels

### 3.1 Customer orders channel

Used for live order changes in the customer app.

```text
/ws/orders/customer/{customer_id}/?token=<JWT>
```

Allowed users:

- `customer` where `user.id == customer_id`

What happens on connect:

1. The server accepts the socket.
2. It sends a `connection` event.
3. It sends `dashboard_snapshot`.
4. It sends `orders_snapshot`.
5. It sends `shops_snapshot`.
6. It sends `on_way_snapshot`.

Important:

- `dashboard_snapshot` is the unified source of truth for the customer tabs.
- Orders are read from `dashboard_snapshot.data.orders`.
- Shops/conversations are read from `dashboard_snapshot.data.shops.results`.
- On-way orders are read from `dashboard_snapshot.data.on_way.results`.
- The legacy per-tab snapshots are still sent for backward compatibility: `orders_snapshot`, `shops_snapshot`, and `on_way_snapshot`.
- The frontend no longer needs REST just to render the orders list, shops-conversations tab, or on-way tab.
- The same socket also receives incremental events such as `order_update`, `new_message`, `support_conversation_update`, `support_message`, and `driver_location`.

Customer list endpoints replaced by the snapshots above:

```text
GET /api/customer/orders/
GET /api/customer/shops-conversations/
GET /api/customer/orders/on-way/
```

### 3.2 Customer chat with shop

Used for the customer conversation with the shop on one order.

```text
/ws/chat/order/{order_id}/?token=<JWT>&chat_type=shop_customer
```

Allowed users:

- `customer` who owns the order
- `shop_owner`
- `employee`

What happens on connect:

1. The server validates token and order access.
2. It sends a `connection` event.
3. It immediately sends `previous_messages`.

### 3.3 Customer chat with driver

Used for the customer conversation with the assigned driver on one order.

```text
/ws/chat/order/{order_id}/?token=<JWT>&chat_type=driver_customer
```

Allowed users:

- `customer` who owns the order
- `driver` assigned to the order

What happens on connect:

1. The server validates token and order access.
2. It sends a `connection` event.
3. It immediately sends `previous_messages`.

### 3.4 Customer support chat with shop

Used for customer `inquiry` or `complaint` flows that should open chat immediately without creating an order.

```text
/ws/chat/support/{support_conversation_id}/?token=<JWT>
```

Allowed users:

- `customer` who owns the support conversation
- `shop_owner`
- `employee`

What happens on connect:

1. The server validates token and support conversation access.
2. It sends a `connection` event.
3. It immediately sends `previous_messages`.

## 4. Rooms and Subscription Logic

There is no explicit `join_order_room` or `leave_order_room`.

Subscription is implicit:

- Opening `/ws/orders/customer/{customer_id}/...` joins the customer orders stream
- Opening `/ws/chat/order/{order_id}/...?chat_type=shop_customer` joins the shop-customer chat room
- Opening `/ws/chat/order/{order_id}/...?chat_type=driver_customer` joins the driver-customer chat room
- Opening `/ws/chat/support/{support_conversation_id}/...` joins the standalone support chat room

Realtime fan-out rules relevant to the customer:

- `shop_customer` chat messages are broadcast to the chat room and the customer orders channel
- `driver_customer` chat messages are broadcast to the chat room and the customer orders channel
- `support_customer` chat messages are broadcast to the support chat room and to the customer orders channel as `support_message`
- Driver live location updates are pushed to the customer orders channel
- Order workflow changes are pushed to the customer orders channel as `order_update`
- Support conversation metadata changes are pushed to the customer orders channel as `support_conversation_update`
- Ring events can arrive on the customer orders channel and on the chat channel

## 5. Shared Payload Shapes

### 5.1 Chat message object

This shape appears in:

- `previous_messages.messages[]`
- `chat_message.data`
- `new_message.data.message`

```json
{
  "id": 36,
  "order_id": 7,
  "chat_type": "shop_customer",
  "sender_type": "shop_owner",
  "sender_name": "برجر كنچ",
  "sender_id": 2,
  "message_type": "text",
  "content": "تم إنشاء الفاتورة",
  "latitude": null,
  "longitude": null,
  "invoice": null,
  "is_read": false,
  "created_at": "2026-03-22T00:12:00+02:00",
  "audio_file_url": null,
  "image_file_url": null
}
```

Notes:

- `message_type` can be `text`, `location`, `audio`, or `image` depending on how the message was created.
- Audio and image messages are uploaded through REST, then broadcast back over WebSocket.
- `invoice` may be present for system/invoice-related messages.

### 5.1A Support chat message object

This shape appears in:

- support chat `previous_messages.messages[]`
- support chat `chat_message.data`
- customer orders `support_message.data.message`

```json
{
  "id": 9,
  "support_conversation_id": "support_12",
  "chat_type": "support_customer",
  "conversation_type": "complaint",
  "conversation_type_display": "شكوى",
  "sender_type": "customer",
  "sender_name": "Ahmed",
  "sender_id": 7,
  "message_type": "text",
  "content": "عندي شكوى بخصوص الخدمة",
  "latitude": null,
  "longitude": null,
  "is_read": false,
  "created_at": "2026-04-02T12:30:00+02:00",
  "audio_file_url": null,
  "image_file_url": null
}
```

### 5.1B Support conversation summary object

This shape appears in:

- `shops_snapshot.data.results[].support_conversation`
- `support_conversation_update.data`
- `support_message.data.conversation`

```json
{
  "support_conversation_id": "support_12",
  "conversation_type": "inquiry",
  "conversation_type_display": "استفسار",
  "status": "open",
  "status_display": "مفتوحة",
  "shop_id": 8,
  "shop_name": "برجر كنچ",
  "shop_logo_url": "/media/shops/logo.png",
  "customer_id": 7,
  "customer_name": "Ahmed",
  "subtitle": "استفسار مفتوح",
  "last_message_preview": null,
  "last_message_at": null,
  "unread_for_customer_count": 0,
  "unread_for_shop_count": 0,
  "created_at": "2026-04-02T12:28:00+02:00",
  "updated_at": "2026-04-02T12:28:00+02:00",
  "chat": {
    "support_conversation_id": "support_12",
    "chat_type": "support_customer",
    "conversation_type": "inquiry",
    "shop_id": 8
  }
}
```

### 5.2 Order snapshot object

This shape appears in:

- `orders_snapshot.data.orders[]`
- `order_update.data`
- `new_message.data.order`

It uses the same shape as `OrderSerializer`.

Key fields used by the customer frontend include:

- `id`
- `order_number`
- `customer`
- `employee`
- `driver`
- `status`
- `status_display`
- `items`
- `total_amount`
- `delivery_fee`
- `address`
- `notes`
- `unread_messages_count`
- `last_message`
- `created_at`
- `updated_at`

## 6. Customer Orders Socket Events

Server-to-client events on `/ws/orders/customer/{customer_id}/`:

- `connection`
- `dashboard_snapshot`
- `orders_snapshot`
- `shops_snapshot`
- `on_way_snapshot`
- `order_update`
- `new_message`
- `support_conversation_update`
- `support_message`
- `driver_location`
- `ring`
- `ack`
- `error`

Client-to-server events accepted on `/ws/orders/customer/{customer_id}/`:

- `sync_dashboard`
- `refresh_dashboard` as an alias of `sync_dashboard`
- `ring`

Important:

- After every successful connect, the backend sends `dashboard_snapshot` and then the three per-tab snapshots.
- After every `order_update`, the backend re-sends `dashboard_snapshot`, `orders_snapshot`, `shops_snapshot`, and `on_way_snapshot`.
- After every `new_message`, the backend re-sends `dashboard_snapshot`, `orders_snapshot`, `shops_snapshot`, and `on_way_snapshot`.
- After every `support_conversation_update`, the backend re-sends `dashboard_snapshot`, `orders_snapshot`, `shops_snapshot`, and `on_way_snapshot`.
- After every `support_message`, the backend re-sends `dashboard_snapshot`, `orders_snapshot`, `shops_snapshot`, and `on_way_snapshot`.
- `driver_location` is incremental only and does not trigger a full snapshot refresh by itself.

### 6.1 `connection`

```json
{
  "type": "connection",
  "message": "تم الاتصال بنجاح",
  "message_ar": "تم الاتصال بنجاح",
  "message_en": "Connected successfully"
}
```

### 6.2 `dashboard_snapshot`

Primary event for the customer dashboard. It returns all three tabs in one payload.

```json
{
  "type": "dashboard_snapshot",
  "data": {
    "orders": [
      {
        "...": "same shape as OrderSerializer"
      }
    ],
    "shops": {
      "count": 2,
      "results": []
    },
    "on_way": {
      "count": 1,
      "results": []
    }
  },
  "message": "تمت مزامنة لوحة العميل بنجاح"
}
```

### 6.3 `orders_snapshot`

Sent immediately after connect and after a dashboard resync.

```json
{
  "type": "orders_snapshot",
  "data": {
    "orders": [
      {
        "...": "same shape as OrderSerializer"
      }
    ]
  },
  "message": "تمت مزامنة الطلبات بنجاح"
}
```

### 6.4 `shops_snapshot`

Used for the customer shops-conversations tab.

```json
{
  "type": "shops_snapshot",
  "data": {
    "count": 2,
    "results": [
      {
        "shop_id": 8,
        "shop_name": "برجر كنچ",
        "shop_logo_url": "/media/shops/logo.png",
        "subtitle": "تم التواصل مؤخراً",
        "chat": {
          "order_id": 15,
          "chat_type": "shop_customer",
          "shop_id": 8
        }
      }
    ]
  },
  "message": "تمت مزامنة قائمة المحلات بنجاح"
}
```

Notes:

- A result can point either to an order chat or to a standalone support chat.
- When the latest customer-shop thread is a support chat, `chat.order_id` is absent and `chat.support_conversation_id` is present.
- In that case the result can also include `support_conversation` with the full support conversation summary object.

### 6.5 `on_way_snapshot`

Used for the customer on-way tab.

```json
{
  "type": "on_way_snapshot",
  "data": {
    "count": 1,
    "results": [
      {
        "order_id": 15,
        "status_key": "on_way",
        "status_label": "في الطريق",
        "shop_id": 8,
        "shop_name": "برجر كنچ",
        "shop_logo_url": "/media/shops/logo.png",
        "driver_id": 12,
        "driver_name": "أحمد محمود",
        "driver_image_url": "/media/drivers/driver.jpg",
        "driver_role_label": "مندوب التوصيل",
        "chat": {
          "order_id": 15,
          "chat_type": "driver_customer",
          "driver_id": 12
        }
      }
    ]
  },
  "message": "تمت مزامنة طلبات الطريق بنجاح"
}
```

### 6.6 Client event: `sync_dashboard`

Requests a fresh customer dashboard snapshot set from the same socket.

```json
{
  "type": "sync_dashboard",
  "request_id": "sync-1001"
}
```

`refresh_dashboard` is accepted as an alias and behaves the same way.

### 6.7 `order_update`

Sent when the order snapshot changes.

Typical reasons:

- invoice created or edited by shop
- invoice cancelled
- customer confirmed invoice
- customer rejected invoice
- driver assigned or changed
- delivery status moved to `preparing` or `on_way`
- unread counters changed after chat read actions

```json
{
  "type": "order_update",
  "data": {
    "...": "same shape as one order inside orders_snapshot.data.orders[]"
  }
}
```

Important:

- There is no separate `order_cancelled` event.
- Cancellation is delivered through `order_update` where `data.status == "cancelled"`.
- After sending `order_update`, the backend re-sends `dashboard_snapshot`, `orders_snapshot`, `shops_snapshot`, and `on_way_snapshot`.

### 6.8 `new_message`

Sent when a new chat message is created for this customer's order.

This can come from:

- `shop_customer` chat
- `driver_customer` chat

```json
{
  "type": "new_message",
  "data": {
    "order_id": 7,
    "order_number": "ODGRQIZA",
    "chat_type": "shop_customer",
    "message": {
      "...": "same shape as one chat message object"
    },
    "order": {
      "...": "latest order snapshot after this message"
    }
  }
}
```

After sending `new_message`, the backend re-sends `dashboard_snapshot`, `orders_snapshot`, `shops_snapshot`, and `on_way_snapshot`.

### 6.9 `support_conversation_update`

Sent when a standalone `inquiry` or `complaint` conversation is created or when its unread/summary metadata changes.

```json
{
  "type": "support_conversation_update",
  "data": {
    "...": "same shape as one support conversation summary object"
  }
}
```

After sending `support_conversation_update`, the backend re-sends `dashboard_snapshot`, `orders_snapshot`, `shops_snapshot`, and `on_way_snapshot`.

### 6.10 `support_message`

Sent when a new standalone support chat message is created.

```json
{
  "type": "support_message",
  "data": {
    "support_conversation_id": "support_12",
    "chat_type": "support_customer",
    "conversation_type": "complaint",
    "message": {
      "...": "same shape as one support chat message object"
    },
    "conversation": {
      "...": "same shape as one support conversation summary object"
    },
    "shop_id": 8,
    "shop_name": "برجر كنچ",
    "customer_id": 7,
    "customer_name": "Ahmed"
  }
}
```

After sending `support_message`, the backend re-sends `dashboard_snapshot`, `orders_snapshot`, `shops_snapshot`, and `on_way_snapshot`.

### 6.11 `driver_location`

Sent when the driver updates location while the order is active.

```json
{
  "type": "driver_location",
  "data": {
    "driver_id": 9,
    "latitude": "30.0444",
    "longitude": "31.2357",
    "updated_at": "2026-03-22T00:18:00+02:00"
  }
}
```

### 6.12 Client event: `ring`

This is a lightweight notification only. It does not open a call.

```json
{
  "type": "ring",
  "request_id": "ring-101",
  "order_id": 15,
  "target": "shop"
}
```

Supported targets when the sender is a customer:

- `shop`
- `driver`

You can also send multiple targets:

```json
{
  "type": "ring",
  "request_id": "ring-102",
  "order_id": 15,
  "targets": ["shop", "driver"]
}
```

### 6.13 Server event: `ring`

```json
{
  "type": "ring",
  "data": {
    "ring_id": "uuid-value",
    "order_id": 15,
    "order_number": "OD12345",
    "sender_type": "customer",
    "sender_name": "Ahmed",
    "sender_id": 7,
    "target": "shop",
    "targets": ["shop"],
    "chat_type": null,
    "notification_kind": "ring",
    "play_sound_on_frontend": true,
    "created_at": "2026-03-28T20:15:00+02:00"
  }
}
```

`chat_type` is `null` when the ring is sent from the orders socket, and can be `shop_customer` or `driver_customer` when sent from a chat socket.

### 6.14 Server event: `ack`

Used for successful client actions such as `sync_dashboard` and `ring`.

Example for dashboard sync:

```json
{
  "type": "ack",
  "action": "sync_dashboard",
  "success": true,
  "request_id": "sync-1001",
  "data": {},
  "message": "تمت مزامنة بيانات العميل بنجاح"
}
```

Example for ring:

```json
{
  "type": "ack",
  "action": "ring",
  "success": true,
  "request_id": "ring-101",
  "data": {
    "order_id": 15,
    "targets": ["shop"],
    "unavailable_targets": [],
    "ring_id": "uuid-value"
  }
}
```

### 6.15 Server event: `error`

Examples of error codes from the current backend:

- `UNKNOWN_EVENT`
- `INVALID_JSON`
- `ORDER_NOT_FOUND`
- `ORDER_ACCESS_DENIED`
- `RING_TARGET_REQUIRED`
- `RING_TARGET_NOT_ALLOWED`
- `RING_TARGET_UNAVAILABLE`
- `UNEXPECTED_ERROR`

```json
{
  "type": "error",
  "success": false,
  "code": "RING_TARGET_REQUIRED",
  "request_id": "ring-101",
  "message": "يجب تحديد الطرف المطلوب إرسال الرنة له"
}
```

## 7. Customer Chat Events

Server-to-client events on both:

- `/ws/chat/order/{order_id}/?token=<JWT>&chat_type=shop_customer`
- `/ws/chat/order/{order_id}/?token=<JWT>&chat_type=driver_customer`

Server-to-client events on support chat:

- `/ws/chat/support/{support_conversation_id}/?token=<JWT>`

Server-to-client events:

- `connection`
- `previous_messages`
- `chat_message`
- `messages_read`
- `typing`
- `ring`
- `ack`
- `error`

Server-to-client events on support chat:

- `connection`
- `previous_messages`
- `chat_message`
- `messages_read`
- `typing`
- `ack`
- `error`

Client-to-server events:

- `send_message`
- `chat_message` as legacy compatibility
- `location`
- `mark_read`
- `typing`
- `ring`

Client-to-server events on support chat:

- `send_message`
- `chat_message` as legacy compatibility
- `location`
- `mark_read`
- `typing`

### 7.1 `connection`

Example for shop chat:

```json
{
  "type": "connection",
  "order_id": "7",
  "chat_type": "shop_customer",
  "user_type": "customer",
  "message": "تم الاتصال بنجاح",
  "message_ar": "تم الاتصال بنجاح",
  "message_en": "Connected successfully"
}
```

Example for driver chat:

```json
{
  "type": "connection",
  "order_id": "7",
  "chat_type": "driver_customer",
  "user_type": "customer",
  "message": "تم الاتصال بنجاح",
  "message_ar": "تم الاتصال بنجاح",
  "message_en": "Connected successfully"
}
```

Example for support chat:

```json
{
  "type": "connection",
  "support_conversation_id": "support_12",
  "chat_type": "support_customer",
  "conversation_type": "complaint",
  "user_type": "customer",
  "message": "تم الاتصال بنجاح",
  "message_ar": "تم الاتصال بنجاح",
  "message_en": "Connected successfully"
}
```

### 7.2 `previous_messages`

Sent immediately after a successful chat connect.

Current backend behavior:

- Returns up to 50 messages
- On order chats: filtered by `order_id` and the selected `chat_type`
- On support chats: filtered by `support_conversation_id`
- Ordered ascending by `created_at`

```json
{
  "type": "previous_messages",
  "messages": [
    {
      "...": "same shape as one chat message object"
    }
  ]
}
```

### 7.3 Client event: `send_message`

Recommended event for sending text messages:

```json
{
  "type": "send_message",
  "request_id": "msg-101",
  "message_type": "text",
  "content": "تمام"
}
```

Works on:

- `chat_type=shop_customer`
- `chat_type=driver_customer`
- `/ws/chat/support/{support_conversation_id}/?token=<JWT>`

### 7.4 Client event: legacy `chat_message`

Still accepted for compatibility:

```json
{
  "type": "chat_message",
  "request_id": "msg-101",
  "message_type": "text",
  "content": "تمام"
}
```

### 7.5 Client event: `location`

```json
{
  "type": "location",
  "request_id": "loc-55",
  "latitude": "30.0444",
  "longitude": "31.2357",
  "content": "موقعي الحالي"
}
```

### 7.6 Client event: `mark_read`

```json
{
  "type": "mark_read",
  "request_id": "read-7"
}
```

Result:

- Chat room receives `messages_read`
- Sender receives `ack`
- On order chats: related order streams receive `order_update`
- On support chats: related customer/shop streams receive `support_conversation_update`
- Customer orders socket then receives the three snapshots again

### 7.7 Client event: `typing`

```json
{
  "type": "typing",
  "is_typing": true
}
```

### 7.8 Client event: `ring`

Supported only on order chat sockets.

```json
{
  "type": "ring",
  "request_id": "ring-201",
  "order_id": 15,
  "target": "shop"
}
```

When sent from a chat socket, the outgoing ring payload includes the current `chat_type`.

### 7.9 Server event: `chat_message`

```json
{
  "type": "chat_message",
  "data": {
    "...": "same shape as one chat message object"
  }
}
```

On support chat sockets, `data` uses the support chat message object instead.

### 7.10 Server event: `messages_read`

```json
{
  "type": "messages_read",
  "order_id": "7",
  "reader_type": "customer",
  "count": 3
}
```

Support chat example:

```json
{
  "type": "messages_read",
  "support_conversation_id": "support_12",
  "reader_type": "shop_owner",
  "count": 2
}
```

### 7.11 Server event: `typing`

Example for shop chat:

```json
{
  "type": "typing",
  "user_type": "shop_owner",
  "user_name": "برجر كنچ",
  "is_typing": true
}
```

Example for driver chat:

```json
{
  "type": "typing",
  "user_type": "driver",
  "user_name": "أحمد محمود",
  "is_typing": true
}
```

### 7.12 Server event: `ring`

```json
{
  "type": "ring",
  "data": {
    "ring_id": "uuid-value",
    "order_id": 15,
    "order_number": "OD12345",
    "sender_type": "shop_owner",
    "sender_name": "برجر كنچ",
    "sender_id": 8,
    "target": "customer",
    "targets": ["customer"],
    "chat_type": "shop_customer",
    "notification_kind": "ring",
    "play_sound_on_frontend": true,
    "created_at": "2026-03-28T20:15:00+02:00"
  }
}
```

### 7.13 Server event: `ack`

Used for successful client actions such as `send_message`, `chat_message`, `location`, `mark_read`, and `ring`.

```json
{
  "type": "ack",
  "action": "send_message",
  "success": true,
  "request_id": "msg-101",
  "data": {
    "message_id": 36,
    "order_id": 7,
    "chat_type": "shop_customer"
  },
  "message": "تم تنفيذ الطلب بنجاح",
  "message_ar": "تم تنفيذ الطلب بنجاح",
  "message_en": "Request completed successfully"
}
```

Support chat example:

```json
{
  "type": "ack",
  "action": "send_message",
  "success": true,
  "request_id": "msg-201",
  "data": {
    "message_id": 9,
    "support_conversation_id": "support_12",
    "chat_type": "support_customer"
  },
  "message": "تم تنفيذ الطلب بنجاح"
}
```

### 7.14 Server event: `error`

Examples of error codes from the current backend:

- `UNKNOWN_EVENT`
- `INVALID_JSON`
- `UNSUPPORTED_MESSAGE_TYPE`
- `MESSAGE_CONTENT_REQUIRED`
- `LOCATION_COORDINATES_REQUIRED`
- `MESSAGE_SAVE_FAILED`
- `ORDER_NOT_FOUND`
- `ORDER_ACCESS_DENIED`
- `RING_TARGET_REQUIRED`
- `RING_TARGET_NOT_ALLOWED`
- `RING_TARGET_UNAVAILABLE`
- `UNEXPECTED_ERROR`

```json
{
  "type": "error",
  "success": false,
  "code": "MESSAGE_CONTENT_REQUIRED",
  "request_id": "msg-101",
  "message": "محتوى الرسالة مطلوب",
  "message_ar": "محتوى الرسالة مطلوب",
  "message_en": "Message content is required"
}
```

## 8. Media Messages for Customer Chat

Audio and image messages are not uploaded through WebSocket directly.

Transport:

- REST upload, then websocket broadcast

Endpoint:

```text
POST /api/chat/order/{order_id}/send-media/
POST /api/chat/support/{support_conversation_id}/send-media/
```

Form-data:

- On order chat uploads: `chat_type=shop_customer` or `chat_type=driver_customer`
- On support chat uploads: no `chat_type` is required because the route already identifies the support conversation
- `audio_file` or `image_file`
- optional `content`

Realtime result:

- Chat room receives `chat_message`
- Order chat uploads push `new_message` on the related customer orders socket
- Support chat uploads push `support_message` on the related customer orders socket
- Customer orders socket then receives refreshed snapshots

## 9. Source of Truth

Current backend source of truth for customer realtime behavior:

- `shop/consumers.py`:
  - `CustomerOrderConsumer`
  - `ChatConsumer`
  - `SupportChatConsumer`
- `shop/websocket_utils.py`
- `shop/serializers.py`:
  - `OrderSerializer`
  - `ChatMessageSerializer`
  - `CustomerSupportConversationSerializer`
  - `CustomerSupportMessageSerializer`
- `shop/models.py`:
  - `CustomerSupportConversation`
  - `CustomerSupportMessage`
- `shop/views.py` helpers used to build customer dashboard snapshot items

If this document and implementation diverge, the implementation wins.

## 10. Reconnect Behavior

### Customer orders socket

On reconnect, the frontend should expect this sequence again:

1. `connection`
2. `dashboard_snapshot`
3. `orders_snapshot`
4. `shops_snapshot`
5. `on_way_snapshot`
6. Resume live handling of `order_update`, `new_message`, `support_conversation_update`, `support_message`, `driver_location`, and `ring`

### Customer chat sockets

On reconnect, the frontend should:

1. Re-open the active chat socket:
   - for order chat: with the same `order_id` and `chat_type`
   - for support chat: with the same `support_conversation_id`
2. Wait for `connection`
3. Wait for `previous_messages`
4. Resume sending `mark_read` if needed
5. Resume live handling of `chat_message`, `messages_read`, and `typing`
6. On order chats only, also resume live handling of `ring`

## 11. Current Naming Notes

Current backend event names for customer integrations are:

- `dashboard_snapshot`
- `orders_snapshot`
- `shops_snapshot`
- `on_way_snapshot`
- `order_update`
- `new_message`
- `support_conversation_update`
- `support_message`
- `driver_location`
- `chat_message`
- `messages_read`
- `typing`
- `ring`
- `ack`
- `error`

Important naming notes:

- The backend currently uses `order_update`, not `order_updated`
- The backend currently uses `mark_read`, not `mark_message_seen`
- The backend currently uses `sync_dashboard`, and also accepts `refresh_dashboard` as an alias
- There is no separate `order_cancelled` event; cancellation comes through `order_update`
- Standalone `inquiry` / `complaint` chat uses `support_conversation_update` and `support_message`, not `order_update`

## 12. Customer UI Action Map

The customer UI actions do not all map to standalone websocket event names.

Important rule:

- Some actions are sent directly through WebSocket
- Some actions are sent through REST
- After successful REST actions, the backend pushes realtime websocket updates back to the customer

### 12.1 Create new order

Purpose:

- Create a new order and send the first request content to the shop

Transport:

- REST

Endpoint:

```text
POST /api/customer/orders/
```

Request body example:

```json
{
  "shop_owner_id": 12,
  "address": "TEST - TEST",
  "items": [
    "Item 1",
    "Item 2"
  ],
  "notes": "Optional notes"
}
```

Backend behavior:

- Creates the order with `status=new`
- Creates the first chat message in `shop_customer`
- Broadcasts that first message realtime
- Creates the static customer-facing status message that the order was received

Realtime result:

- Shop dashboard receives `new_order`
- Shop and customer flows receive `new_message`
- If the customer orders socket is already open, it also receives fresh customer dashboard snapshots

### 12.1A Open inquiry / complaint chat without order

Purpose:

- Open customer support chat immediately with the selected shop without creating an order or invoice flow

Transport:

- REST

Endpoint:

```text
POST /api/customer/support-chats/
```

Request body example:

```json
{
  "shop_owner_id": 12,
  "conversation_type": "complaint",
  "initial_message": "عندي شكوى بخصوص الخدمة"
}
```

Allowed `conversation_type` values:

- `inquiry`
- `complaint`

Backend behavior:

- Creates a standalone support conversation linked to the customer and shop
- Returns `support_conversation_id`
- Does not create an order
- If `initial_message` is provided, creates the first support message immediately

Realtime result:

- Customer orders socket receives `support_conversation_update`
- If `initial_message` is provided, customer orders socket also receives `support_message`
- `shops_snapshot` refreshes so the shop thread can point to `support_conversation_id`

### 12.2 Send text message

Transport:

- WebSocket

Socket:

- `/ws/chat/order/{order_id}/?token=<JWT>&chat_type=shop_customer`
- `/ws/chat/order/{order_id}/?token=<JWT>&chat_type=driver_customer`
- `/ws/chat/support/{support_conversation_id}/?token=<JWT>`

Client payload:

```json
{
  "type": "send_message",
  "request_id": "msg-101",
  "message_type": "text",
  "content": "تمام"
}
```

Realtime result:

- Chat room receives `chat_message`
- Sender receives `ack`
- On order chat, customer orders socket receives `new_message`
- On support chat, customer orders socket receives `support_message`
- Customer orders socket receives refreshed snapshots

### 12.3 Send audio file

Transport:

- REST upload, then websocket broadcast

Endpoint:

```text
POST /api/chat/order/{order_id}/send-media/
POST /api/chat/support/{support_conversation_id}/send-media/
```

Form-data:

- On order chat uploads: `chat_type=shop_customer` or `chat_type=driver_customer`
- On support chat uploads: no `chat_type` is required
- `audio_file`
- optional `content`

Realtime result:

- Chat room receives `chat_message` with `message_type=audio`
- On order chat, customer orders socket receives `new_message`
- On support chat, customer orders socket receives `support_message`
- Customer orders socket receives refreshed snapshots

### 12.4 Send image

Transport:

- REST upload, then websocket broadcast

Endpoint:

```text
POST /api/chat/order/{order_id}/send-media/
POST /api/chat/support/{support_conversation_id}/send-media/
```

Form-data:

- On order chat uploads: `chat_type=shop_customer` or `chat_type=driver_customer`
- On support chat uploads: no `chat_type` is required
- `image_file`
- optional `content`

Realtime result:

- Chat room receives `chat_message` with `message_type=image`
- On order chat, customer orders socket receives `new_message`
- On support chat, customer orders socket receives `support_message`
- Customer orders socket receives refreshed snapshots

### 12.5 Send current location

Transport:

- WebSocket

Socket payload:

```json
{
  "type": "location",
  "request_id": "loc-55",
  "latitude": "30.0444",
  "longitude": "31.2357",
  "content": "موقعي الحالي"
}
```

Realtime result:

- Chat room receives `chat_message` with `message_type=location`
- Sender receives `ack`
- On order chat, customer orders socket receives `new_message`
- On support chat, customer orders socket receives `support_message`
- Customer orders socket receives refreshed snapshots

### 12.6 Mark messages as read

Transport:

- WebSocket

Socket payload:

```json
{
  "type": "mark_read",
  "request_id": "read-7"
}
```

Realtime result:

- Chat room receives `messages_read`
- Sender receives `ack`
- On order chat, related order streams receive `order_update`
- On support chat, related customer/shop streams receive `support_conversation_update`
- Customer orders socket receives refreshed snapshots

### 12.7 Send ring / nudge

Transport:

- WebSocket

Possible sockets:

- `/ws/orders/customer/{customer_id}/?token=<JWT>`
- `/ws/chat/order/{order_id}/?token=<JWT>&chat_type=shop_customer`
- `/ws/chat/order/{order_id}/?token=<JWT>&chat_type=driver_customer`

`ring` is not supported on `/ws/chat/support/{support_conversation_id}/`.

Client payload:

```json
{
  "type": "ring",
  "request_id": "ring-501",
  "order_id": 15,
  "target": "shop"
}
```

Realtime result:

- The target side receives `ring`
- The sender receives `ack`
- The frontend plays sound or visual notification locally

### 12.8 Confirm invoice

Transport:

- REST

Endpoint:

```text
POST /api/customer/orders/{order_id}/confirm/
```

Realtime result:

- Customer orders socket receives `order_update` with `status=confirmed`
- Shop and customer flows receive `new_message` for the system confirmation message
- Customer orders socket receives refreshed snapshots

### 12.9 Reject invoice

Transport:

- REST

Endpoint:

```text
POST /api/customer/orders/{order_id}/reject/
```

Realtime result:

- Customer orders socket receives `order_update` with `status=cancelled`
- Shop and customer flows receive `new_message` for the system rejection message
- Customer orders socket receives refreshed snapshots

### 12.10 Track driver live

Primary realtime source:

- Customer orders socket `driver_location`

Fallback REST endpoint:

```text
GET /api/orders/{order_id}/track/
```

Use this when:

- The screen opens after reconnect and you want the latest stored coordinates immediately
- You want one immediate coordinate fetch before waiting for the next websocket push

## 13. Automatic Status Messages

The following customer-facing messages are system-generated by the backend:

- After order creation:
  - `تم استلام طلبك ويرجى الانتظار حتى يتم إرسال الفاتورة.`
- After shop pricing:
  - `تم تسعير الطلب، يرجى المراجعة والضغط على تأكيد أو إلغاء.`
- After shop edits the invoice:
  - `تم تعديل الفاتورة وإعادة إرسالها للعميل بانتظار الموافقة.`
- After shop cancels before confirmation:
  - `تم إلغاء الفاتورة.`
- After customer confirms:
  - `تمت الموافقة على الفاتورة من العميل`
- After customer rejects:
  - `تم رفض الفاتورة من العميل`

Implementation note:

- These are static workflow/status messages generated automatically by the server.
- They are not expected to be typed manually by shop staff.
