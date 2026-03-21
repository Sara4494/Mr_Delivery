# 🔌 WebSocket API Reference

Legacy note: use [WEBSOCKET_CONTRACT.md](./WEBSOCKET_CONTRACT.md) for the current supported contract.

Real-time communication using Django Channels and WebSocket.

---

## 🌐 WebSocket URLs

### Base URL
```
Development: ws://86.48.3.103/ws/
Production: wss://your-domain.com/ws/
```

### Authentication
All WebSocket connections require JWT token in query string:
```
ws://server/ws/endpoint/?token=YOUR_JWT_TOKEN
```

---

## 💬 Chat WebSocket

### Connection URL
```
ws://server/ws/chat/order/{order_id}/?token=JWT&chat_type=shop_customer
```

### Parameters
| Parameter | Required | Values |
|-----------|----------|--------|
| `order_id` | Yes | Order ID number |
| `token` | Yes | JWT access token |
| `chat_type` | Yes | `shop_customer` or `driver_customer` |

### Who Can Connect
| Chat Type | Allowed Users |
|-----------|---------------|
| `shop_customer` | Shop Owner, Employee, Customer |
| `driver_customer` | Driver, Customer |

### Send Message
```json
{
    "type": "send_message",
    "message_type": "text",
    "content": "Hello, how can I help?"
}
```

### Send Location
```json
{
    "type": "send_message",
    "message_type": "location",
    "latitude": "24.7136",
    "longitude": "46.6753",
    "content": "My current location"
}
```

### Mark Messages as Read
```json
{
    "type": "mark_read"
}
```

### Typing Indicator
```json
{
    "type": "typing"
}
```

### Receive Message Event
```json
{
    "type": "chat_message",
    "data": {
        "id": 1,
        "order": 1,
        "chat_type": "shop_customer",
        "sender_type": "shop_owner",
        "sender_name": "Shop Name",
        "sender_id": 1,
        "message_type": "text",
        "content": "Your order is being prepared",
        "is_read": false,
        "created_at": "2026-01-27T10:30:00Z"
    }
}
```

### Receive Previous Messages (on connect)
```json
{
    "type": "previous_messages",
    "messages": [
        {
            "id": 1,
            "sender_type": "customer",
            "sender_name": "Ahmed",
            "content": "When will my order arrive?",
            "created_at": "2026-01-27T10:00:00Z"
        }
    ]
}
```

---

## 🏪 Shop Orders WebSocket

### Connection URL
```
ws://server/ws/orders/shop/{shop_owner_id}/?token=JWT
```

### Who Can Connect
- Shop Owner
- Employee (of that shop)

### Receive Events

#### New Order
```json
{
    "type": "new_order",
    "data": {
        "id": 1,
        "order_number": "ORD-001",
        "customer": { ... },
        "items": "2x Burger",
        "total_amount": "50.00",
        "status": "new"
    }
}
```

#### Order Update
```json
{
    "type": "order_update",
    "data": {
        "id": 1,
        "status": "preparing",
        ...
    }
}
```

#### New Message Notification
```json
{
    "type": "new_message",
    "data": {
        "order_id": 1,
        "sender_type": "customer",
        "content": "Hello",
        ...
    }
}
```

---

## 👤 Customer Orders WebSocket

### Connection URL
```
ws://server/ws/orders/customer/{customer_id}/?token=JWT
```

### Who Can Connect
- Customer (matching customer_id)

### Receive Events

#### Order Update
```json
{
    "type": "order_update",
    "data": {
        "id": 1,
        "status": "on_way",
        "driver": { ... }
    }
}
```

#### Driver Location
```json
{
    "type": "driver_location",
    "data": {
        "driver_id": 1,
        "latitude": "24.7136",
        "longitude": "46.6753",
        "updated_at": "2026-01-27T10:30:00Z"
    }
}
```

#### New Message Notification
```json
{
    "type": "new_message",
    "data": {
        "order_id": 1,
        "sender_type": "shop_owner",
        "content": "Your order is ready",
        ...
    }
}
```

---

## 🚗 Driver WebSocket

### Connection URL
```
ws://server/ws/driver/{driver_id}/?token=JWT
```

### Who Can Connect
- Driver (matching driver_id)

### Send Location Update
```json
{
    "type": "location_update",
    "latitude": "24.7136",
    "longitude": "46.6753"
}
```

### Receive Events

#### New Order Assignment
```json
{
    "type": "new_order",
    "data": {
        "id": 1,
        "order_number": "ORD-001",
        "customer": { ... },
        "delivery_address": "123 Street"
    }
}
```

#### Order Update
```json
{
    "type": "order_update",
    "data": {
        "id": 1,
        "status": "preparing"
    }
}
```

#### New Message
```json
{
    "type": "new_message",
    "data": {
        "order_id": 1,
        "sender_type": "customer",
        "content": "I'm waiting outside"
    }
}
```

---

## 🔌 Connection Examples

### JavaScript Example
```javascript
// Connect to chat
const chatSocket = new WebSocket(
    'ws://86.48.3.103/ws/chat/order/1/?token=' + accessToken + '&chat_type=shop_customer'
);

chatSocket.onopen = function(e) {
    console.log('Connected to chat');
};

chatSocket.onmessage = function(e) {
    const data = JSON.parse(e.data);
    console.log('Received:', data);
    
    if (data.type === 'chat_message') {
        // Handle new message
    } else if (data.type === 'previous_messages') {
        // Handle previous messages on connect
    }
};

// Send message
chatSocket.send(JSON.stringify({
    type: 'send_message',
    message_type: 'text',
    content: 'Hello!'
}));

// Close connection
chatSocket.close();
```

### Python Example
```python
import websocket
import json

def on_message(ws, message):
    data = json.loads(message)
    print(f"Received: {data}")

def on_open(ws):
    ws.send(json.dumps({
        "type": "send_message",
        "message_type": "text",
        "content": "Hello from Python!"
    }))

ws = websocket.WebSocketApp(
    "ws://86.48.3.103/ws/chat/order/1/?token=YOUR_TOKEN&chat_type=shop_customer",
    on_message=on_message,
    on_open=on_open
)
ws.run_forever()
```

---

## ⚠️ Error Handling

### Connection Errors
```json
{
    "type": "error",
    "message": "Unauthorized access"
}
```

### Common Error Codes
| Code | Meaning |
|------|---------|
| 4001 | Invalid token |
| 4003 | Forbidden - no permission |
| 4004 | Order not found |

---

## 📁 Related Files

- `shop/consumers.py` - WebSocket consumers
- `shop/routing.py` - WebSocket URL routing
- `shop/middleware.py` - JWT authentication middleware
- `shop/websocket_utils.py` - Helper functions
- `Mr_Delivery/asgi.py` - ASGI configuration
- `frontend_test.html` - WebSocket testing page
