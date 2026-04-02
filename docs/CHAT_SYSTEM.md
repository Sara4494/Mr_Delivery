# 💬 Chat System

Real-time chat system for communication between customers, shop staff, and drivers.

---

## 📋 Overview

The chat system supports two types of conversations per order:

| Chat Type | Participants | Use Case |
|-----------|--------------|----------|
| `shop_customer` | Customer ↔ Shop Owner/Employee | Order inquiries, support |
| `driver_customer` | Customer ↔ Driver | Delivery coordination |

---

## 🔌 Connection

### WebSocket URL
```
ws://server/ws/chat/order/{order_id}/?token=JWT&chat_type=shop_customer
```

### Parameters
| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `order_id` | Integer | Yes | The order ID |
| `token` | String | Yes | JWT access token |
| `chat_type` | String | Yes | `shop_customer` or `driver_customer` |

---

## 👥 Access Control

### shop_customer Chat
| User Type | Can Access |
|-----------|------------|
| Shop Owner | ✅ (order belongs to shop) |
| Employee | ✅ (employee of the shop) |
| Customer | ✅ (owns the order) |
| Driver | ❌ |

### driver_customer Chat
| User Type | Can Access |
|-----------|------------|
| Shop Owner | ❌ |
| Employee | ❌ |
| Customer | ✅ (owns the order) |
| Driver | ✅ (assigned to the order) |

---

## 📨 Message Types

### Text Message
```json
{
    "type": "send_message",
    "message_type": "text",
    "content": "Your order is being prepared"
}
```

### Location Message
```json
{
    "type": "send_message",
    "message_type": "location",
    "latitude": "24.7136",
    "longitude": "46.6753",
    "content": "I'm here at this location"
}
```

### Audio Message (via REST)
```http
POST /api/shop/orders/{id}/messages/
Content-Type: multipart/form-data

message_type: audio
audio_file: (file)
```

### Image Message (via REST)
```http
POST /api/shop/orders/{id}/messages/
Content-Type: multipart/form-data

message_type: image
image_file: (file)
content: "Check this image"
```

---

## 📥 Receiving Messages

### On Connection - Previous Messages
```json
{
    "type": "previous_messages",
    "messages": [
        {
            "id": 1,
            "chat_type": "shop_customer",
            "sender_type": "customer",
            "sender_name": "Ahmed Mohamed",
            "sender_id": 1,
            "message_type": "text",
            "content": "When will my order be ready?",
            "is_read": true,
            "created_at": "2026-01-27T10:00:00Z"
        },
        {
            "id": 2,
            "chat_type": "shop_customer",
            "sender_type": "shop_owner",
            "sender_name": "My Shop",
            "sender_id": 1,
            "message_type": "text",
            "content": "About 15 minutes",
            "is_read": false,
            "created_at": "2026-01-27T10:01:00Z"
        }
    ]
}
```

### New Message Event
```json
{
    "type": "chat_message",
    "data": {
        "id": 3,
        "order": 1,
        "chat_type": "shop_customer",
        "sender_type": "customer",
        "sender_name": "Ahmed Mohamed",
        "sender_id": 1,
        "message_type": "text",
        "content": "Thank you!",
        "is_read": false,
        "created_at": "2026-01-27T10:05:00Z"
    }
}
```

---

## ✅ Mark as Read

### Send Mark Read Event
```json
{
    "type": "mark_read"
}
```

### Response
```json
{
    "type": "messages_marked_read",
    "count": 5
}
```

---

## ⌨️ Typing Indicator

### Send Typing Event
```json
{
    "type": "typing"
}
```

### Receive Typing Event
```json
{
    "type": "typing",
    "data": {
        "user_type": "customer",
        "user_name": "Ahmed"
    }
}
```

---

## Ring / Nudge Event

This is a lightweight notification only. It does **not** open a call and the backend does **not** stream any sound.
The frontend should play the ringtone or show the visual notification when it receives the event.

### Send Ring Event

You can send it through:

- chat socket `/ws/chat/order/{order_id}/?...`
- shop orders socket `/ws/orders/shop/{shop_owner_id}/?...`
- customer orders socket `/ws/orders/customer/{customer_id}/?...`
- driver socket `/ws/driver/{driver_id}/?...`

Client payload:

```json
{
    "type": "ring",
    "request_id": "ring-101",
    "order_id": 15,
    "target": "driver"
}
```

Supported targets:

- `shop`
- `customer`
- `driver`

You can also send multiple targets:

```json
{
    "type": "ring",
    "request_id": "ring-102",
    "order_id": 15,
    "targets": ["customer", "driver"]
}
```

### Ring Ack

```json
{
    "type": "ack",
    "action": "ring",
    "success": true,
    "request_id": "ring-101",
    "data": {
        "order_id": 15,
        "shop": {
            "id": 3,
            "name": "برجر كنچ",
            "profile_image_url": "/media/shops/logo.png"
        },
        "shop_id": 3,
        "shop_name": "برجر كنچ",
        "shop_profile_image_url": "/media/shops/logo.png",
        "targets": ["driver"],
        "unavailable_targets": [],
        "ring_id": "uuid-value"
    }
}
```

### Receive Ring Event

```json
{
    "type": "ring",
    "data": {
        "ring_id": "uuid-value",
        "order_id": 15,
        "order_number": "OD12345",
        "shop": {
            "id": 3,
            "name": "برجر كنچ",
            "profile_image_url": "/media/shops/logo.png"
        },
        "shop_id": 3,
        "shop_name": "برجر كنچ",
        "shop_profile_image_url": "/media/shops/logo.png",
        "sender_type": "customer",
        "sender_name": "Ahmed",
        "sender_id": 7,
        "target": "driver",
        "targets": ["driver"],
        "chat_type": "driver_customer",
        "notification_kind": "ring",
        "play_sound_on_frontend": true,
        "created_at": "2026-03-28T20:15:00+02:00"
    }
}
```

---

## 🔔 Notifications

When a new message is sent, the system automatically notifies:

### For shop_customer Messages
- **Shop Owner**: via `shop_orders_{shop_id}` channel
- **Customer**: via `customer_orders_{customer_id}` channel

### For driver_customer Messages
- **Driver**: via `driver_{driver_id}` channel
- **Customer**: via `customer_orders_{customer_id}` channel

---

## 💻 JavaScript Implementation

```javascript
class ChatManager {
    constructor(orderId, chatType, token) {
        this.orderId = orderId;
        this.chatType = chatType;
        this.token = token;
        this.socket = null;
    }
    
    connect() {
        const url = `ws://86.48.3.103/ws/chat/order/${this.orderId}/?token=${this.token}&chat_type=${this.chatType}`;
        this.socket = new WebSocket(url);
        
        this.socket.onopen = () => {
            console.log('Chat connected');
        };
        
        this.socket.onmessage = (event) => {
            const data = JSON.parse(event.data);
            this.handleMessage(data);
        };
        
        this.socket.onclose = () => {
            console.log('Chat disconnected');
            // Reconnect after 3 seconds
            setTimeout(() => this.connect(), 3000);
        };
    }
    
    handleMessage(data) {
        switch (data.type) {
            case 'previous_messages':
                this.displayMessages(data.messages);
                break;
            case 'chat_message':
                this.displayMessage(data.data);
                break;
            case 'typing':
                this.showTypingIndicator(data.data);
                break;
            case 'messages_marked_read':
                this.updateReadStatus();
                break;
        }
    }
    
    sendMessage(content, messageType = 'text') {
        this.socket.send(JSON.stringify({
            type: 'send_message',
            message_type: messageType,
            content: content
        }));
    }
    
    sendLocation(lat, lng) {
        this.socket.send(JSON.stringify({
            type: 'send_message',
            message_type: 'location',
            latitude: lat,
            longitude: lng
        }));
    }
    
    markAsRead() {
        this.socket.send(JSON.stringify({
            type: 'mark_read'
        }));
    }
    
    sendTyping() {
        this.socket.send(JSON.stringify({
            type: 'typing'
        }));
    }
    
    disconnect() {
        if (this.socket) {
            this.socket.close();
        }
    }
}

// Usage
const chat = new ChatManager(1, 'shop_customer', 'your-jwt-token');
chat.connect();
chat.sendMessage('Hello!');
```

---

## 📁 Related Files

- `shop/consumers.py` - `ChatConsumer` class
- `shop/routing.py` - WebSocket URL routing
- `shop/models.py` - `ChatMessage` model
- `shop/serializers.py` - `ChatMessageSerializer`
- `frontend_test.html` - Testing interface

---

## ⚠️ Important Notes

1. **Authentication Required**: All WebSocket connections require valid JWT token
2. **Order Ownership**: Users can only access chats for orders they're involved in
3. **Message Persistence**: All messages are saved to database
4. **File Uploads**: Audio and image messages should be sent via REST API, not WebSocket
5. **Reconnection**: Implement auto-reconnection in frontend for better UX

---

## Customer Orders Dashboard Snapshot

The customer orders socket `/ws/orders/customer/{customer_id}/?...` now streams the customer dashboard lists directly over WebSocket, so the frontend does not need to fetch these lists over HTTP just to render the tabs:

- `/api/customer/orders/`
- `/api/customer/shops-conversations/`
- `/api/customer/orders/on-way/`

### Initial Snapshot Events

Immediately after the socket connects, the backend sends:

- `dashboard_snapshot`
- `orders_snapshot`
- `shops_snapshot`
- `on_way_snapshot`

`dashboard_snapshot` is the primary event and contains all three lists in one payload.

`orders_snapshot`:

```json
{
    "type": "orders_snapshot",
    "data": {
        "orders": [
            {
                "...": "same shape as OrderSerializer"
            }
        ]
    }
}
```

`shops_snapshot`:

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
    }
}
```

`on_way_snapshot`:

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
                "driver_id": 12,
                "driver_name": "أحمد محمود",
                "chat": {
                    "order_id": 15,
                    "chat_type": "driver_customer",
                    "driver_id": 12
                }
            }
        ]
    }
}
```

### Manual Resync

The frontend can request a fresh snapshot from the same socket:

```json
{
    "type": "sync_dashboard",
    "request_id": "sync-1001"
}
```

Ack:

```json
{
    "type": "ack",
    "action": "sync_dashboard",
    "success": true,
    "request_id": "sync-1001"
}
```

The backend also re-sends the three snapshot events after `order_update` and `new_message` so the customer tabs stay in sync without polling.
