# Shop WebSocket Contract

This document is the dedicated source of truth for the shop-side realtime integration only.

It covers:

- Shop owner dashboard socket
- Employee dashboard socket access
- Shop-customer order chat socket
- Event names and payload shapes
- Reconnect behavior
- How new orders and latest messages reach the shop UI in realtime

The backend uses native WebSocket, not Socket.IO.

## 1. Socket Type

- Protocol: native WebSocket
- HTTP environments: `ws://<host>/ws/`
- HTTPS environments: `wss://<host>/ws/`

## 2. Authentication

All shop sockets require a JWT access token in the query string:

```text
?token=<JWT_ACCESS_TOKEN>
```

Connection close codes used by the backend:

- `4401`: missing or invalid token
- `4403`: authenticated user does not have access to this shop/order
- `1011`: unexpected server error during connect

Supported shop users:

- `shop_owner`
- `employee`

## 3. Shop Channels

### 3.1 Shop dashboard orders channel

Used for the shop order list and live dashboard changes.

```text
/ws/orders/shop/{shop_owner_id}/?token=<JWT>
```

Allowed users:

- `shop_owner` where `user.id == shop_owner_id`
- `employee` where `user.shop_owner_id == shop_owner_id`

What happens on connect:

1. The server accepts the socket.
2. It sends a `connection` event.
3. It immediately sends `orders_snapshot`.

Important:

- `orders_snapshot` is the initial shop list snapshot.
- The current dashboard can build the list directly from this socket event.
- New orders do not require a page refresh or a follow-up REST request to appear in the list.

### 3.2 Shop order chat channel

Used for the chat between shop side and customer inside one order.

```text
/ws/chat/order/{order_id}/?token=<JWT>&chat_type=shop_customer
```

Allowed users for `shop_customer` chat:

- `shop_owner`
- `employee`
- `customer`

What happens on connect:

1. The server validates token and order access.
2. It sends a `connection` event.
3. It immediately sends `previous_messages`.

Notes:

- There is no explicit `join_order_room` event.
- Opening the URL is the room subscription itself.
- Closing the socket is the leave action.

## 4. Rooms and Subscription Logic

The shop side does not send `join_order_room` or `leave_order_room`.

Subscription is implicit:

- Opening `/ws/orders/shop/{shop_owner_id}/...` joins the shop dashboard stream
- Opening `/ws/chat/order/{order_id}/...?chat_type=shop_customer` joins one shop-customer chat room

Realtime fan-out rules relevant to the shop:

- `shop_customer` chat messages are broadcast to the order chat room
- The same message is also broadcast to the shop orders dashboard as `new_message`
- `mark_read` updates unread counters and triggers an `order_update` snapshot to the shop dashboard

## 5. Shop Dashboard Events

Server-to-client events on `/ws/orders/shop/{shop_owner_id}/`:

- `connection`
- `orders_snapshot`
- `new_order`
- `order_update`
- `new_message`
- `store_status_updated`
- `driver_status_updated`

The shop dashboard channel does not currently expect any client-to-server events.

### 5.1 `connection`

Sent once after a successful dashboard socket connect.

```json
{
  "type": "connection",
  "shop_owner_id": "2",
  "message": "تم الاتصال بنجاح",
  "message_ar": "تم الاتصال بنجاح",
  "message_en": "Connected successfully"
}
```

### 5.2 `orders_snapshot`

Sent immediately after `connection`.

Current backend behavior:

- Returns the latest 50 orders for that shop
- Sorted by `updated_at` descending
- Uses `OrderSerializer`

```json
{
  "type": "orders_snapshot",
  "data": {
    "orders": [
      {
        "id": 7,
        "order_number": "ODGRQIZA",
        "customer": {
          "id": 4,
          "name": "محمد علي",
          "phone_number": "+201069646266",
          "profile_image": "/media/customer_profile/example.jpg",
          "profile_image_url": "http://86.48.3.103/media/customer_profile/example.jpg",
          "addresses": [],
          "default_address": null,
          "is_online": false,
          "is_verified": true,
          "unread_messages_count": 0,
          "last_message": {
            "content": "فاتورة الطلب العميل: محمد علي العنوان: TEST - TEST",
            "created_at": "2026-03-21T23:08:41+02:00"
          },
          "created_at": "2026-03-21T20:44:00+02:00",
          "updated_at": "2026-03-21T23:08:41+02:00"
        },
        "employee": null,
        "driver": null,
        "status": "new",
        "status_display": "جديد",
        "items": [],
        "total_amount": "0.00",
        "delivery_fee": "0.00",
        "address": "TEST - TEST",
        "notes": "",
        "unread_messages_count": 0,
        "last_message": {
          "id": 31,
          "chat_type": "shop_customer",
          "chat_type_display": "محادثة المحل مع العميل",
          "sender_type": "customer",
          "sender_type_display": "عميل",
          "sender_name": "محمد علي",
          "sender_id": 4,
          "message_type": "text",
          "message_type_display": "نص",
          "content": "فاتورة الطلب العميل: محمد علي العنوان: TEST - TEST",
          "audio_file": null,
          "audio_file_url": null,
          "image_file": null,
          "image_file_url": null,
          "latitude": null,
          "longitude": null,
          "is_read": false,
          "created_at": "2026-03-21T23:08:41+02:00"
        },
        "created_at": "2026-03-21T23:08:41+02:00",
        "updated_at": "2026-03-21T23:08:41+02:00"
      }
    ]
  },
  "message": "تمت مزامنة قائمة الطلبات بنجاح",
  "message_ar": "تمت مزامنة قائمة الطلبات بنجاح",
  "message_en": "Orders list synced successfully"
}
```

Use this event to:

- Render the initial order list
- Fill the latest message preview on each card
- Fill unread counts on each card

### 5.3 `new_order`

Sent when a new order is created for the shop.

Payload shape:

```json
{
  "type": "new_order",
  "data": {
    "...OrderSerializer fields": "same shape as one item inside orders_snapshot.data.orders[]"
  }
}
```

Use this event to:

- Insert the new card at the top
- Update counters
- Optionally auto-select the order

### 5.4 `order_update`

Sent when the order snapshot changes.

Typical reasons:

- status change
- invoice created or edited
- order cancelled
- driver assigned or changed
- unread counters changed
- `mark_read` happened in chat

Payload shape:

```json
{
  "type": "order_update",
  "data": {
    "...OrderSerializer fields": "same shape as one item inside orders_snapshot.data.orders[]"
  }
}
```

Important:

- There is no separate `order_cancelled` event right now.
- Cancellation is delivered through `order_update` where `data.status == "cancelled"`.

### 5.5 `new_message`

Sent to the shop dashboard when a new `shop_customer` chat message is created.

Payload shape:

```json
{
  "type": "new_message",
  "data": {
    "order_id": 7,
    "order_number": "ODGRQIZA",
    "chat_type": "shop_customer",
    "message": {
      "id": 32,
      "order_id": 7,
      "chat_type": "shop_customer",
      "sender_type": "customer",
      "sender_name": "محمد علي",
      "sender_id": 4,
      "message_type": "text",
      "content": "السلام عليكم",
      "latitude": null,
      "longitude": null,
      "is_read": false,
      "created_at": "2026-03-21T23:12:00+02:00",
      "audio_file_url": null,
      "image_file_url": null
    },
    "order": {
      "...OrderSerializer fields": "latest order snapshot after this message"
    }
  }
}
```

Use this event to:

- Update the card preview with the latest message
- Move the order card to the top
- Update unread counters
- Update the open conversation if the same order is selected

### 5.6 `store_status_updated`

Sent when the shop status is updated from REST.

Payload shape:

```json
{
  "type": "store_status_updated",
  "data": {
    "shop_owner_id": 2,
    "id": 3,
    "status": "open",
    "status_display": "مفتوح",
    "updated_at": "2026-03-21T23:15:00+02:00"
  }
}
```

Serializer source:

- `ShopStatusSerializer`

### 5.7 `driver_status_updated`

Sent to shops related to that driver.

Payload shape:

```json
{
  "type": "driver_status_updated",
  "data": {
    "shop_owner_ids": [2],
    "driver": {
      "id": 9,
      "name": "خالد سمير",
      "phone_number": "01000000000",
      "profile_image": "/media/drivers/driver.jpg",
      "profile_image_url": "http://86.48.3.103/media/drivers/driver.jpg",
      "status": "available",
      "status_display": "متاح",
      "current_orders_count": 1,
      "rating": "4.50",
      "total_rides": 22,
      "created_at": "2026-03-21T20:00:00+02:00",
      "updated_at": "2026-03-21T23:16:00+02:00"
    }
  }
}
```

Serializer source:

- `DriverSerializer`

## 6. Shop Chat Events

Server-to-client events on `/ws/chat/order/{order_id}/?token=<JWT>&chat_type=shop_customer`:

- `connection`
- `previous_messages`
- `chat_message`
- `messages_read`
- `typing`
- `ack`
- `error`

Client-to-server events supported on this channel:

- `send_message`
- `chat_message` (legacy compatibility)
- `location`
- `mark_read`
- `typing`

### 6.1 `connection`

```json
{
  "type": "connection",
  "order_id": "7",
  "chat_type": "shop_customer",
  "user_type": "shop_owner",
  "message": "تم الاتصال بنجاح",
  "message_ar": "تم الاتصال بنجاح",
  "message_en": "Connected successfully"
}
```

### 6.2 `previous_messages`

Sent immediately after a successful chat connect.

Current backend behavior:

- Returns up to the last 50 messages
- Filtered by `order_id`
- Filtered by `chat_type=shop_customer`
- Ordered ascending by `created_at`

```json
{
  "type": "previous_messages",
  "messages": [
    {
      "id": 31,
      "order_id": 7,
      "chat_type": "shop_customer",
      "sender_type": "customer",
      "sender_name": "محمد علي",
      "sender_id": 4,
      "message_type": "text",
      "content": "السلام عليكم",
      "latitude": null,
      "longitude": null,
      "is_read": false,
      "created_at": "2026-03-21T23:12:00+02:00",
      "audio_file_url": null,
      "image_file_url": null
    }
  ]
}
```

### 6.3 Client event: `send_message`

Recommended event for sending text messages:

```json
{
  "type": "send_message",
  "request_id": "msg-101",
  "message_type": "text",
  "content": "تم إنشاء الفاتورة"
}
```

Notes:

- Only `text` and `location` are supported directly over WebSocket
- `audio` and `image` are not uploaded over this socket

### 6.4 Client event: legacy `chat_message`

Still accepted for compatibility:

```json
{
  "type": "chat_message",
  "request_id": "msg-101",
  "message_type": "text",
  "content": "تم إنشاء الفاتورة"
}
```

### 6.5 Client event: `location`

```json
{
  "type": "location",
  "request_id": "loc-55",
  "latitude": "30.0444",
  "longitude": "31.2357",
  "content": "موقعي الحالي"
}
```

### 6.6 Client event: `mark_read`

```json
{
  "type": "mark_read",
  "request_id": "read-7"
}
```

Result:

- Chat room receives `messages_read`
- Client that sent the request also receives `ack`
- Shop dashboard receives `order_update` with fresh unread counters

### 6.7 Client event: `typing`

```json
{
  "type": "typing",
  "is_typing": true
}
```

### 6.8 Server event: `chat_message`

Broadcast to all subscribers in that order chat room.

```json
{
  "type": "chat_message",
  "data": {
    "id": 32,
    "order_id": 7,
    "chat_type": "shop_customer",
    "sender_type": "shop_owner",
    "sender_name": "شاورما",
    "sender_id": 2,
    "message_type": "text",
    "content": "تم إنشاء الفاتورة",
    "latitude": null,
    "longitude": null,
    "is_read": false,
    "created_at": "2026-03-21T23:20:00+02:00",
    "audio_file_url": null,
    "image_file_url": null
  }
}
```

### 6.9 Server event: `messages_read`

```json
{
  "type": "messages_read",
  "order_id": "7",
  "reader_type": "shop_owner",
  "count": 3
}
```

### 6.10 Server event: `typing`

```json
{
  "type": "typing",
  "user_type": "customer",
  "user_name": "محمد علي",
  "is_typing": true
}
```

### 6.11 Server event: `ack`

Used for successful client actions such as `send_message`, `chat_message`, `location`, and `mark_read`.

```json
{
  "type": "ack",
  "action": "send_message",
  "success": true,
  "request_id": "msg-101",
  "data": {
    "message_id": 32,
    "order_id": 7,
    "chat_type": "shop_customer"
  },
  "message": "تم تنفيذ الطلب بنجاح",
  "message_ar": "تم تنفيذ الطلب بنجاح",
  "message_en": "Request completed successfully"
}
```

For `mark_read`:

```json
{
  "type": "ack",
  "action": "mark_read",
  "success": true,
  "request_id": "read-7",
  "data": {
    "order_id": 7,
    "count": 3
  },
  "message": "تم تنفيذ الطلب بنجاح",
  "message_ar": "تم تنفيذ الطلب بنجاح",
  "message_en": "Request completed successfully"
}
```

### 6.12 Server event: `error`

Used when the client sends invalid or unsupported data.

Examples of error codes from current backend:

- `UNKNOWN_EVENT`
- `INVALID_JSON`
- `UNSUPPORTED_MESSAGE_TYPE`
- `MESSAGE_CONTENT_REQUIRED`
- `LOCATION_COORDINATES_REQUIRED`
- `MESSAGE_SAVE_FAILED`
- `UNEXPECTED_ERROR`

Example payload:

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

## 7. Media Messages for Shop Chat

Image and audio uploads are not sent through the WebSocket payload directly.

Current backend behavior:

- WebSocket supports direct send for `text` and `location`
- Media upload happens through REST
- After REST upload succeeds, the backend broadcasts the created media message to websocket subscribers

REST endpoint:

```text
POST /api/chat/order/{order_id}/send-media/
```

Required form-data:

- `chat_type=shop_customer`
- exactly one of:
  - `image_file`
  - `audio_file`

Optional:

- `content`

Then the shop chat socket receives normal `chat_message`, and the shop dashboard receives `new_message`.

## 8. Order Data Shape Used by Shop Sockets

`orders_snapshot`, `new_order`, and `order_update` all use `OrderSerializer`.

Important top-level fields:

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

Useful fields for rendering the shop order card:

- `data.id`
- `data.order_number`
- `data.status`
- `data.status_display`
- `data.customer.name`
- `data.customer.profile_image_url`
- `data.last_message.content`
- `data.last_message.created_at`
- `data.unread_messages_count`
- `data.updated_at`

## 9. Source of Truth

For the current shop dashboard implementation:

- Order list initial state can come directly from `orders_snapshot`
- Live list updates come from the shop dashboard WebSocket events
- Chat history initial state comes from `previous_messages`
- Live chat updates come from the chat WebSocket events

Current UI note:

- The order list can be fully websocket-driven
- The selected order detail panel may still use REST in the current dashboard implementation when opening an order

## 10. Reconnect Behavior

Current expected client behavior:

### Dashboard orders socket

- Reopen `/ws/orders/shop/{shop_owner_id}/?token=<JWT>` after disconnect
- Wait for `connection`
- Consume the fresh `orders_snapshot`
- Resume live handling of `new_order`, `order_update`, and `new_message`

### Shop chat socket

- Reopen `/ws/chat/order/{order_id}/?token=<JWT>&chat_type=shop_customer` after disconnect
- Wait for `connection`
- Consume `previous_messages`
- Resume live handling of `chat_message`, `messages_read`, `typing`, `ack`, and `error`

No extra room rejoin event is required after reconnect.

## 11. Current Naming Notes

Current backend event names for shop integrations are:

- `orders_snapshot`
- `new_order`
- `order_update`
- `new_message`
- `store_status_updated`
- `driver_status_updated`
- `chat_message`
- `messages_read`
- `typing`
- `ack`
- `error`

Important naming notes:

- The backend currently uses `order_update`, not `order_updated`
- The backend currently uses `mark_read`, not `mark_message_seen`
- There is no separate `order_cancelled` event; cancellation comes through `order_update`

## 12. Shop UI Action Map

The shop UI buttons do not all map to standalone websocket event names.

Important rule:

- Some actions are sent directly through WebSocket
- Some actions are sent through REST
- After successful REST actions, the backend pushes realtime websocket updates back to the shop UI

### 12.1 `نصي`

Purpose:

- Send a normal text message in the order chat

Transport:

- WebSocket

Socket:

- `/ws/chat/order/{order_id}/?token=<JWT>&chat_type=shop_customer`

Client payload:

```json
{
  "type": "send_message",
  "request_id": "msg-101",
  "message_type": "text",
  "content": "تم إنشاء الفاتورة"
}
```

Realtime result:

- Chat room receives `chat_message`
- Sender receives `ack`
- Shop orders list receives `new_message`

### 12.2 `ملف صوتي`

Purpose:

- Upload an audio message in shop-customer chat

Transport:

- REST upload, then backend broadcasts through WebSocket

Endpoint:

```text
POST /api/chat/order/{order_id}/send-media/
```

Form-data:

- `chat_type=shop_customer`
- `audio_file`
- optional `content`

Realtime result after successful upload:

- Chat room receives `chat_message` with `message_type=audio`
- Shop orders list receives `new_message`

### 12.3 `صورة`

Purpose:

- Upload an image message in shop-customer chat

Transport:

- REST upload, then backend broadcasts through WebSocket

Endpoint:

```text
POST /api/chat/order/{order_id}/send-media/
```

Form-data:

- `chat_type=shop_customer`
- `image_file`
- optional `content`

Realtime result after successful upload:

- Chat room receives `chat_message` with `message_type=image`
- Shop orders list receives `new_message`

### 12.4 `موقعي` / `إرسال موقع`

Purpose:

- Send a location message from the shop side inside the chat

Transport:

- WebSocket

Socket:

- `/ws/chat/order/{order_id}/?token=<JWT>&chat_type=shop_customer`

Client payload:

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
- Shop orders list receives `new_message`

### 12.5 `إنشاء فاتورة`

Purpose:

- Create and send the priced invoice to the customer

Transport:

- REST

Endpoint:

```text
PUT /api/shop/orders/{order_id}/
```

Request body:

```json
{
  "status": "pending_customer_confirm",
  "items": [
    "Item 1 - price: 60.00",
    "Item 2 - price: 45.00"
  ],
  "delivery_fee": "15.00",
  "total_amount": "120.00",
  "notes": "Optional notes"
}
```

Realtime result:

- Shop orders list receives `order_update`
- Shop chat receives system `chat_message`
- Shop orders list also receives `new_message` for the system invoice message

Notes:

- `total_amount` must be greater than `0`
- This moves the order to `pending_customer_confirm`

### 12.6 `تعديل الفاتورة`

Purpose:

- Edit an already sent invoice and resend it to the customer

Transport:

- REST

Endpoint:

```text
PUT /api/shop/orders/{order_id}/
```

Request body:

```json
{
  "status": "pending_customer_confirm",
  "items": [
    "Updated item 1",
    "Updated item 2"
  ],
  "delivery_fee": "20.00",
  "total_amount": "140.00",
  "notes": "Updated notes"
}
```

Realtime result:

- Shop orders list receives `order_update`
- Shop chat receives system `chat_message`
- Shop orders list receives `new_message`

Rules:

- Allowed while the order is still waiting for customer confirmation
- Not allowed after the customer confirms
- Not allowed after the order is delivered or cancelled

### 12.7 `إلغاء الفاتورة` / `إلغاء استلام الأوردر`

Purpose:

- Cancel the order before the customer confirms the invoice

Transport:

- REST

Endpoint:

```text
PUT /api/shop/orders/{order_id}/
```

Request body:

```json
{
  "status": "cancelled"
}
```

Realtime result:

- Shop orders list receives `order_update` with `status=cancelled`
- Shop chat receives system `chat_message`
- Shop orders list receives `new_message`

Rules:

- Allowed only before customer confirmation
- There is no separate websocket event named `order_cancelled`
- Cancellation is delivered through `order_update`

### 12.8 `تحويل الأوردر للدليفري`

Purpose:

- Assign the order to a driver and move operational status forward

Transport:

- REST

Endpoint:

```text
PUT /api/shop/orders/{order_id}/
```

Example request body:

```json
{
  "driver_id": 1,
  "status": "preparing"
}
```

You can also move later to:

- `status=on_way`

Realtime result:

- Shop orders list receives `order_update`
- If a new driver is assigned, driver channel receives `new_order`
- Shop chat may receive a system `chat_message` like driver assignment notice
- Shop orders list may receive `new_message`
- Shop dashboard receives `driver_status_updated`

Rules:

- Not allowed before customer confirmation
- Driver assignment is valid only when current status is one of:
  - `confirmed`
  - `preparing`
  - `on_way`

### 12.9 Customer confirmation or rejection impact on shop UI

These buttons are on the customer side, not the shop side, but the shop must handle their websocket effects.

Customer REST endpoints:

- `POST /api/customer/orders/{id}/confirm/`
- `POST /api/customer/orders/{id}/reject/`

Realtime effect seen by the shop:

- `order_update`
- `new_message`

Meaning:

- If the customer confirms, the shop order status becomes `confirmed`
- If the customer rejects, the shop order status becomes `cancelled`
