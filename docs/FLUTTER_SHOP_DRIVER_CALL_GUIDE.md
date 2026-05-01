# Flutter Shop-to-Driver Call Guide

This guide is for the shop mobile app and the driver mobile app.

It covers the current backend flow for shop-to-driver ringing and call signaling.

## Scope

The backend already supports:

- shop starts a call to a driver
- driver receives ringing state
- driver accepts or rejects
- either side ends the call
- WebRTC signaling messages are relayed through WebSocket

This module uses the existing driver chat conversation between shop and driver.

## Authentication

Use the normal JWT access token.

- REST:

```http
Authorization: Bearer <access_token>
```

- WebSocket:

```text
?token=<access_token>
```

## WebSocket endpoints

### Shop socket

```text
/ws/driver-chats/shop/<shop_owner_id>/?token=<JWT>&lang=ar
```

### Driver socket

```text
/ws/driver-chats/driver/<driver_id>/?token=<JWT>&lang=ar
```

## Required conversation id

Call start happens inside an existing driver chat conversation.

The shop gets conversations from:

```text
GET /api/shop/driver-chats/conversations/
```

Each item contains:

- `id`: conversation id like `conv_12`
- `driver.id`

## Start ring / call from shop

Send this through the shop socket:

```json
{
  "action": "driver_chat.call_start",
  "request_id": "call-start-1",
  "conversation_id": "conv_12",
  "driver_id": "9"
}
```

Notes:

- `driver_id` is optional for current backend behavior
- `conversation_id` is the important field

## Successful ack to shop

```json
{
  "type": "driver_chat.ack",
  "request_id": "call-start-1",
  "success": true,
  "data": {
    "call_id": "call_100",
    "conversation_id": "conv_12"
  },
  "sent_at": "2026-04-06T12:04:00Z"
}
```

## Ringing event received by both sides

```json
{
  "type": "driver_chat.call_ringing",
  "success": true,
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

## Driver accepts

Driver sends:

```json
{
  "action": "driver_chat.call_accept",
  "request_id": "call-accept-1",
  "call_id": "call_100"
}
```

Shop and driver then receive:

```json
{
  "type": "driver_chat.call_accepted",
  "success": true,
  "data": {
    "call": {
      "call_id": "call_100",
      "status": "accepted"
    }
  }
}
```

## Driver rejects

Driver sends:

```json
{
  "action": "driver_chat.call_reject",
  "request_id": "call-reject-1",
  "call_id": "call_100"
}
```

Both sides receive:

```json
{
  "type": "driver_chat.call_rejected",
  "success": true,
  "data": {
    "call": {
      "call_id": "call_100",
      "status": "rejected",
      "reason": "busy"
    }
  }
}
```

## End call

Either side can end:

```json
{
  "action": "driver_chat.call_end",
  "request_id": "call-end-1",
  "call_id": "call_100"
}
```

If the shop cancels before answer:

```json
{
  "action": "driver_chat.call_cancel",
  "request_id": "call-cancel-1",
  "call_id": "call_100"
}
```

## Timeout behavior

Current backend timeout is about `30` seconds.

If no one answers, the backend emits:

- `driver_chat.call_timeout`
- `driver_chat.call_missed`

## WebRTC signaling

After `driver_chat.call_accepted`, exchange signaling over the same socket.

### Offer

```json
{
  "action": "driver_chat.webrtc_offer",
  "request_id": "rtc-offer-1",
  "call_id": "call_100",
  "sdp": "..."
}
```

### Answer

```json
{
  "action": "driver_chat.webrtc_answer",
  "request_id": "rtc-answer-1",
  "call_id": "call_100",
  "sdp": "..."
}
```

### ICE candidate

```json
{
  "action": "driver_chat.webrtc_ice_candidate",
  "request_id": "rtc-ice-1",
  "call_id": "call_100",
  "candidate": {
    "candidate": "...",
    "sdpMid": "0",
    "sdpMLineIndex": 0
  }
}
```

## Recommended Flutter behavior

### Shop app

1. Connect to shop driver chats socket after login.
2. Load conversations.
3. When user taps call button, send `driver_chat.call_start`.
4. Show outgoing ringing UI on:
   - ack success
   - or `driver_chat.call_ringing`
5. When `driver_chat.call_accepted` arrives, open in-call screen and start WebRTC.
6. When `driver_chat.call_rejected`, `driver_chat.call_cancelled`, `driver_chat.call_timeout`, `driver_chat.call_missed`, or `driver_chat.call_ended` arrives, close ringing/in-call UI.

### Driver app

1. Keep driver chats socket connected after login.
2. On `driver_chat.call_ringing` with `initiated_by=store`, show incoming call UI.
3. If user accepts, send `driver_chat.call_accept`.
4. If user rejects, send `driver_chat.call_reject`.
5. After accept, complete WebRTC negotiation using socket relay events.
6. If call ends or times out, close the call screen and clean the peer connection.

## Minimal status set to handle in UI

- `initiated`
- `ringing`
- `accepted`
- `rejected`
- `cancelled`
- `ended`
- `timeout`
- `missed`
- `failed`

## Related existing files

- `shop/driver_chat/consumers.py`
- `shop/driver_chat/service.py`
- `shop/templates/shop/driver_chats_ui.html`
- `shop/templates/shop/driver_store_chats_ui.html`
- `docs/FLUTTER_DRIVER_APP_CHAT_GUIDE.md`
