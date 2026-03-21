# Flutter Shop Chat Guide (Shop Owner / Employee)

For the latest backend event contract, use [WEBSOCKET_CONTRACT.md](./WEBSOCKET_CONTRACT.md) together with this Flutter-focused guide.

## 1) Scope
This guide is for the **shop-side app** (shop owner or employee) in Flutter.

It covers:
- Real-time shop chat with customer (`shop_customer`)
- Media upload (image/audio) in chat
- Invoice lifecycle from chat actions
- Order assignment to driver after customer confirmation

This guide uses the current backend behavior in:
- `shop/consumers.py`
- `shop/views.py`
- `shop/urls.py`

## 2) Base URLs
- REST base: `http://86.48.3.103/api`
- WebSocket base: `ws://86.48.3.103/ws`

Production should use HTTPS/WSS.

## 3) Authentication
Use a valid JWT access token for:
- shop owner (`user_type=shop_owner`)
- employee (`user_type=employee`)

Pass token as:
- REST: `Authorization: Bearer <token>`
- WebSocket query param: `?token=<token>`

## 4) WebSocket Channels You Need on Shop App

### A) Shop Orders channel (list screen updates)
URL:
```text
ws://86.48.3.103/ws/orders/shop/{shop_owner_id}/?token={JWT}
```

Used for:
- `new_order`
- `order_update`
- `new_message`
- `store_status_updated`
- `driver_status_updated`

### B) Order Chat channel (chat screen)
URL:
```text
ws://86.48.3.103/ws/chat/order/{order_id}/?token={JWT}&chat_type=shop_customer
```

On connect, server sends:
- `connection`
- `previous_messages` (up to last 50 messages for this order/chat type)

## 5) Chat WebSocket Events (shop_customer)

### Send text message
```json
{
  "type": "send_message",
  "message_type": "text",
  "content": "Your order is being prepared."
}
```

Compatibility note:
- `chat_message` is still accepted for text payloads, but `send_message` is the recommended client event name.

### Send typing state
```json
{
  "type": "typing",
  "is_typing": true
}
```

### Mark messages as read
```json
{
  "type": "mark_read"
}
```

### Send location message (optional)
```json
{
  "type": "location",
  "latitude": "24.7136",
  "longitude": "46.6753",
  "content": "Shop location"
}
```

### Receive new chat message
```json
{
  "type": "chat_message",
  "data": {
    "id": 123,
    "chat_type": "shop_customer",
    "sender_type": "customer",
    "sender_name": "Customer Name",
    "message_type": "text",
    "content": "Hello",
    "latitude": null,
    "longitude": null,
    "is_read": false,
    "created_at": "2026-02-18T12:30:00+00:00",
    "audio_file_url": null,
    "image_file_url": null
  }
}
```

## 6) Upload Image/Audio in Chat (REST)
Endpoint:
```text
POST /api/chat/order/{order_id}/send-media/
```

Allowed users:
- shop_owner, employee, customer, driver (with access checks)

Required multipart fields:
- `chat_type`: `shop_customer` (for shop chat)
- `message_type`: `image` or `audio`
- `image_file` OR `audio_file` (exactly one)
- `content` optional

After upload, backend broadcasts the message to chat subscribers over WebSocket.

## 7) Invoice + Chat Workflow (Shop Side)
Endpoint for all actions below:
```text
PUT /api/shop/orders/{order_id}/
```

### A) Create/Send invoice to customer
Set:
- `status = pending_customer_confirm`
- `items` (priced items text list)
- `total_amount` (> 0)
- `delivery_fee` (>= 0)

Example:
```json
{
  "status": "pending_customer_confirm",
  "items": [
    "Item 1 - price: 60.00",
    "Item 2 - price: 45.00"
  ],
  "delivery_fee": "15.00",
  "total_amount": "120.00"
}
```

### B) Edit and resend invoice
Same request as above, still `status=pending_customer_confirm`.

Allowed only while order is still waiting for customer confirmation.

### C) Cancel invoice
```json
{
  "status": "cancelled"
}
```

Allowed only before customer confirms.

### D) Assign order to driver
```json
{
  "driver_id": 1,
  "status": "preparing"
}
```

Rules:
- Not allowed before customer confirmation.
- Valid when order status is one of: `confirmed`, `preparing`, `on_way`.

### E) Status locks you must enforce in UI
After customer confirmation, invoice becomes locked:
- no invoice edit
- no invoice cancel
- no resend to `pending_customer_confirm`

Locked states:
- `confirmed`, `preparing`, `on_way`, `delivered`, `cancelled`

## 8) Customer Decision Endpoints (for reference)
- Confirm invoice: `POST /api/customer/orders/{id}/confirm/`
- Reject invoice: `POST /api/customer/orders/{id}/reject/`

Note:
- After customer accepts, reject/cancel should not be allowed.

## 9) Flutter Implementation Pattern

## Recommended packages
- `web_socket_channel`
- `dio` (or `http`)

## Suggested architecture
- `OrdersSocketService` for `/ws/orders/shop/...`
- `ChatSocketService` for `/ws/chat/order/...`
- `ChatRepository` for media upload + order update actions
- `Cubit/BLoC` per screen:
  - Orders list bloc
  - Chat room bloc

## Connection lifecycle
1. Connect orders socket after login.
2. Open chat socket when chat screen for an order opens.
3. Send `mark_read` after loading messages.
4. Reconnect with exponential backoff on disconnect.
5. On HTTP media upload success, do not manually add duplicate message; wait for WebSocket event.

## 10) Common Error Cases to Handle
- WebSocket close `4401`: unauthorized token
- WebSocket close `4403`: forbidden (wrong shop/order/chat type access)
- HTTP `400`: business rule violations (invoice lock, invalid state transition, invalid media payload)
- HTTP `404`: order/driver/customer not found

Show backend `message` to the user when available.

## 11) Minimal Dart Snippets

### Open chat socket
```dart
final uri = Uri.parse(
  'ws://86.48.3.103/ws/chat/order/$orderId/?token=$token&chat_type=shop_customer',
);
final channel = WebSocketChannel.connect(uri);
```

### Send text
```dart
channel.sink.add(jsonEncode({
  'type': 'chat_message',
  'message_type': 'text',
  'content': text,
}));
```

### Mark read
```dart
channel.sink.add(jsonEncode({'type': 'mark_read'}));
```

### Upload image (multipart)
```dart
final form = FormData.fromMap({
  'chat_type': 'shop_customer',
  'message_type': 'image',
  'content': caption,
  'image_file': await MultipartFile.fromFile(filePath),
});
await dio.post('/api/chat/order/$orderId/send-media/', data: form);
```

## 12) API Checklist for Shop Chat Feature
- [x] Shop orders websocket connected
- [x] Chat websocket connected per order
- [x] Text sending works
- [x] Typing indicator handled
- [x] Read receipts (`mark_read`) handled
- [x] Image/audio upload endpoint integrated
- [x] Invoice create/edit/cancel actions integrated
- [x] Driver assignment integrated after customer confirmation
- [x] State-lock rules enforced in UI
