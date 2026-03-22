# Customer WebSocket Contract

This document is the dedicated source of truth for the customer-side realtime integration only.

It covers:

- Customer orders socket
- Customer chat with shop
- Customer chat with driver
- Driver live location updates
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

Connection close codes used by the backend:

- `4401`: missing or invalid token
- `4403`: authenticated user does not have access to this order/chat
- `1011`: unexpected server error during connect

Supported user:

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

Important:

- The customer orders socket does not currently send an initial snapshot.
- Initial orders list should come from REST.
- Realtime changes then arrive through this socket.

Recommended initial REST source:

```text
GET /api/customer/orders/
```

Customer companion endpoints for the app tabs:

```text
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

## 4. Rooms and Subscription Logic

There is no explicit `join_order_room` or `leave_order_room`.

Subscription is implicit:

- Opening `/ws/orders/customer/{customer_id}/...` joins the customer orders stream
- Opening `/ws/chat/order/{order_id}/...?chat_type=shop_customer` joins the shop-customer chat room
- Opening `/ws/chat/order/{order_id}/...?chat_type=driver_customer` joins the driver-customer chat room

Realtime fan-out rules relevant to the customer:

- `shop_customer` chat messages are broadcast to the chat room and the customer orders channel
- `driver_customer` chat messages are broadcast to the chat room and the customer orders channel
- Driver live location updates are pushed to the customer orders channel

## 5. Customer Orders Socket Events

Server-to-client events on `/ws/orders/customer/{customer_id}/`:

- `connection`
- `order_update`
- `new_message`
- `driver_location`

The customer orders channel does not currently expect any client-to-server events.

### 5.1 `connection`

Sent once after a successful customer orders socket connect.

```json
{
  "type": "connection",
  "message": "تم الاتصال بنجاح",
  "message_ar": "تم الاتصال بنجاح",
  "message_en": "Connected successfully"
}
```

### 5.2 `order_update`

Sent when the order snapshot changes.

Typical reasons:

- invoice created or edited by shop
- invoice cancelled
- customer confirmed invoice
- customer rejected invoice
- driver assigned or changed
- delivery status moved to `preparing` or `on_way`
- unread counters changed after chat read actions

Payload shape:

```json
{
  "type": "order_update",
  "data": {
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
        "content": "تمت الموافقة على الفاتورة من العميل",
        "created_at": "2026-03-22T00:10:00+02:00"
      },
      "created_at": "2026-03-21T20:44:00+02:00",
      "updated_at": "2026-03-22T00:10:00+02:00"
    },
    "employee": null,
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
      "updated_at": "2026-03-22T00:09:00+02:00"
    },
    "status": "confirmed",
    "status_display": "مؤكد",
    "items": [
      "Item 1 - price: 60.00",
      "Item 2 - price: 45.00"
    ],
    "total_amount": "120.00",
    "delivery_fee": "15.00",
    "address": "TEST - TEST",
    "notes": "",
    "unread_messages_count": 0,
    "last_message": {
      "id": 35,
      "chat_type": "shop_customer",
      "chat_type_display": "محادثة المحل مع العميل",
      "sender_type": "customer",
      "sender_type_display": "عميل",
      "sender_name": "محمد علي",
      "sender_id": 4,
      "message_type": "text",
      "message_type_display": "نص",
      "content": "تمت الموافقة على الفاتورة من العميل",
      "audio_file": null,
      "audio_file_url": null,
      "image_file": null,
      "image_file_url": null,
      "latitude": null,
      "longitude": null,
      "is_read": false,
      "created_at": "2026-03-22T00:10:00+02:00"
    },
    "created_at": "2026-03-21T23:08:41+02:00",
    "updated_at": "2026-03-22T00:10:00+02:00"
  }
}
```

Important:

- There is no separate `order_cancelled` event.
- Cancellation is delivered through `order_update` where `data.status == "cancelled"`.

### 5.3 `new_message`

Sent when a new chat message is created for this customer's order.

This can come from:

- `shop_customer` chat
- `driver_customer` chat

Payload shape:

```json
{
  "type": "new_message",
  "data": {
    "order_id": 7,
    "order_number": "ODGRQIZA",
    "chat_type": "shop_customer",
    "message": {
      "id": 36,
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
      "created_at": "2026-03-22T00:12:00+02:00",
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

- Update the last message preview in the customer order list
- Update unread counters
- Update the open conversation if the same order and same chat type are active

### 5.4 `driver_location`

Sent when the driver updates location while the order is active.

Payload shape:

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

Use this event to:

- Move the live driver marker on the map
- Refresh delivery tracking UI

## 6. Customer Chat Events

Server-to-client events on both:

- `/ws/chat/order/{order_id}/?token=<JWT>&chat_type=shop_customer`
- `/ws/chat/order/{order_id}/?token=<JWT>&chat_type=driver_customer`

Server-to-client events:

- `connection`
- `previous_messages`
- `chat_message`
- `messages_read`
- `typing`
- `ack`
- `error`

Client-to-server events:

- `send_message`
- `chat_message` (legacy compatibility)
- `location`
- `mark_read`
- `typing`

### 6.1 `connection`

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

### 6.2 `previous_messages`

Sent immediately after a successful chat connect.

Current backend behavior:

- Returns up to the last 50 messages
- Filtered by `order_id`
- Filtered by the selected `chat_type`
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
      "created_at": "2026-03-22T00:02:00+02:00",
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
  "content": "تمام"
}
```

Works on:

- `chat_type=shop_customer`
- `chat_type=driver_customer`

### 6.4 Client event: legacy `chat_message`

Still accepted for compatibility:

```json
{
  "type": "chat_message",
  "request_id": "msg-101",
  "message_type": "text",
  "content": "تمام"
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
- Sender receives `ack`
- Related order streams receive `order_update` with fresh unread counters

### 6.7 Client event: `typing`

```json
{
  "type": "typing",
  "is_typing": true
}
```

### 6.8 Server event: `chat_message`

Example:

```json
{
  "type": "chat_message",
  "data": {
    "id": 36,
    "order_id": 7,
    "chat_type": "driver_customer",
    "sender_type": "driver",
    "sender_name": "خالد سمير",
    "sender_id": 9,
    "message_type": "text",
    "content": "أنا قريب منك",
    "latitude": null,
    "longitude": null,
    "is_read": false,
    "created_at": "2026-03-22T00:20:00+02:00",
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
  "reader_type": "customer",
  "count": 3
}
```

### 6.10 Server event: `typing`

Example for shop chat:

```json
{
  "type": "typing",
  "user_type": "shop_owner",
  "user_name": "شاورما",
  "is_typing": true
}
```

Example for driver chat:

```json
{
  "type": "typing",
  "user_type": "driver",
  "user_name": "خالد سمير",
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
    "message_id": 36,
    "order_id": 7,
    "chat_type": "shop_customer"
  },
  "message": "تم تنفيذ الطلب بنجاح",
  "message_ar": "تم تنفيذ الطلب بنجاح",
  "message_en": "Request completed successfully"
}
```

### 6.12 Server event: `error`

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

## 7. Media Messages for Customer Chat

Image and audio uploads are not sent through the websocket payload directly.

Current backend behavior:

- WebSocket supports direct send for `text` and `location`
- Media upload happens through REST
- After REST upload succeeds, the backend broadcasts the created media message to websocket subscribers

REST endpoint:

```text
POST /api/chat/order/{order_id}/send-media/
```

Required form-data:

- `chat_type=shop_customer` or `chat_type=driver_customer`
- exactly one of:
  - `image_file`
  - `audio_file`

Optional:

- `content`

Then:

- The active chat socket receives `chat_message`
- The customer orders socket receives `new_message`

## 8. Order Data Shape Used by Customer Sockets

`order_update` uses `OrderSerializer`.

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

Useful fields for customer order cards:

- `data.id`
- `data.order_number`
- `data.status`
- `data.status_display`
- `data.last_message.content`
- `data.last_message.created_at`
- `data.unread_messages_count`
- `data.total_amount`
- `data.delivery_fee`
- `data.driver.name`
- `data.updated_at`

## 9. Source of Truth

For the current customer-side behavior:

- Initial orders list should come from `GET /api/customer/orders/`
- Shops tab can use `GET /api/customer/shops-conversations/`
- Active delivery / on-way tab can use `GET /api/customer/orders/on-way/`
- Live order changes come from `/ws/orders/customer/{customer_id}/`
- Initial chat history comes from `previous_messages`
- Live chat updates come from the chat websocket channels
- Driver live tracking comes from `driver_location` events on the customer orders socket

Fallback tracking REST endpoint:

```text
GET /api/orders/{order_id}/track/
```

## 10. Reconnect Behavior

Current expected client behavior:

### Customer orders socket

- Reopen `/ws/orders/customer/{customer_id}/?token=<JWT>` after disconnect
- Wait for `connection`
- Refresh the current order list from REST if needed, because this socket does not send snapshot on reconnect
- Resume live handling of `order_update`, `new_message`, and `driver_location`

### Customer chat sockets

- Reopen the needed chat URL after disconnect
- Wait for `connection`
- Consume `previous_messages`
- Resume live handling of `chat_message`, `messages_read`, `typing`, `ack`, and `error`

No extra room rejoin event is required after reconnect.

## 11. Current Naming Notes

Current backend event names for customer integrations are:

- `order_update`
- `new_message`
- `driver_location`
- `chat_message`
- `messages_read`
- `typing`
- `ack`
- `error`

Important naming notes:

- The backend currently uses `order_update`, not `order_updated`
- The backend currently uses `mark_read`, not `mark_message_seen`
- There is no separate `order_cancelled` event; cancellation comes through `order_update`

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

Request body:

```json
{
  "address": "TEST - TEST",
  "items": [
    "Item 1",
    "Item 2"
  ],
  "notes": "Optional notes",
  "phone_number": "01000000000"
}
```

Backend behavior:

- Creates the order with `status=new`
- Creates the first chat message in `shop_customer`
- Broadcasts that first message realtime

Realtime result:

- Shop dashboard receives `new_order`
- Shop and customer flows receive the first `new_message`

Automatic status message after creation:

- The backend also creates a static system message for the customer:
  - `تم استلام طلبك ويرجى الانتظار حتى يتم إرسال الفاتورة.`
- This is not a message the shop needs to type manually

Client note:

- The REST response itself should also be used to insert the new order locally

### 12.2 Send text message

Purpose:

- Send a normal chat message to shop or driver

Transport:

- WebSocket

Socket:

- `/ws/chat/order/{order_id}/?token=<JWT>&chat_type=shop_customer`
- `/ws/chat/order/{order_id}/?token=<JWT>&chat_type=driver_customer`

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
- Customer orders list receives `new_message`

### 12.3 Send audio file

Transport:

- REST upload, then websocket broadcast

Endpoint:

```text
POST /api/chat/order/{order_id}/send-media/
```

Form-data:

- `chat_type=shop_customer` or `chat_type=driver_customer`
- `audio_file`
- optional `content`

Realtime result:

- Chat room receives `chat_message` with `message_type=audio`
- Customer orders list receives `new_message`

### 12.4 Send image

Transport:

- REST upload, then websocket broadcast

Endpoint:

```text
POST /api/chat/order/{order_id}/send-media/
```

Form-data:

- `chat_type=shop_customer` or `chat_type=driver_customer`
- `image_file`
- optional `content`

Realtime result:

- Chat room receives `chat_message` with `message_type=image`
- Customer orders list receives `new_message`

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
- Customer orders list receives `new_message`

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
- Related order streams receive `order_update`

### 12.7 Confirm invoice

Purpose:

- Customer accepts the priced invoice

Transport:

- REST

Endpoint:

```text
POST /api/customer/orders/{order_id}/confirm/
```

Realtime result:

- Customer orders socket receives `order_update` with `status=confirmed`
- Shop and customer flows receive `new_message` for the system confirmation message

### 12.8 Reject invoice

Purpose:

- Customer rejects the priced invoice

Transport:

- REST

Endpoint:

```text
POST /api/customer/orders/{order_id}/reject/
```

Realtime result:

- Customer orders socket receives `order_update` with `status=cancelled`
- Shop and customer flows receive `new_message` for the system rejection message

### 12.9 Track driver live

Primary realtime source:

- Customer orders socket `driver_location`

Fallback REST endpoint:

```text
GET /api/orders/{order_id}/track/
```

Use this when:

- The screen opens after reconnect
- You want the latest known driver coordinates immediately before waiting for the next websocket push

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

- These are static workflow/status messages generated automatically by the server
- They are not expected to be typed manually by shop staff
