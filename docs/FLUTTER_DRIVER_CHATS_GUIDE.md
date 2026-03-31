# Flutter Driver Chats Guide

This document is the handoff for the Flutter team for the new shop-side `Driver Chats` module.

It covers:
- Shop-to-driver realtime conversations
- Driver presence
- Invoice/order cards inside the conversation
- Order transfer flow
- Voice messages
- Call signaling
- Snapshot and resync

## 1. Base URLs

- REST base: `/api`
- WebSocket base: `/ws`

Examples:

```text
GET  /api/shop/driver-chats/conversations/
WSS  /ws/driver-chats/shop/{shop_owner_id}/?token=JWT&lang=ar
```

## 2. Authentication

Use the normal shop JWT.

- REST:

```http
Authorization: Bearer <access_token>
```

- WebSocket:

```text
?token=<access_token>&lang=ar
```

Allowed users:
- `shop_owner`
- `employee`

## 3. Main Concept

The backend is `conversation per driver`, not `conversation per order`.

Each conversation contains:
- one driver
- list of linked orders/invoices
- messages between store and driver
- conversation status
- unread count for the shop side

## 4. Main Data Shapes

## Conversation

```json
{
  "id": "conv_12",
  "driver": {},
  "orders": [],
  "status": "driver_on_way",
  "updated_at": "2026-03-31T12:00:00Z",
  "unread_count": 2,
  "last_message_preview": "طلب تحويل الأوردر بسبب...",
  "messages": [],
  "messages_next_cursor": "..."
}
```

## Driver

```json
{
  "id": "15",
  "name": "محمد علي",
  "phone": "+201001234567",
  "avatar_url": "https://...",
  "rating": 4.8,
  "vehicle_label": "هيونداي أكسنت",
  "plate_number": "س ص 1234",
  "is_online": true,
  "presence_status": "online",
  "last_seen_at": "2026-03-31T12:00:00Z"
}
```

## Order

```json
{
  "id": "order_123",
  "order_number": "#12345",
  "customer": {
    "id": "c_1",
    "name": "أحمد محمد",
    "phone": "+2010..."
  },
  "delivery_address": "حي الحسين، شارع رقم 12، عمارة 4",
  "total_amount": 154.0,
  "currency": "EGP",
  "items_count": 5,
  "created_at": "2026-03-31T10:20:00Z",
  "delivery_note": "العميل طلب التواصل عند الوصول",
  "status": "driver_on_way",
  "items": [],
  "delivery_fee": 40.0,
  "assigned_driver_name": "محمد علي",
  "transfer_reason": null
}
```

## Message

```json
{
  "id": "msg_1001",
  "type": "text",
  "sender": "driver",
  "sent_at": "2026-03-31T12:00:00Z",
  "text": "أنا أمام المنزل الآن",
  "audio_url": null,
  "voice_duration_seconds": null,
  "invoice_order": null,
  "client_message_id": null,
  "delivery_status": "sent"
}
```

## Call

```json
{
  "call_id": "call_100",
  "conversation_id": "conv_12",
  "driver_id": "15",
  "initiated_by": "store",
  "status": "ringing",
  "created_at": "2026-03-31T12:00:00Z",
  "answered_at": null,
  "ended_at": null,
  "duration_seconds": 0,
  "reason": null,
  "channel_name": "driver_chat_room_12_150501",
  "rtc_token": null
}
```

## 5. WebSocket

Endpoint:

```text
/ws/driver-chats/shop/{shop_owner_id}/?token=JWT&lang=ar
```

On connect, the backend sends:

```json
{
  "type": "driver_chats.snapshot",
  "success": true,
  "data": {
    "conversations": [],
    "last_event_id": "evt_1"
  },
  "sent_at": "2026-03-31T12:00:00Z"
}
```

## Unified envelope

```json
{
  "type": "driver_chat.message_created",
  "request_id": "req_123",
  "success": true,
  "event_id": "evt_50",
  "data": {},
  "sent_at": "2026-03-31T12:00:00Z"
}
```

Notes:
- `event_id` exists on persisted server events and should be stored for resync.
- `request_id` is echoed on ack/error when applicable.

## 6. Important Server Events

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

## Example event payloads

```json
{ "type": "driver_chat.message_created", "data": { "conversation_id": "conv_1", "message": {} } }
{ "type": "driver_chat.order_updated", "data": { "conversation_id": "conv_1", "order": {} } }
{ "type": "driver_chat.unread_updated", "data": { "conversation_id": "conv_1", "unread_count": 3 } }
{ "type": "driver_chat.driver_presence_updated", "data": { "driver_id": "15", "is_online": true, "presence_status": "online", "last_seen_at": "2026-03-31T12:00:00Z" } }
```

## 7. Shop Actions Sent from Flutter

## Send text

```json
{
  "action": "driver_chat.send_text",
  "request_id": "req_1",
  "conversation_id": "conv_1",
  "client_message_id": "tmp_1",
  "text": "السلام عليكم"
}
```

## Send voice

```json
{
  "action": "driver_chat.send_voice",
  "request_id": "req_2",
  "conversation_id": "conv_1",
  "client_message_id": "tmp_2",
  "audio_url": "https://...",
  "voice_duration_seconds": 12
}
```

## Mark read

```json
{
  "action": "driver_chat.mark_read",
  "request_id": "req_3",
  "conversation_id": "conv_1"
}
```

## Subscribe

```json
{
  "action": "driver_chat.subscribe",
  "request_id": "req_4",
  "conversation_id": "conv_1"
}
```

## Fetch more messages

```json
{
  "action": "driver_chat.fetch_more_messages",
  "request_id": "req_5",
  "conversation_id": "conv_1",
  "cursor": "..."
}
```

## Transfer to another driver

```json
{
  "action": "driver_chat.transfer_to_driver",
  "request_id": "req_6",
  "source_conversation_id": "conv_1",
  "order_id": "order_1",
  "target_driver_id": "22"
}
```

## Start / cancel / end call

```json
{ "action": "driver_chat.call_start", "request_id": "c1", "conversation_id": "conv_1", "driver_id": "15" }
{ "action": "driver_chat.call_cancel", "request_id": "c2", "call_id": "call_100" }
{ "action": "driver_chat.call_end", "request_id": "c3", "call_id": "call_100" }
```

## WebRTC signaling

```json
{ "action": "driver_chat.webrtc_offer", "request_id": "rtc1", "call_id": "call_100", "sdp": "..." }
{ "action": "driver_chat.webrtc_answer", "request_id": "rtc2", "call_id": "call_100", "sdp": "..." }
{ "action": "driver_chat.webrtc_ice_candidate", "request_id": "rtc3", "call_id": "call_100", "candidate": {} }
```

## 8. Ack Handling

Every client action should wait for:

```json
{
  "type": "driver_chat.ack",
  "request_id": "req_1",
  "success": true,
  "data": {},
  "sent_at": "2026-03-31T12:00:00Z"
}
```

Failure:

```json
{
  "type": "driver_chat.ack",
  "request_id": "req_1",
  "success": false,
  "error": {
    "code": "FORBIDDEN",
    "message": "..."
  }
}
```

Recommended Flutter rule:
- keep a map of pending `request_id`
- mark optimistic UI as confirmed only on `ack.success=true`
- rollback on `ack.success=false`

## 9. REST Endpoints Used by Flutter

## Conversations list

```text
GET /api/shop/driver-chats/conversations/?q=
```

Search works on:
- driver name
- order number
- customer name
- delivery address

## Messages page

```text
GET /api/shop/driver-chats/conversations/{conversation_id}/messages/?cursor=...
```

## Orders in a conversation

```text
GET /api/shop/driver-chats/conversations/{conversation_id}/orders/
```

## Available drivers for transfer

```text
GET /api/shop/drivers/available-for-transfer/?exclude_driver_id=15
```

## Voice upload URL

```text
POST /api/shop/driver-chats/voice/upload-url/
```

Current backend also supports direct upload:

```text
POST /api/shop/driver-chats/voice/upload/
multipart/form-data
field: file
```

## Mark read by REST

```text
POST /api/shop/driver-chats/mark-read/
{
  "conversation_id": "conv_1"
}
```

## Resync

```text
GET /api/shop/driver-chats/resync/?last_event_id=evt_25
```

Response:
- `events` if delta is available
- `requires_snapshot=true` + `snapshot` if the event id is no longer valid

## Call details

```text
GET /api/shop/driver-chats/calls/{call_id}/
```

## 10. Voice Message Flow

Do not upload audio bytes inside WebSocket.

Flow:
1. Upload file by REST.
2. Receive `audio_url`.
3. Send `driver_chat.send_voice` through WebSocket.

## 11. Enums

## Conversation / order status

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

## Message type

```text
text
voice
invoice
system
call
```

## Sender

```text
store
driver
system
```

## Presence

```text
online
offline
busy
on_trip
```

## Call status

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

## 12. Reconnect Strategy for Flutter

Recommended behavior:

1. Open WebSocket after login.
2. Store `last_event_id` from snapshot and every incoming persisted event.
3. If socket disconnects:
   - reconnect with exponential backoff
   - after reconnect, accept the fresh snapshot
   - optionally call `/resync` before reconnecting UI-heavy screens
4. Preserve current selected conversation locally.
5. On `driver_chat.error` or failed `ack`, show backend message.

## 13. Suggested Flutter Architecture

- `DriverChatsRepository`
- `DriverChatsSocketService`
- `DriverChatsCubit` or `Bloc`
- `DriverChatRoomCubit` for selected conversation detail
- `CallSignalingService` for WebRTC signaling

State to keep locally:
- `conversationsById`
- sorted conversation ids
- `selectedConversationId`
- `lastEventId`
- `pendingRequests`
- `availableTransferDrivers`
- `activeCallByConversationId`

## 14. Important UI Rules

- Show driver green indicator when `presence_status != offline`
- Reset unread when the user opens the conversation and `mark_read` succeeds
- Do not duplicate sent messages after socket echo
- For invoice messages use `message.invoice_order`
- For call banners use latest `driver_chat.call_*` event
- Show transfer reason from `order.transfer_reason`

## 15. Current Backend Choice for Calls

Current backend implementation supports:
- call state events
- WebRTC signaling relay through WebSocket

It does **not** currently generate Agora/Twilio/Zego tokens.

So Flutter should implement the call media layer with WebRTC on top of:
- `driver_chat.webrtc_offer`
- `driver_chat.webrtc_answer`
- `driver_chat.webrtc_ice_candidate`

