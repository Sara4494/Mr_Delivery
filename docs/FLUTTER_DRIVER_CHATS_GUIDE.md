# Flutter Driver-Customer Chat Guide

This file now has two separate detailed companions:

1. Driver -> Customer
   [FLUTTER_DRIVER_TO_CUSTOMER_CHAT_GUIDE.md](./FLUTTER_DRIVER_TO_CUSTOMER_CHAT_GUIDE.md)

2. Driver -> Shop
   [FLUTTER_DRIVER_TO_SHOP_CHAT_GUIDE.md](./FLUTTER_DRIVER_TO_SHOP_CHAT_GUIDE.md)

Additional broader reference:

- [FLUTTER_DRIVER_APP_CHAT_GUIDE.md](./FLUTTER_DRIVER_APP_CHAT_GUIDE.md)

---

This document is only for the chat between:

- Driver
- Customer

Inside one order using:

- `chat_type=driver_customer`

Out of scope:

- Shop-to-driver chats
- Shop-to-customer chats
- Support chats
- Driver invitations
- Driver order realtime list socket

## Scope

This guide covers:

- Opening the driver-customer chat explicitly
- Loading previous chat messages
- Sending text messages
- Sending media through the existing upload endpoint
- Connecting to the chat websocket
- Receiving realtime messages
- Marking messages as read
- Typing indicator
- Basic reconnect behavior

## Supported Directions

This same chat covers both directions:

1. Driver -> Customer
   The driver sends a message and the customer receives it on the same `driver_customer` thread.

2. Customer -> Driver
   The customer sends a message and the driver receives it on the same `driver_customer` thread.

There is no separate conversation type for each direction.

- Both directions use the same `order_id`
- Both directions use the same `chat_type=driver_customer`
- The actual direction is determined by `sender_type`

## Base URLs

- REST base: `/api`
- WebSocket base: `/ws`

Examples:

```text
POST /api/driver/orders/123/chat/open/
GET  /api/driver/orders/123/chat/
POST /api/driver/orders/123/chat/
WSS  /ws/chat/order/123/?token=<JWT>&chat_type=driver_customer&lang=ar
```

## Authentication

Use the normal driver JWT.

REST:

```http
Authorization: Bearer <access_token>
```

WebSocket:

```text
?token=<access_token>&chat_type=driver_customer&lang=ar
```

Allowed users on this chat:

- `driver` assigned to the order
- `customer` owner of the order

## Core Rule

The chat does not start automatically when the driver accepts the order.

The chat starts only when the driver presses the chat icon.

That means Flutter should do this:

1. Call `POST /api/driver/orders/{order_id}/chat/open/`
2. Read the response
3. Open the websocket returned by the backend
4. Load old messages from `GET /api/driver/orders/{order_id}/chat/`

## REST Endpoints

### 1. Open chat

```http
POST /api/driver/orders/{order_id}/chat/open/
```

Purpose:

- Prepare the driver-customer chat session
- Return the conversation identifier
- Return the websocket path to open
- Tell Flutter whether chat already had messages or not

Example response:

```json
{
  "success": true,
  "data": {
    "conversation_id": "order_123_driver_customer",
    "order_id": 123,
    "chat_type": "driver_customer",
    "is_existing": true,
    "is_new": false,
    "ws_url": "/ws/chat/order/123/?chat_type=driver_customer&lang=ar"
  }
}
```

Notes:

- `ws_url` is a path; Flutter should append the host and token
- the backend currently returns `is_existing` and `is_new`

### 2. Get chat messages

```http
GET /api/driver/orders/{order_id}/chat/
```

What it returns:

- customer block
- invoice block
- ordered messages array
- quick replies

Important:

- On this GET, unread customer messages in `driver_customer` are marked as read

Example response shape:

```json
{
  "success": true,
  "data": {
    "customer": {
      "id": 22,
      "name": "أحمد محمود",
      "phone_number": "01000000000",
      "profile_image_url": null,
      "is_online": false,
      "last_seen": null
    },
    "invoice": {
      "items": [
        {
          "name": "وجبة برجر كلاسيك",
          "quantity": 2,
          "line_total": 100.0
        }
      ],
      "payment_method": "cash",
      "amount_to_collect": 150.0
    },
    "messages": [
      {
        "id": 501,
        "message_type": "text",
        "content": "أنا في الطريق",
        "created_at": "2026-04-12T20:20:00Z",
        "is_mine": true
      }
    ],
    "quick_replies": [
      "أنا في الطريق",
      "وصلت",
      "من فضلك رد على الهاتف"
    ]
  }
}
```

### 3. Send text message

```http
POST /api/driver/orders/{order_id}/chat/
Content-Type: application/json
```

Body:

```json
{
  "content": "أنا في الطريق"
}
```

Success response:

```json
{
  "success": true,
  "data": {
    "id": 501,
    "message_type": "text",
    "content": "أنا في الطريق",
    "created_at": "2026-04-12T20:20:00Z",
    "is_mine": true
  }
}
```

Notes:

- Current driver REST endpoint sends text only
- Realtime delivery should still rely on the websocket

### 4. Send media

Use the existing shared upload endpoint:

```http
POST /api/chat/order/{order_id}/send-media/
```

Required form-data fields:

- `chat_type=driver_customer`
- `message_type=image` or `audio`
- `image_file` or `audio_file`

Example:

```text
chat_type: driver_customer
message_type: image
image_file: <binary>
```

After upload succeeds:

- the chat websocket receives a normal `chat_message`
- the customer side also receives the message

## WebSocket URL

```text
/ws/chat/order/{order_id}/?token=<JWT>&chat_type=driver_customer&lang=ar
```

Example:

```text
wss://example.com/ws/chat/order/123/?token=<JWT>&chat_type=driver_customer&lang=ar
```

## WebSocket Events

This chat uses the shared order-chat websocket contract.

The driver side should expect these server events:

- `messages_snapshot`
- `chat_message`
- `messages_read`
- `typing`
- `ack`
- `error`

## 1. `messages_snapshot`

Sent immediately after websocket connect.

Example:

```json
{
  "type": "messages_snapshot",
  "chat_type": "driver_customer",
  "order_id": 123,
  "data": {
    "messages": [
      {
        "id": 501,
        "chat_type": "driver_customer",
        "sender_type": "driver",
        "sender_name": "محمد علي",
        "message_type": "text",
        "content": "أنا في الطريق",
        "is_read": true,
        "created_at": "2026-04-12T20:20:00Z"
      }
    ]
  }
}
```

Flutter rule:

- Replace the visible message list with this snapshot on connect

## 2. `chat_message`

Sent when either the driver or the customer sends a message.

Example:

```json
{
  "type": "chat_message",
  "message": {
    "id": 502,
    "chat_type": "driver_customer",
    "sender_type": "customer",
    "sender_name": "أحمد محمود",
    "message_type": "text",
    "content": "تمام",
    "is_read": false,
    "created_at": "2026-04-12T20:21:00Z"
  }
}
```

Flutter rule:

- Append the new message if it is not already in the list
- If this screen is open and the sender is the customer, mark as seen locally

### Example A: Driver -> Customer

```json
{
  "type": "chat_message",
  "message": {
    "id": 601,
    "chat_type": "driver_customer",
    "sender_type": "driver",
    "sender_name": "محمد علي",
    "message_type": "text",
    "content": "أنا وصلت تحت البيت",
    "is_read": false,
    "created_at": "2026-04-12T20:30:00Z"
  }
}
```

### Example B: Customer -> Driver

```json
{
  "type": "chat_message",
  "message": {
    "id": 602,
    "chat_type": "driver_customer",
    "sender_type": "customer",
    "sender_name": "أحمد محمود",
    "message_type": "text",
    "content": "تمام نازل حالاً",
    "is_read": false,
    "created_at": "2026-04-12T20:31:00Z"
  }
}
```

## 3. `messages_read`

Sent when one side marks messages as read.

Example:

```json
{
  "type": "messages_read",
  "order_id": 123,
  "chat_type": "driver_customer",
  "reader_type": "driver"
}
```

Flutter rule:

- Update read state for outgoing messages when appropriate

## 4. `typing`

Sent when the other side is typing.

Example:

```json
{
  "type": "typing",
  "order_id": 123,
  "chat_type": "driver_customer",
  "sender_type": "customer",
  "is_typing": true
}
```

Flutter rule:

- Show a temporary typing indicator
- Auto-hide it after a short timeout if no follow-up event arrives

## 5. `ack`

Sent after successful websocket actions like sending a message or marking read.

Example:

```json
{
  "type": "ack",
  "action": "chat_message",
  "request_id": "req_1",
  "message": "تم تنفيذ الطلب بنجاح"
}
```

## 6. `error`

Sent when the websocket request is invalid.

Example:

```json
{
  "type": "error",
  "code": "MESSAGE_CONTENT_REQUIRED",
  "message": "محتوى الرسالة مطلوب"
}
```

## Client-to-Server WebSocket Events

### Send text message

```json
{
  "type": "chat_message",
  "content": "أنا في الطريق",
  "request_id": "req_1"
}
```

You may also send:

```json
{
  "type": "send_message",
  "content": "أنا في الطريق",
  "request_id": "req_1"
}
```

Meaning:

- If the socket is opened by the driver app, this payload means `driver -> customer`
- If the socket is opened by the customer app on the same order thread, this payload means `customer -> driver`
- In both cases, the backend sets the real `sender_type` from the authenticated socket user

### Mark messages as read

```json
{
  "type": "mark_read",
  "request_id": "req_2"
}
```

### Typing indicator

```json
{
  "type": "typing",
  "is_typing": true
}
```

## Recommended Flutter Flow

### Open chat screen

1. Call `POST /api/driver/orders/{order_id}/chat/open/`
2. Build websocket URL:
   - host + `ws_url`
   - append `token`
3. Open websocket
4. Call `GET /api/driver/orders/{order_id}/chat/`
5. Show:
   - customer header
   - invoice summary
   - message list
   - quick replies

### Send message

Preferred:

1. send websocket `chat_message`
2. wait for `chat_message` broadcast
3. append to UI

Fallback:

1. call `POST /api/driver/orders/{order_id}/chat/`
2. append returned message

### Upload media

1. upload through `/api/chat/order/{order_id}/send-media/`
2. wait for websocket `chat_message`
3. append to UI

### Leave chat screen

- close the websocket for that order
- keep the driver realtime orders socket alive if used elsewhere in app

## Reconnect Strategy

When chat socket disconnects:

1. reconnect with exponential backoff
2. use the same `order_id` and `chat_type=driver_customer`
3. after reconnect, trust the new `messages_snapshot`
4. if needed, refresh with `GET /api/driver/orders/{order_id}/chat/`

## Practical Notes

- `conversation_id` format is currently:
  - `order_{order_id}_driver_customer`
- message order from REST is ascending by `created_at`
- current driver-side REST send endpoint creates text only
- media should use the shared upload endpoint
- this chat is tied to one order, not a standalone conversation object in a separate table

## Minimal Integration Checklist

- [ ] Add driver chat repository/service for open/get/send
- [ ] Add websocket service for `/ws/chat/order/{order_id}/?chat_type=driver_customer`
- [ ] Open chat only after pressing the chat icon
- [ ] Render `messages_snapshot`
- [ ] Handle `chat_message`
- [ ] Handle `messages_read`
- [ ] Handle `typing`
- [ ] Handle `ack`
- [ ] Handle `error`
- [ ] Support media upload using `/api/chat/order/{order_id}/send-media/`

## Related Docs

- [driver_realtime_flutter_handoff.md](./driver_realtime_flutter_handoff.md)
- [CHAT_SYSTEM.md](./CHAT_SYSTEM.md)
- [WEBSOCKET_CONTRACT.md](./WEBSOCKET_CONTRACT.md)
