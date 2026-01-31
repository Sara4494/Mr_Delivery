# 📦 Orders Management

Complete guide to order management in Mr Delivery.

---

## 📋 Order Status Flow

```
┌─────────┐     ┌───────────┐     ┌───────────┐     ┌────────┐     ┌───────────┐
│   NEW   │ ──► │ CONFIRMED │ ──► │ PREPARING │ ──► │ ON_WAY │ ──► │ DELIVERED │
└─────────┘     └───────────┘     └───────────┘     └────────┘     └───────────┘
      │                                                                    
      │                        ┌───────────┐                              
      └──────────────────────► │ CANCELLED │                              
                               └───────────┘                              
```

### Status Values
| Status | Arabic | Description |
|--------|--------|-------------|
| `new` | جديد | New order received |
| `confirmed` | مؤكد | Order confirmed by shop |
| `preparing` | قيد التحضير | Being prepared |
| `on_way` | في الطريق | Out for delivery |
| `delivered` | تم التوصيل | Successfully delivered |
| `cancelled` | ملغي | Order cancelled |

---

## 🔌 API Endpoints

### List Orders
```http
GET /api/shop/orders/
Authorization: Bearer {shop_owner_token}

Query Parameters:
  - status: Filter by status (new, preparing, etc.)
  - search: Search by order number or customer name
  - sort_by: Sort field (-created_at, total_amount)
  - page: Page number
  - page_size: Items per page (default: 20)
```

**Response:**
```json
{
    "status": 200,
    "data": {
        "results": [
            {
                "id": 1,
                "order_number": "ORD-20260127-001",
                "customer": {
                    "id": 1,
                    "name": "Ahmed Mohamed",
                    "phone_number": "01012345678"
                },
                "items": "2x Burger, 1x Fries",
                "total_amount": "75.00",
                "delivery_fee": "10.00",
                "status": "new",
                "status_display": "جديد",
                "address": "123 Street, City",
                "notes": "No onions please",
                "created_at": "2026-01-27T10:00:00Z"
            }
        ],
        "count": 50,
        "next": "http://server/api/shop/orders/?page=2",
        "previous": null
    }
}
```

### Create Order
```http
POST /api/shop/orders/
Authorization: Bearer {shop_owner_token}
Content-Type: application/json

{
    "customer_id": 1,
    "items": "2x Burger, 1x Fries, 1x Cola",
    "total_amount": "75.00",
    "delivery_fee": "10.00",
    "address": "123 Street, Building 5, Floor 2",
    "notes": "Ring the bell twice",
    "payment_method": "cash"
}
```

**Response:**
```json
{
    "status": 201,
    "message": "Order created successfully",
    "data": {
        "id": 1,
        "order_number": "ORD-20260127-001",
        "status": "new",
        ...
    }
}
```

### Get Order Details
```http
GET /api/shop/orders/{order_id}/
Authorization: Bearer {shop_owner_token}
```

### Update Order
```http
PUT /api/shop/orders/{order_id}/
Authorization: Bearer {shop_owner_token}
Content-Type: application/json

{
    "status": "preparing",
    "driver_id": 1,
    "employee_id": 2
}
```

### Delete Order
```http
DELETE /api/shop/orders/{order_id}/
Authorization: Bearer {shop_owner_token}
```

---

## 🚗 Assign Driver

```http
PUT /api/shop/orders/{order_id}/
Authorization: Bearer {shop_owner_token}
Content-Type: application/json

{
    "driver_id": 1,
    "status": "on_way"
}
```

When a driver is assigned:
1. Order status can be updated to `on_way`
2. Driver receives WebSocket notification
3. Customer can track driver location

---

## 📍 Order Tracking

### Get Tracking Info
```http
GET /api/shop/orders/{order_id}/track/
Authorization: Bearer {customer_token}
```

**Response:**
```json
{
    "status": 200,
    "data": {
        "order": {
            "id": 1,
            "order_number": "ORD-20260127-001",
            "status": "on_way",
            "estimated_delivery_time": 15
        },
        "driver": {
            "id": 1,
            "name": "Mohamed Ali",
            "phone_number": "01000000001",
            "current_latitude": "24.7136",
            "current_longitude": "46.6753",
            "location_updated_at": "2026-01-27T10:30:00Z"
        }
    }
}
```

### Real-time Driver Location (WebSocket)

Connect to customer WebSocket:
```
ws://server/ws/orders/customer/{customer_id}/?token=JWT
```

Receive location updates:
```json
{
    "type": "driver_location",
    "data": {
        "driver_id": 1,
        "latitude": "24.7140",
        "longitude": "46.6760",
        "updated_at": "2026-01-27T10:31:00Z"
    }
}
```

---

## ⭐ Order Rating

### Submit Rating (Customer)
```http
POST /api/orders/rate/
Authorization: Bearer {customer_token}
Content-Type: application/json

{
    "order_id": 1,
    "shop_rating": 5,
    "driver_rating": 4,
    "food_rating": 5,
    "comment": "Excellent service and fast delivery!"
}
```

**Validation:**
- Rating values: 1-5
- Order must be `delivered`
- Can only rate once per order

### View Rating (Shop Owner)
```http
GET /api/shop/orders/{order_id}/rating/
Authorization: Bearer {shop_owner_token}
```

---

## 🔔 Order Notifications (WebSocket)

### Shop Owner/Employee

Connect to:
```
ws://server/ws/orders/shop/{shop_owner_id}/?token=JWT
```

Events received:
```json
// New order
{
    "type": "new_order",
    "data": { "id": 1, "order_number": "ORD-001", ... }
}

// Order update
{
    "type": "order_update",
    "data": { "id": 1, "status": "delivered", ... }
}

// New message from customer
{
    "type": "new_message",
    "data": { "order_id": 1, "content": "Hello", ... }
}
```

### Customer

Connect to:
```
ws://server/ws/orders/customer/{customer_id}/?token=JWT
```

Events received:
```json
// Order status update
{
    "type": "order_update",
    "data": { "id": 1, "status": "on_way", ... }
}

// Driver location
{
    "type": "driver_location",
    "data": { "latitude": "24.7136", "longitude": "46.6753" }
}
```

### Driver

Connect to:
```
ws://server/ws/driver/{driver_id}/?token=JWT
```

Events received:
```json
// New order assignment
{
    "type": "new_order",
    "data": { "id": 1, "delivery_address": "123 Street", ... }
}

// Order update
{
    "type": "order_update",
    "data": { "id": 1, "status": "preparing", ... }
}
```

---

## 💳 Payment Methods

| Value | Description |
|-------|-------------|
| `cash` | Cash on delivery |
| `card` | Credit/Debit card |
| `wallet` | Digital wallet |

---

## 📊 Order Model Fields

| Field | Type | Description |
|-------|------|-------------|
| `id` | Integer | Primary key |
| `order_number` | String | Unique order number |
| `shop_owner` | FK | Shop owner |
| `customer` | FK | Customer |
| `employee` | FK | Assigned employee (optional) |
| `driver` | FK | Assigned driver (optional) |
| `delivery_address` | FK | Customer address (optional) |
| `items` | Text | Order items description |
| `total_amount` | Decimal | Total price |
| `delivery_fee` | Decimal | Delivery fee |
| `address` | Text | Delivery address text |
| `notes` | Text | Customer notes |
| `status` | String | Order status |
| `payment_method` | String | Payment method |
| `is_paid` | Boolean | Payment status |
| `estimated_delivery_time` | Integer | Minutes |
| `delivered_at` | DateTime | Delivery timestamp |
| `unread_messages_count` | Integer | Unread chat messages |
| `created_at` | DateTime | Order creation time |
| `updated_at` | DateTime | Last update time |

---

## 📁 Related Files

- `shop/models.py` - Order model
- `shop/views.py` - Order views
- `shop/serializers.py` - OrderSerializer, OrderCreateSerializer
- `shop/consumers.py` - WebSocket consumers
