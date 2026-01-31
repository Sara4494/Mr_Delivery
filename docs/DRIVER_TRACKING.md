# 🚗 Driver Tracking System

Real-time driver location tracking for delivery orders.

---

## 📋 Overview

The driver tracking system allows:
- Drivers to update their location in real-time
- Customers to track their delivery
- Shop owners to monitor driver locations

---

## 🔌 Driver Location Update

### REST API
```http
PUT /api/driver/location/
Authorization: Bearer {driver_token}
Content-Type: application/json

{
    "latitude": "24.7136",
    "longitude": "46.6753"
}
```

**Response:**
```json
{
    "status": 200,
    "message": "Location updated successfully",
    "data": {
        "latitude": "24.7136",
        "longitude": "46.6753",
        "updated_at": "2026-01-27T10:30:00Z"
    }
}
```

### WebSocket (Real-time)

Connect to driver channel:
```
ws://server/ws/driver/{driver_id}/?token=JWT
```

Send location update:
```json
{
    "type": "location_update",
    "latitude": "24.7136",
    "longitude": "46.6753"
}
```

---

## 📍 Customer Tracking

### Get Current Location
```http
GET /api/shop/orders/{order_id}/track/
Authorization: Bearer {customer_token}
```

**Response:**
```json
{
    "status": 200,
    "message": "Tracking data retrieved",
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
        },
        "delivery_address": {
            "full_address": "123 Street, City",
            "latitude": "24.7200",
            "longitude": "46.6800"
        }
    }
}
```

### Real-time Location Updates (WebSocket)

Connect to customer channel:
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

## 💻 Implementation Examples

### Driver App (JavaScript)

```javascript
class DriverTracker {
    constructor(driverId, token) {
        this.driverId = driverId;
        this.token = token;
        this.socket = null;
        this.watchId = null;
    }
    
    connect() {
        this.socket = new WebSocket(
            `ws://server/ws/driver/${this.driverId}/?token=${this.token}`
        );
        
        this.socket.onopen = () => {
            console.log('Connected to driver channel');
            this.startTracking();
        };
        
        this.socket.onmessage = (event) => {
            const data = JSON.parse(event.data);
            if (data.type === 'new_order') {
                this.handleNewOrder(data.data);
            }
        };
    }
    
    startTracking() {
        if ('geolocation' in navigator) {
            this.watchId = navigator.geolocation.watchPosition(
                (position) => {
                    this.sendLocation(
                        position.coords.latitude,
                        position.coords.longitude
                    );
                },
                (error) => console.error('GPS Error:', error),
                {
                    enableHighAccuracy: true,
                    maximumAge: 10000,
                    timeout: 5000
                }
            );
        }
    }
    
    sendLocation(latitude, longitude) {
        if (this.socket && this.socket.readyState === WebSocket.OPEN) {
            this.socket.send(JSON.stringify({
                type: 'location_update',
                latitude: latitude.toString(),
                longitude: longitude.toString()
            }));
        }
    }
    
    stopTracking() {
        if (this.watchId) {
            navigator.geolocation.clearWatch(this.watchId);
        }
        if (this.socket) {
            this.socket.close();
        }
    }
}

// Usage
const tracker = new DriverTracker(1, 'driver-jwt-token');
tracker.connect();
```

### Customer App (JavaScript)

```javascript
class DeliveryTracker {
    constructor(customerId, token) {
        this.customerId = customerId;
        this.token = token;
        this.socket = null;
        this.map = null;
        this.driverMarker = null;
    }
    
    connect() {
        this.socket = new WebSocket(
            `ws://server/ws/orders/customer/${this.customerId}/?token=${this.token}`
        );
        
        this.socket.onmessage = (event) => {
            const data = JSON.parse(event.data);
            
            if (data.type === 'driver_location') {
                this.updateDriverLocation(data.data);
            } else if (data.type === 'order_update') {
                this.handleOrderUpdate(data.data);
            }
        };
    }
    
    updateDriverLocation(location) {
        const lat = parseFloat(location.latitude);
        const lng = parseFloat(location.longitude);
        
        // Update map marker (using Google Maps example)
        if (this.driverMarker) {
            this.driverMarker.setPosition({ lat, lng });
        } else {
            this.driverMarker = new google.maps.Marker({
                position: { lat, lng },
                map: this.map,
                icon: '/images/driver-icon.png',
                title: 'Driver'
            });
        }
        
        // Update ETA display
        this.updateETA(lat, lng);
    }
    
    handleOrderUpdate(order) {
        // Update order status UI
        document.getElementById('order-status').textContent = order.status;
        
        if (order.status === 'delivered') {
            this.showDeliveredMessage();
            this.disconnect();
        }
    }
    
    disconnect() {
        if (this.socket) {
            this.socket.close();
        }
    }
}

// Usage
const deliveryTracker = new DeliveryTracker(1, 'customer-jwt-token');
deliveryTracker.connect();
```

---

## 🗄️ Database Fields

### Driver Model Location Fields

| Field | Type | Description |
|-------|------|-------------|
| `current_latitude` | Decimal(10,7) | Current latitude |
| `current_longitude` | Decimal(10,7) | Current longitude |
| `location_updated_at` | DateTime | Last update timestamp |

---

## 📡 Broadcast Flow

```
Driver sends location
        │
        ▼
┌─────────────────┐
│ Driver Consumer │
└─────────────────┘
        │
        ▼
┌─────────────────┐
│ Update Database │
└─────────────────┘
        │
        ▼
┌─────────────────────────┐
│ Get Active Orders with  │
│ this Driver             │
└─────────────────────────┘
        │
        ▼
┌─────────────────────────┐
│ Broadcast to Customers  │
│ via customer_orders_X   │
└─────────────────────────┘
```

---

## ⚙️ Configuration

### Update Frequency
- **Recommended**: Every 10-30 seconds
- **High accuracy mode**: Every 5 seconds (more battery usage)

### Location Precision
- Latitude/Longitude: 7 decimal places
- Accuracy: ~1.1 centimeters

---

## 🔐 Security Considerations

1. **Driver Authentication**: Only authenticated drivers can update their location
2. **Customer Access**: Customers can only track orders they own
3. **Location Privacy**: Location data is only shared during active deliveries
4. **Data Retention**: Consider clearing old location data periodically

---

## 📁 Related Files

- `shop/models.py` - Driver model with location fields
- `shop/views.py` - `driver_location_update_view`, `order_tracking_view`
- `shop/consumers.py` - `DriverConsumer` class
- `shop/websocket_utils.py` - `broadcast_driver_location` function
