# Flutter Driver To Customer Chat Guide

This document is only for:

- Driver -> Customer

Inside the order chat thread that uses:

- `chat_type=driver_customer`

## Purpose

This flow starts when the driver presses the customer chat icon from the driver app.

The driver can then:

- open the chat session
- load previous messages
- send text messages
- send media using the shared upload endpoint
- receive realtime replies from the customer

## REST Endpoints

### 1. Open chat

```http
POST /api/driver/orders/{order_id}/chat/open/
```

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

### 2. Load old messages

```http
GET /api/driver/orders/{order_id}/chat/
```

Driver-side benefit:

- returns customer info
- returns invoice summary
- returns message history
- returns quick replies

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

### 4. Send media

```http
POST /api/chat/order/{order_id}/send-media/
```

Form-data:

- `chat_type=driver_customer`
- `message_type=image` or `audio`
- `image_file` or `audio_file`

## WebSocket

```text
/ws/chat/order/{order_id}/?token=<JWT>&chat_type=driver_customer&lang=ar
```

The driver app opens this socket after `chat/open`.

## Driver -> Customer Message Example

When the driver sends a text message, the room broadcasts:

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

## Server Events The Driver App Should Handle

- `messages_snapshot`
- `chat_message`
- `messages_read`
- `typing`
- `ack`
- `error`

## Client Events The Driver App Can Send

### Send text message

```json
{
  "type": "chat_message",
  "content": "أنا في الطريق",
  "request_id": "req_1"
}
```

### Mark read

```json
{
  "type": "mark_read",
  "request_id": "req_2"
}
```

### Typing

```json
{
  "type": "typing",
  "is_typing": true
}
```

## Flutter Flow

1. Call `POST /api/driver/orders/{order_id}/chat/open/`
2. Open `/ws/chat/order/{order_id}/?chat_type=driver_customer`
3. Call `GET /api/driver/orders/{order_id}/chat/`
4. Render messages
5. Send outgoing driver messages by websocket
6. Use REST media upload only for image/audio

## Related Docs

- [FLUTTER_DRIVER_TO_SHOP_CHAT_GUIDE.md](./FLUTTER_DRIVER_TO_SHOP_CHAT_GUIDE.md)
- [FLUTTER_DRIVER_CHATS_GUIDE.md](./FLUTTER_DRIVER_CHATS_GUIDE.md)
- [driver_realtime_flutter_handoff.md](./driver_realtime_flutter_handoff.md)
