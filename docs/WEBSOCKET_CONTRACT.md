# WebSocket Contract

This document is the source of truth for realtime integrations in Mr Delivery.

The backend uses native WebSocket, not Socket.IO.

## 1. Socket Type

- Protocol: native WebSocket
- Development base: `ws://<host>/ws/`
- Production base: `wss://<host>/ws/`

## 2. Authentication

All sockets require a JWT access token in the query string:

```text
?token=<JWT_ACCESS_TOKEN>
```

Notes:

- Invalid or missing token: connection closes with `4401`
- Authenticated user without permission for the target channel: connection closes with `4403`
- Unexpected server error during connect: connection closes with `1011`

## 3. Channels

### 3.1 Shop dashboard orders channel

Used by shop owner and employees for realtime dashboard updates.

```text
/ws/orders/shop/{shop_owner_id}/?token=<JWT>
```

Server to client events on this channel:

- `connection`
- `new_order`
- `order_update`
- `new_message`
- `store_status_updated`
- `driver_status_updated`

### 3.2 Customer orders channel

Used by the customer app for live order changes.

```text
/ws/orders/customer/{customer_id}/?token=<JWT>
```

Server to client events on this channel:

- `connection`
- `order_update`
- `new_message`
- `driver_location`

### 3.3 Driver channel

Used by the driver app for live assignments and sending location updates.

```text
/ws/driver/{driver_id}/?token=<JWT>
```

Client to server events on this channel:

- `location_update`

Server to client events on this channel:

- `connection`
- `new_order`
- `order_update`
- `new_message`

### 3.4 Order chat channel

Used for per-order chat threads.

```text
/ws/chat/order/{order_id}/?token=<JWT>&chat_type=shop_customer
```

or

```text
/ws/chat/order/{order_id}/?token=<JWT>&chat_type=driver_customer
```

Valid `chat_type` values:

- `shop_customer`
- `driver_customer`

Server to client events on this channel:

- `connection`
- `previous_messages`
- `chat_message`
- `messages_read`
- `typing`
- `ack`
- `error`

Client to server events on this channel:

- `chat_message`
- `send_message`
- `location`
- `mark_read`
- `typing`

## 4. Rooms and Subscription Logic

There is no explicit `join_order_room` or `leave_order_room` event right now.

Room subscription is implicit from the URL:

- Opening `/ws/chat/order/{order_id}/...` joins one order chat room
- Opening `/ws/orders/shop/{shop_owner_id}/...` joins the shop dashboard stream
- Opening `/ws/orders/customer/{customer_id}/...` joins the customer order stream
- Opening `/ws/driver/{driver_id}/...` joins the driver stream

Realtime routing rules:

- `shop_customer` chat messages fan out to the chat room, the shop dashboard channel, and the customer orders channel
- `driver_customer` chat messages fan out to the chat room, the driver channel, and the customer orders channel

## 5. Event Naming Convention

The backend currently uses underscore event names consistently:

- `new_order`
- `order_update`
- `new_message`
- `store_status_updated`
- `driver_status_updated`
- `chat_message`
- `messages_read`
- `driver_location`

Invoice changes and cancellations are delivered through `order_update` with the latest order snapshot and `status` field.

## 6. Payload Contracts

### 6.1 Connection

Shop dashboard connection:

```json
{
  "type": "connection",
  "shop_owner_id": "12",
  "message": "تم الاتصال بنجاح"
}
```

Chat connection:

```json
{
  "type": "connection",
  "order_id": "12345",
  "chat_type": "shop_customer",
  "user_type": "shop_owner",
  "message": "تم الاتصال بنجاح"
}
```

### 6.2 Previous messages

Sent immediately after chat connect. The backend always sends this event, even if the list is empty.

```json
{
  "type": "previous_messages",
  "messages": [
    {
      "id": 11,
      "order_id": 12345,
      "chat_type": "shop_customer",
      "sender_type": "customer",
      "sender_name": "Ahmed",
      "sender_id": 77,
      "message_type": "text",
      "content": "السلام عليكم",
      "latitude": null,
      "longitude": null,
      "is_read": false,
      "created_at": "2026-03-21T18:15:00+00:00",
      "audio_file_url": null,
      "image_file_url": null
    }
  ]
}
```

### 6.3 Client -> server chat send

Recommended text payload:

```json
{
  "type": "send_message",
  "request_id": "msg-123",
  "message_type": "text",
  "content": "تم إنشاء الفاتورة"
}
```

Supported compatibility payload:

```json
{
  "type": "chat_message",
  "request_id": "msg-123",
  "message_type": "text",
  "content": "تم إنشاء الفاتورة"
}
```

Location payload:

```json
{
  "type": "location",
  "request_id": "loc-55",
  "latitude": "30.0444",
  "longitude": "31.2357",
  "content": "موقعي الحالي"
}
```

### 6.4 Chat message broadcast

```json
{
  "type": "chat_message",
  "data": {
    "id": 12,
    "order_id": 12345,
    "chat_type": "shop_customer",
    "sender_type": "shop_owner",
    "sender_name": "My Shop",
    "sender_id": 12,
    "message_type": "text",
    "content": "تم إنشاء الفاتورة",
    "latitude": null,
    "longitude": null,
    "is_read": false,
    "created_at": "2026-03-21T18:16:00+00:00",
    "audio_file_url": null,
    "image_file_url": null
  }
}
```

### 6.5 Ack

Ack is sent only for chat channel actions that mutate server state.

```json
{
  "type": "ack",
  "action": "send_message",
  "success": true,
  "request_id": "msg-123",
  "message": "تم تنفيذ الطلب بنجاح",
  "data": {
    "message_id": 12,
    "order_id": 12345,
    "chat_type": "shop_customer"
  }
}
```

For `mark_read`:

```json
{
  "type": "ack",
  "action": "mark_read",
  "success": true,
  "request_id": "read-1",
  "message": "تم تنفيذ الطلب بنجاح",
  "data": {
    "order_id": 12345,
    "count": 4
  }
}
```

### 6.6 Error

```json
{
  "type": "error",
  "success": false,
  "code": "MESSAGE_CONTENT_REQUIRED",
  "request_id": "msg-123",
  "message": "محتوى الرسالة مطلوب"
}
```

Possible `code` values currently produced by the backend:

- `INVALID_JSON`
- `UNKNOWN_EVENT`
- `UNSUPPORTED_MESSAGE_TYPE`
- `MESSAGE_CONTENT_REQUIRED`
- `LOCATION_COORDINATES_REQUIRED`
- `MESSAGE_SAVE_FAILED`
- `UNEXPECTED_ERROR`

### 6.7 Messages read

```json
{
  "type": "messages_read",
  "order_id": "12345",
  "reader_type": "shop_owner",
  "count": 4
}
```

Client request:

```json
{
  "type": "mark_read",
  "request_id": "read-1"
}
```

### 6.8 Typing

Client request:

```json
{
  "type": "typing",
  "is_typing": true
}
```

Server broadcast:

```json
{
  "type": "typing",
  "user_type": "customer",
  "user_name": "Ahmed",
  "is_typing": true
}
```

### 6.9 New order

Sent to the shop dashboard channel when a customer creates a new order.

```json
{
  "type": "new_order",
  "data": {
    "id": 12345,
    "order_number": "ODABC123",
    "status": "new",
    "status_display": "جديد",
    "total_amount": "250.00",
    "delivery_fee": "20.00",
    "unread_messages_count": 1,
    "created_at": "2026-03-21T18:10:00+00:00",
    "updated_at": "2026-03-21T18:10:00+00:00",
    "customer": {
      "id": 77,
      "name": "Ahmed"
    }
  }
}
```

### 6.10 Order update

Used for:

- status changes
- invoice created/edited/sent
- customer confirmation
- customer rejection/cancellation
- driver assignment changes
- unread-count refresh after `mark_read`

```json
{
  "type": "order_update",
  "data": {
    "id": 12345,
    "order_number": "ODABC123",
    "status": "pending_customer_confirm",
    "status_display": "في انتظار تأكيد العميل",
    "items": [
      "دجاج مشوي",
      "بيبسي"
    ],
    "total_amount": "250.00",
    "delivery_fee": "20.00",
    "unread_messages_count": 0,
    "last_message": {
      "id": 12,
      "message_type": "text",
      "content": "تم إنشاء الفاتورة"
    },
    "created_at": "2026-03-21T18:10:00+00:00",
    "updated_at": "2026-03-21T18:16:00+00:00"
  }
}
```

### 6.11 New message for list/dashboard channels

This event is sent to the non-chat channels so list screens can update preview text, unread badge, and ordering.

```json
{
  "type": "new_message",
  "data": {
    "order_id": 12345,
    "order_number": "ODABC123",
    "chat_type": "shop_customer",
    "message": {
      "id": 12,
      "order_id": 12345,
      "chat_type": "shop_customer",
      "sender_type": "customer",
      "sender_name": "Ahmed",
      "sender_id": 77,
      "message_type": "text",
      "content": "السلام عليكم",
      "latitude": null,
      "longitude": null,
      "is_read": false,
      "created_at": "2026-03-21T18:16:00+00:00",
      "audio_file_url": null,
      "image_file_url": null
    },
    "order": {
      "id": 12345,
      "order_number": "ODABC123",
      "status": "new",
      "unread_messages_count": 1,
      "last_message": {
        "id": 12,
        "content": "السلام عليكم"
      }
    }
  }
}
```

### 6.12 Driver location

Driver sends on driver channel:

```json
{
  "type": "location_update",
  "latitude": "30.0444",
  "longitude": "31.2357"
}
```

Customers receive on customer orders channel:

```json
{
  "type": "driver_location",
  "data": {
    "driver_id": "9",
    "latitude": "30.0444",
    "longitude": "31.2357",
    "updated_at": "2026-03-21T18:20:00+00:00"
  }
}
```

### 6.13 Store status updated

Sent on the shop dashboard channel when `/api/shop/status/` is updated.

```json
{
  "type": "store_status_updated",
  "data": {
    "shop_owner_id": 12,
    "id": 3,
    "status": "open",
    "status_display": "مفتوح",
    "updated_at": "2026-03-21T18:22:00+00:00"
  }
}
```

### 6.14 Driver status updated

Sent on the shop dashboard channel when driver status changes or driver load changes.

```json
{
  "type": "driver_status_updated",
  "data": {
    "shop_owner_ids": [
      12
    ],
    "driver": {
      "id": 9,
      "name": "Mohamed Ali",
      "phone_number": "01000000000",
      "status": "available",
      "status_display": "متاح",
      "current_orders_count": 2,
      "rating": "4.80",
      "total_rides": 35,
      "created_at": "2026-03-01T10:00:00+00:00",
      "updated_at": "2026-03-21T18:22:00+00:00"
    }
  }
}
```

## 7. Media Upload Rule

Image and audio are still sent via REST, not through WebSocket frames:

```text
POST /api/chat/order/{order_id}/send-media/
```

After the REST upload succeeds, the backend broadcasts the new chat message over WebSocket automatically.

## 8. Reconnect Behavior

The client should assume WebSocket sessions are stateless.

Recommended client behavior:

1. Reconnect with exponential backoff
2. Re-open all required channels after reconnect
3. Re-open the order chat URL again for each active order screen
4. Re-fetch order list/detail/history from REST after reconnect
5. Then resume using WebSocket for live updates only

Important:

- The server does not keep room membership across disconnects
- Missed events are not replayed automatically
- After reconnect, REST should be used to fill any gap

## 9. Source of Truth

Recommended contract between frontend and backend:

- REST API = source of truth for initial data, history, pagination, and refresh
- WebSocket = live updates only

Typical split:

- REST: order list, order details, older messages, invoice data, staff lists
- WebSocket: new order, order update, new message, read state, driver location, store status, driver status

## 10. Realtime Use Cases Covered

- New order reaches the shop dashboard immediately
- Order status changes reach all subscribed parties immediately
- Chat messages inside an order appear immediately
- Shop dashboard receives store status changes immediately
- Shop dashboard receives driver status/load changes immediately
- Customer tracking receives driver location immediately
- Invoice send/edit/cancel flows appear through `order_update`

## 11. Recommended Flutter Split

- `OrdersSocketService` -> `/ws/orders/shop/{shop_owner_id}/`
- `ChatSocketService` -> `/ws/chat/order/{order_id}/`
- `CustomerOrdersSocketService` -> `/ws/orders/customer/{customer_id}/`
- `DriverSocketService` -> `/ws/driver/{driver_id}/`

For the shop dashboard in particular:

- Keep one long-lived orders socket after login
- Open one chat socket per opened order details screen
- Use REST for initial order list/details
- Use `new_message` to update list cards and unread counts in realtime
