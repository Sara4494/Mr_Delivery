# Flutter Driver App Chat Guide

This document is the handoff for the Flutter delivery app.

It covers both driver chat modules used by the backend:

1. Driver <-> shop chat through the dedicated `driver-chats` module
2. Driver <-> customer chat inside an order through `chat_type=driver_customer`

It is based on the current backend behavior in:

- `shop/driver_chat_consumers.py`
- `shop/driver_chat_service.py`
- `shop/consumers.py`
- `shop/views.py`
- `shop/urls.py`
- `shop/routing.py`

For broader websocket details, also see:

- [WEBSOCKET_CONTRACT.md](./WEBSOCKET_CONTRACT.md)
- [FLUTTER_DRIVER_CHATS_GUIDE.md](./FLUTTER_DRIVER_CHATS_GUIDE.md)

## 1. Scope

This guide is for the driver app only.

It covers:

- realtime driver <-> shop conversations
- realtime driver <-> customer order chat
- driver-side live notifications when the chat screen is closed
- text, voice, image, audio, location, typing, read state, ring, presence
- driver-side order actions sent from the shop chat module
- call signaling between shop and driver

The backend uses native WebSocket, not Socket.IO.

## 2. Base URLs

- REST base: `/api`
- WebSocket base: `/ws`

Examples:

```text
GET  /api/driver/orders/15/chat/
POST /api/chat/order/15/send-media/
WSS  /ws/driver/9/?token=<JWT>&lang=ar
WSS  /ws/driver-chats/driver/9/?token=<JWT>&lang=ar
WSS  /ws/chat/order/15/?token=<JWT>&chat_type=driver_customer&lang=ar
```

## 3. Authentication

Use the normal driver JWT access token.

- REST:

```http
Authorization: Bearer <access_token>
```

- WebSocket:

```text
?token=<access_token>
```

Optional:

- `lang=ar` or `lang=en` on sockets that return localized messages

## 4. Channels The Driver App Should Use

The driver app usually needs three sockets:

### A. Driver realtime channel

Use this as the long-lived background socket after login.

```text
/ws/driver/{driver_id}/?token=<JWT>&lang=ar
```

Purpose:

- receive `new_order`
- receive `order_update`
- receive `new_message` for `driver_customer` chat when the order chat screen is not open
- receive `presence_update` when customer presence changes
- receive `ring`
- send `location_update`
- optionally send `ring`

### B. Driver <-> shop chats socket

Use this as the long-lived driver/shop conversations socket after login.

```text
/ws/driver-chats/driver/{driver_id}/?token=<JWT>&lang=ar
```

Purpose:

- receive the full shop/driver conversations snapshot
- send and receive driver/shop messages
- receive order action updates from the shop chat module
- receive call state and WebRTC signaling

### C. Driver <-> customer order chat socket

Open this per active order chat screen.

```text
/ws/chat/order/{order_id}/?token=<JWT>&chat_type=driver_customer&lang=ar
```

Purpose:

- live driver/customer order chat
- typing
- read receipts
- customer online/offline presence for that order
- ring inside the active order chat

## 5. Driver <-> Shop Chat

## 5.1 Main concept

This module is not per order.

The backend keeps one conversation per `(shop_owner, driver)` pair.

Each conversation can contain:

- one shop
- one driver
- one or more linked orders
- a message history
- conversation status
- call history/state

Important:

- conversation id looks like `conv_12`
- message id looks like `msg_44`
- call id looks like `call_7`
- order id inside this module looks like `order_15`

## 5.2 Connect flow

Socket:

```text
/ws/driver-chats/driver/{driver_id}/?token=<JWT>&lang=ar
```

On connect, the backend sends:

1. `driver_chat.connection`
2. `driver_chats.snapshot`

Connection example:

```json
{
  "type": "driver_chat.connection",
  "success": true,
  "data": {
    "driver_id": "9"
  },
  "sent_at": "2026-04-06T12:00:00Z"
}
```

Snapshot example:

```json
{
  "type": "driver_chats.snapshot",
  "success": true,
  "data": {
    "conversations": [
      {
        "id": "conv_12",
        "shop": {
          "id": "3",
          "shop_name": "Burger House",
          "shop_number": "1020",
          "owner_name": "Mahmoud"
        },
        "driver": {
          "id": "9",
          "name": "Ali Hassan",
          "phone": "+201001234567",
          "avatar_url": "https://example.com/media/drivers/9.jpg",
          "rating": 4.8,
          "vehicle_label": "Motorbike",
          "plate_number": "ABC-123",
          "is_online": true,
          "presence_status": "online",
          "last_seen_at": "2026-04-06T11:58:00Z"
        },
        "orders": [
          {
            "id": "order_15",
            "order_number": "#OD123456",
            "customer": {
              "id": "c_7",
              "name": "Ahmed",
              "phone": "+201055555555"
            },
            "delivery_address": "Nasr City, Building 10",
            "total_amount": 180.0,
            "currency": "EGP",
            "items_count": 3,
            "created_at": "2026-04-06T10:00:00Z",
            "delivery_note": "Call when arriving",
            "status": "awaiting_driver_acceptance",
            "items": [
              {
                "id": "item_1",
                "name": "Burger",
                "price": 70.0,
                "quantity": 2
              }
            ],
            "delivery_fee": 30.0,
            "assigned_driver_name": "Ali Hassan",
            "transfer_reason": null
          }
        ],
        "status": "awaiting_driver_acceptance",
        "updated_at": "2026-04-06T12:00:00Z",
        "unread_count": 1,
        "last_message_preview": "Please take this order",
        "messages": [
          {
            "id": "msg_51",
            "type": "text",
            "sender": "store",
            "sent_at": "2026-04-06T11:59:00Z",
            "text": "Please take this order",
            "audio_url": null,
            "voice_duration_seconds": null,
            "invoice_order": null,
            "client_message_id": null,
            "delivery_status": "read"
          }
        ],
        "messages_next_cursor": null
      }
    ]
  },
  "sent_at": "2026-04-06T12:00:00Z"
}
```

Notes:

- `messages` inside the snapshot are paginated
- current page size is `20`
- use `messages_next_cursor` to load older messages

## 5.3 Main data shapes

### Conversation

```json
{
  "id": "conv_12",
  "shop": {},
  "driver": {},
  "orders": [],
  "status": "driver_on_way",
  "updated_at": "2026-04-06T12:00:00Z",
  "unread_count": 2,
  "last_message_preview": "Transfer requested",
  "messages": [],
  "messages_next_cursor": "..."
}
```

### Message

```json
{
  "id": "msg_1001",
  "type": "voice",
  "sender": "driver",
  "sent_at": "2026-04-06T12:00:00Z",
  "text": null,
  "audio_url": "https://example.com/media/driver_chats/voice/file.webm",
  "voice_duration_seconds": 11,
  "invoice_order": null,
  "client_message_id": "tmp_1",
  "delivery_status": "sent"
}
```

### Call

```json
{
  "call_id": "call_100",
  "conversation_id": "conv_12",
  "driver_id": "9",
  "initiated_by": "store",
  "status": "ringing",
  "created_at": "2026-04-06T12:00:00Z",
  "answered_at": null,
  "ended_at": null,
  "duration_seconds": 0,
  "reason": null,
  "channel_name": "driver_chat_room_12_150501",
  "rtc_token": null
}
```

## 5.4 Driver actions sent over the socket

All actions use either `action` or `type`.
The backend resolves both, but `action` is the preferred format in this module.

### Ping

```json
{
  "action": "driver_chat.ping",
  "request_id": "ping-1"
}
```

Response:

```json
{
  "type": "driver_chat.pong",
  "success": true,
  "request_id": "ping-1",
  "data": {},
  "sent_at": "2026-04-06T12:00:00Z"
}
```

### Send text

```json
{
  "action": "driver_chat.send_text",
  "request_id": "req-1",
  "conversation_id": "conv_12",
  "client_message_id": "tmp-1",
  "text": "I am on the way"
}
```

### Send voice

Upload first by REST, then send the websocket action:

```json
{
  "action": "driver_chat.send_voice",
  "request_id": "req-2",
  "conversation_id": "conv_12",
  "client_message_id": "tmp-2",
  "audio_url": "https://example.com/media/driver_chats/voice/file.webm",
  "voice_duration_seconds": 9
}
```

### Mark read

```json
{
  "action": "driver_chat.mark_read",
  "request_id": "req-3",
  "conversation_id": "conv_12"
}
```

### Typing

```json
{
  "action": "driver_chat.typing",
  "request_id": "req-4",
  "conversation_id": "conv_12",
  "is_typing": true
}
```

### Subscribe

```json
{
  "action": "driver_chat.subscribe",
  "request_id": "req-5",
  "conversation_id": "conv_12"
}
```

Current backend note:

- this action is accepted and acked
- it currently does not filter future events server-side
- the socket still broadcasts all relevant driver/shop conversation events for that driver

### Fetch older messages

```json
{
  "action": "driver_chat.fetch_more_messages",
  "request_id": "req-6",
  "conversation_id": "conv_12",
  "cursor": "..."
}
```

### Accept order

```json
{
  "action": "driver_chat.accept_order",
  "request_id": "req-7",
  "conversation_id": "conv_12",
  "order_id": "order_15"
}
```

Backend effect:

- linked conversation order moves to `driver_on_way`
- real order status moves to `on_way`
- system message is created
- conversation snapshot is refreshed

### Mark busy

```json
{
  "action": "driver_chat.mark_busy",
  "request_id": "req-8",
  "conversation_id": "conv_12",
  "order_id": "order_15"
}
```

Backend effect:

- driver status becomes `busy`
- order link status becomes `driver_busy`
- system message is created

### Request transfer

```json
{
  "action": "driver_chat.request_transfer",
  "request_id": "req-9",
  "conversation_id": "conv_12",
  "order_id": "order_15",
  "reason": "Vehicle issue"
}
```

Backend effect:

- order link status becomes `transfer_requested`
- `transfer_reason` is stored on the linked order
- a normal driver text message is created with the transfer reason

### Call actions available to the driver

Important:

- the current backend lets the shop start the call
- the driver side can respond to the call, but does not currently start it

Accept:

```json
{
  "action": "driver_chat.call_accept",
  "request_id": "call-1",
  "call_id": "call_100"
}
```

Reject:

```json
{
  "action": "driver_chat.call_reject",
  "request_id": "call-2",
  "call_id": "call_100"
}
```

End:

```json
{
  "action": "driver_chat.call_end",
  "request_id": "call-3",
  "call_id": "call_100"
}
```

### WebRTC signaling

Offer:

```json
{
  "action": "driver_chat.webrtc_offer",
  "request_id": "rtc-1",
  "call_id": "call_100",
  "sdp": "..."
}
```

Answer:

```json
{
  "action": "driver_chat.webrtc_answer",
  "request_id": "rtc-2",
  "call_id": "call_100",
  "sdp": "..."
}
```

ICE candidate:

```json
{
  "action": "driver_chat.webrtc_ice_candidate",
  "request_id": "rtc-3",
  "call_id": "call_100",
  "candidate": {
    "candidate": "...",
    "sdpMid": "0",
    "sdpMLineIndex": 0
  }
}
```

## 5.5 Server events on the driver/shop socket

Main server events:

- `driver_chat.connection`
- `driver_chats.snapshot`
- `driver_chat.conversation_created`
- `driver_chat.conversation_updated`
- `driver_chat.message_created`
- `driver_chat.order_updated`
- `driver_chat.unread_updated`
- `driver_chat.driver_presence_updated`
- `driver_chat.typing`
- `driver_chat.call_initiated`
- `driver_chat.call_ringing`
- `driver_chat.call_accepted`
- `driver_chat.call_rejected`
- `driver_chat.call_cancelled`
- `driver_chat.call_ended`
- `driver_chat.call_timeout`
- `driver_chat.call_missed`
- `driver_chat.webrtc_offer`
- `driver_chat.webrtc_answer`
- `driver_chat.webrtc_ice_candidate`
- `driver_chat.ack`
- `driver_chat.error`
- `driver_chat.pong`

### Example: message created

```json
{
  "type": "driver_chat.message_created",
  "success": true,
  "event_id": "evt_90",
  "data": {
    "conversation_id": "conv_12",
    "message": {
      "id": "msg_55",
      "type": "text",
      "sender": "store",
      "sent_at": "2026-04-06T12:01:00Z",
      "text": "Please go now",
      "audio_url": null,
      "voice_duration_seconds": null,
      "invoice_order": null,
      "client_message_id": null,
      "delivery_status": "read"
    }
  },
  "sent_at": "2026-04-06T12:01:00Z"
}
```

### Example: order updated

```json
{
  "type": "driver_chat.order_updated",
  "success": true,
  "event_id": "evt_91",
  "data": {
    "conversation_id": "conv_12",
    "order": {
      "id": "order_15",
      "order_number": "#OD123456",
      "status": "transfer_requested",
      "transfer_reason": "Vehicle issue"
    }
  },
  "sent_at": "2026-04-06T12:02:00Z"
}
```

### Example: typing

```json
{
  "type": "driver_chat.typing",
  "success": true,
  "data": {
    "conversation_id": "conv_12",
    "sender": "store",
    "is_typing": true
  },
  "sent_at": "2026-04-06T12:03:00Z"
}
```

### Example: call state

```json
{
  "type": "driver_chat.call_ringing",
  "success": true,
  "event_id": "evt_92",
  "data": {
    "call": {
      "call_id": "call_100",
      "conversation_id": "conv_12",
      "driver_id": "9",
      "initiated_by": "store",
      "status": "ringing",
      "created_at": "2026-04-06T12:04:00Z",
      "answered_at": null,
      "ended_at": null,
      "duration_seconds": 0,
      "reason": null,
      "channel_name": "driver_chat_room_12_120400",
      "rtc_token": null
    }
  },
  "sent_at": "2026-04-06T12:04:00Z"
}
```

Call timeout note:

- current backend timeout is `30` seconds
- when no answer arrives, the backend emits `driver_chat.call_timeout` and then `driver_chat.call_missed`

## 5.6 Ack and error handling

Successful action ack:

```json
{
  "type": "driver_chat.ack",
  "request_id": "req-1",
  "success": true,
  "data": {
    "message_id": "msg_55",
    "conversation_id": "conv_12"
  },
  "sent_at": "2026-04-06T12:01:00Z"
}
```

Error event:

```json
{
  "type": "driver_chat.error",
  "success": false,
  "data": {
    "code": "CONVERSATION_NOT_FOUND",
    "message": "Conversation not found"
  },
  "request_id": "req-1",
  "sent_at": "2026-04-06T12:01:00Z"
}
```

Failed ack:

```json
{
  "type": "driver_chat.ack",
  "request_id": "req-1",
  "success": false,
  "data": {},
  "error": {
    "code": "CONVERSATION_NOT_FOUND",
    "message": "Conversation not found"
  },
  "sent_at": "2026-04-06T12:01:00Z"
}
```

Important:

- for driver/shop socket errors with `request_id`, the backend can emit both:
  - `driver_chat.error`
  - `driver_chat.ack` with `success=false`

Recommended Flutter rule:

- keep a pending requests map by `request_id`
- confirm optimistic updates only after `driver_chat.ack.success == true`
- surface the backend message from either `driver_chat.error` or failed `driver_chat.ack`

## 5.7 Voice upload for driver/shop chat

Do not upload voice bytes through WebSocket.

Driver app endpoint:

```text
POST /api/driver/driver-chats/voice/upload/
Content-Type: multipart/form-data
field: file
```

Response:

```json
{
  "success": true,
  "data": {
    "audio_url": "https://example.com/media/driver_chats/voice/abcd.webm",
    "path": "driver_chats/voice/abcd.webm"
  }
}
```

Flow:

1. upload voice file by REST
2. read `audio_url`
3. send `driver_chat.send_voice`

## 5.8 Important driver/shop notes

- `event_id` is present on persisted server events and can be stored for debugging or ordering
- there is no dedicated driver-side resync endpoint right now
- on reconnect, the driver app should rely on a fresh `driver_chats.snapshot`
- current backend `unread_count` is maintained for shop-side unread driver messages
- current backend does not expose a separate driver unread counter field for store/system messages

The last two points are current backend behavior inferred from `create_message()` and `mark_conversation_read()` in `shop/driver_chat_service.py`.

## 6. Driver <-> Customer Order Chat

## 6.1 Main concept

This chat is per order and uses `ChatMessage` with:

- `chat_type = driver_customer`

Participants:

- assigned driver
- order owner customer

Socket:

```text
/ws/chat/order/{order_id}/?token=<JWT>&chat_type=driver_customer&lang=ar
```

## 6.2 Driver REST endpoint for initial chat data

The driver app has a dedicated REST endpoint:

```text
GET  /api/driver/orders/{order_id}/chat/
POST /api/driver/orders/{order_id}/chat/
```

Current GET behavior:

- allowed only for driver orders in statuses:
  - `confirmed`
  - `preparing`
  - `on_way`
- marks customer unread `driver_customer` messages as read
- returns customer summary, invoice summary, message history, and quick replies

Example GET response shape:

```json
{
  "success": true,
  "data": {
    "customer": {
      "id": 7,
      "name": "Ahmed",
      "phone_number": "+201055555555",
      "profile_image_url": "https://example.com/media/customer/7.jpg",
      "is_online": true,
      "last_seen": "2026-04-06T11:58:00Z"
    },
    "invoice": {
      "items": [
        {
          "name": "Burger",
          "quantity": 2,
          "line_total": 140.0
        }
      ],
      "payment_method": "cash",
      "amount_to_collect": 180.0
    },
    "messages": [
      {
        "id": 11,
        "message_type": "text",
        "content": "Please call me when you arrive",
        "created_at": "2026-04-06T11:30:00+00:00",
        "is_mine": false
      },
      {
        "id": 12,
        "message_type": "location",
        "content": "Current location",
        "created_at": "2026-04-06T11:32:00+00:00",
        "is_mine": true,
        "latitude": "30.0444",
        "longitude": "31.2357"
      }
    ],
    "quick_replies": [
      "One minute?",
      "I am under the building",
      "I arrived",
      "I am on the way"
    ]
  }
}
```

Current POST behavior:

- sends a normal text message only
- request body:

```json
{
  "content": "I arrived"
}
```

Realtime note:

- websocket is still the recommended path for live text and location
- REST POST is useful as a fallback if the chat socket is not open

## 6.3 Connect flow for the order chat socket

On connect, the backend sends:

1. `connection`
2. `presence_snapshot`
3. `previous_messages`

Connection example:

```json
{
  "type": "connection",
  "order_id": "15",
  "chat_type": "driver_customer",
  "user_type": "driver",
  "message": "Connected successfully",
  "message_ar": "...",
  "message_en": "Connected successfully"
}
```

Presence snapshot example:

```json
{
  "type": "presence_snapshot",
  "data": {
    "customer_id": 7,
    "is_online": true,
    "last_seen": "2026-04-06T11:58:00Z",
    "order_id": 15
  }
}
```

Previous messages example:

```json
{
  "type": "previous_messages",
  "messages": [
    {
      "id": 11,
      "chat_type": "driver_customer",
      "sender_type": "customer",
      "sender_name": "Ahmed",
      "sender_id": 7,
      "message_type": "text",
      "content": "Please call me when you arrive",
      "audio_file_url": null,
      "image_file_url": null,
      "latitude": null,
      "longitude": null,
      "invoice": null,
      "is_read": false,
      "created_at": "2026-04-06T11:30:00+00:00"
    }
  ]
}
```

## 6.4 Client events on the order chat socket

### Send text

Recommended:

```json
{
  "type": "send_message",
  "request_id": "msg-1",
  "message_type": "text",
  "content": "I am downstairs"
}
```

Legacy compatibility:

```json
{
  "type": "chat_message",
  "request_id": "msg-1",
  "message_type": "text",
  "content": "I am downstairs"
}
```

### Send location

Either of these works:

```json
{
  "type": "location",
  "request_id": "loc-1",
  "latitude": "30.0444",
  "longitude": "31.2357",
  "content": "My current location"
}
```

or

```json
{
  "type": "send_message",
  "request_id": "loc-1",
  "message_type": "location",
  "latitude": "30.0444",
  "longitude": "31.2357",
  "content": "My current location"
}
```

### Mark read

```json
{
  "type": "mark_read",
  "request_id": "read-1"
}
```

### Typing

```json
{
  "type": "typing",
  "is_typing": true
}
```

### Ring

Supported on order chat sockets.

For the driver, typical targets are:

- `customer`
- `shop`

Example:

```json
{
  "type": "ring",
  "request_id": "ring-1",
  "order_id": 15,
  "target": "customer"
}
```

Multi-target example:

```json
{
  "type": "ring",
  "request_id": "ring-2",
  "order_id": 15,
  "targets": ["customer", "shop"]
}
```

Ring ack example:

```json
{
  "type": "ack",
  "action": "ring",
  "success": true,
  "request_id": "ring-1",
  "data": {
    "order_id": 15,
    "shop": {
      "id": 3,
      "name": "Burger House",
      "profile_image_url": "https://example.com/media/shops/logo.png"
    },
    "shop_id": 3,
    "shop_name": "Burger House",
    "shop_profile_image_url": "https://example.com/media/shops/logo.png",
    "targets": ["customer"],
    "unavailable_targets": [],
    "ring_id": "uuid-value"
  },
  "message": "Ring sent successfully"
}
```

## 6.5 Server events on the order chat socket

Server-to-client events:

- `connection`
- `presence_snapshot`
- `presence_update`
- `previous_messages`
- `chat_message`
- `messages_read`
- `typing`
- `ring`
- `ack`
- `error`

### New message broadcast

```json
{
  "type": "chat_message",
  "data": {
    "id": 12,
    "chat_type": "driver_customer",
    "sender_type": "driver",
    "sender_name": "Ali Hassan",
    "sender_id": 9,
    "message_type": "text",
    "content": "I am downstairs",
    "audio_file_url": null,
    "image_file_url": null,
    "latitude": null,
    "longitude": null,
    "invoice": null,
    "is_read": false,
    "created_at": "2026-04-06T12:10:00+00:00"
  }
}
```

### Messages read

```json
{
  "type": "messages_read",
  "order_id": "15",
  "reader_type": "driver",
  "count": 3
}
```

### Typing

```json
{
  "type": "typing",
  "user_type": "customer",
  "user_name": "Ahmed",
  "is_typing": true
}
```

### Presence update

```json
{
  "type": "presence_update",
  "data": {
    "order_id": 15,
    "customer_id": 7,
    "is_online": false,
    "last_seen": "2026-04-06T12:11:00Z"
  }
}
```

### Ack

For text:

```json
{
  "type": "ack",
  "action": "send_message",
  "success": true,
  "request_id": "msg-1",
  "data": {
    "message_id": 12,
    "order_id": 15,
    "chat_type": "driver_customer"
  },
  "message": "Request completed successfully"
}
```

For mark read:

```json
{
  "type": "ack",
  "action": "mark_read",
  "success": true,
  "request_id": "read-1",
  "data": {
    "order_id": 15,
    "count": 3
  },
  "message": "Request completed successfully"
}
```

### Error

```json
{
  "type": "error",
  "success": false,
  "code": "MESSAGE_CONTENT_REQUIRED",
  "request_id": "msg-1",
  "message": "Message content is required"
}
```

Current error codes produced by the order chat consumer:

- `INVALID_JSON`
- `UNKNOWN_EVENT`
- `UNSUPPORTED_MESSAGE_TYPE`
- `MESSAGE_CONTENT_REQUIRED`
- `LOCATION_COORDINATES_REQUIRED`
- `MESSAGE_SAVE_FAILED`
- `UNEXPECTED_ERROR`

### Ring event delivered to the other side

```json
{
  "type": "ring",
  "data": {
    "ring_id": "uuid-value",
    "order_id": 15,
    "order_number": "OD123456",
    "shop": {
      "id": 3,
      "name": "Burger House",
      "profile_image_url": "https://example.com/media/shops/logo.png"
    },
    "shop_id": 3,
    "shop_name": "Burger House",
    "shop_profile_image_url": "https://example.com/media/shops/logo.png",
    "sender_type": "driver",
    "sender_name": "Ali Hassan",
    "sender_id": 9,
    "target": "customer",
    "targets": ["customer"],
    "chat_type": "driver_customer",
    "notification_kind": "ring",
    "play_sound_on_frontend": true,
    "created_at": "2026-04-06T12:12:00+02:00"
  }
}
```

## 6.6 Media upload for driver/customer chat

Image and audio are uploaded by REST, not through WebSocket frames.

Endpoint:

```text
POST /api/chat/order/{order_id}/send-media/
```

Required multipart fields:

- `chat_type=driver_customer`
- exactly one of:
  - `image_file`
  - `audio_file`

Optional:

- `message_type=image` or `message_type=audio`
- `content`

Success result:

- REST returns the created serialized message
- active order chat socket receives `chat_message`
- driver background socket receives `new_message`
- customer orders socket receives `new_message`

Important Flutter rule:

- after REST upload succeeds, do not manually insert a duplicate final message if you are already listening to the order chat socket
- wait for websocket echo or deduplicate by message id

## 6.7 Driver background socket relevance to customer chat

Keep this socket open after login:

```text
/ws/driver/{driver_id}/?token=<JWT>&lang=ar
```

Server events relevant to chat:

- `connection`
- `new_order`
- `order_update`
- `new_message`
- `presence_update`
- `ring`

### `new_message` on the driver background socket

This is how the driver app can update list previews and badges while the order chat screen is closed.

Example shape:

```json
{
  "type": "new_message",
  "data": {
    "order_id": 15,
    "order_number": "OD123456",
    "chat_type": "driver_customer",
    "message": {
      "id": 12,
      "chat_type": "driver_customer",
      "sender_type": "customer",
      "sender_name": "Ahmed",
      "message_type": "text",
      "content": "Where are you?",
      "audio_file_url": null,
      "image_file_url": null,
      "latitude": null,
      "longitude": null,
      "invoice": null,
      "is_read": false,
      "created_at": "2026-04-06T12:13:00+00:00"
    },
    "order": {
      "...": "latest order snapshot after this message"
    }
  }
}
```

### `presence_update` on the driver background socket

The backend also sends customer presence changes to the driver background socket.

Example:

```json
{
  "type": "presence_update",
  "data": {
    "order_id": 15,
    "customer_id": 7,
    "is_online": true,
    "last_seen": "2026-04-06T12:14:00Z"
  }
}
```

### Driver background client events

Location update:

```json
{
  "type": "location_update",
  "latitude": "30.0444",
  "longitude": "31.2357"
}
```

Optional ring from the driver background socket:

```json
{
  "type": "ring",
  "request_id": "ring-3",
  "order_id": 15,
  "target": "customer"
}
```

The same `ack` shape used for `ring` on the order chat socket is also used when `ring` is sent from the driver background socket.

## 7. Enums And Rules

## 7.1 Driver <-> shop statuses

Conversation and linked-order statuses:

```text
waiting_reply
awaiting_driver_acceptance
transfer_requested
driver_busy
driver_on_way
driver_arrived
transferred_to_another_driver
delivered
cancelled
rejected
```

Driver/shop message types:

```text
text
voice
invoice
system
call
```

Driver/shop senders:

```text
store
driver
system
```

Driver presence statuses in the driver/shop module:

```text
online
offline
busy
on_trip
```

Driver/shop call statuses:

```text
initiated
ringing
accepted
rejected
cancelled
ended
missed
timeout
failed
```

## 7.2 Driver <-> customer order chat rules

Chat type:

```text
driver_customer
```

Order chat sender types:

```text
driver
customer
```

Order chat message types currently supported by the model and API:

```text
text
audio
image
location
```

WebSocket direct-send support on order chat:

```text
text
location
```

Media upload support on order chat REST:

```text
audio
image
```

Current driver REST chat endpoint active order statuses:

```text
confirmed
preparing
on_way
```

## 8. Recommended Flutter Split

Suggested services:

- `DriverRealtimeSocketService` for `/ws/driver/{driver_id}/`
- `DriverShopChatsSocketService` for `/ws/driver-chats/driver/{driver_id}/`
- `DriverOrderChatSocketService` for `/ws/chat/order/{order_id}/?chat_type=driver_customer`
- `DriverOrderChatRepository` for `/api/driver/orders/{order_id}/chat/`
- `DriverChatMediaRepository` for `/api/chat/order/{order_id}/send-media/`
- `DriverShopVoiceRepository` for `/api/driver/driver-chats/voice/upload/`

Suggested state:

- `driverOrdersById`
- `shopConversationsById`
- `openOrderChatId`
- `openShopConversationId`
- `pendingRequests`
- `customerPresenceByOrderId`
- `activeCallByConversationId`

## 9. Reconnect Strategy

Recommended behavior:

1. After driver login, open:
   - `/ws/driver/{driver_id}/`
   - `/ws/driver-chats/driver/{driver_id}/`
2. When a driver opens an order chat screen, open:
   - `/ws/chat/order/{order_id}/?chat_type=driver_customer`
3. Reconnect each socket independently with exponential backoff.
4. After reconnecting the driver/shop socket:
   - wait for `driver_chat.connection`
   - replace local conversations from fresh `driver_chats.snapshot`
5. After reconnecting the driver/customer order chat:
   - wait for `connection`
   - accept `presence_snapshot`
   - rebuild room history from `previous_messages`
   - optionally refresh via `GET /api/driver/orders/{order_id}/chat/` if the UI needs invoice/customer data again
6. After reconnecting the background driver socket:
   - resume handling `new_order`, `order_update`, `new_message`, `presence_update`, and `ring`

Important:

- there is no driver-side resync endpoint for the driver/shop chat module right now
- the fresh snapshot is the source of truth after reconnect
- for the order chat module, websocket history is only the latest room history, while REST is the safe place for a complete active-screen refresh

## 10. Implementation Checklist

- [x] Keep `/ws/driver/{driver_id}/` open after login
- [x] Keep `/ws/driver-chats/driver/{driver_id}/` open after login
- [x] Open `/ws/chat/order/{order_id}/?chat_type=driver_customer` per active order chat
- [x] Hydrate driver/customer chat screen from `GET /api/driver/orders/{order_id}/chat/`
- [x] Send text over websocket for both chat modules
- [x] Upload voice for driver/shop chat by REST, then send `driver_chat.send_voice`
- [x] Upload image/audio for driver/customer chat by REST
- [x] Handle typing, read receipts, presence, and ring
- [x] Handle `driver_chat.call_*` and WebRTC relay for shop/driver calls
- [x] Deduplicate REST-uploaded messages against websocket echoes
