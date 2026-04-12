# Driver Realtime Orders + Chat Handoff

## Goal

This document defines the backend contract that the Flutter team should implement for the driver app realtime flow.

Scope in this document:

- Available delivery orders
- Assigned driver orders
- Driver order details
- Driver-to-customer chat
- Order transfer

Out of scope:

- Invitation flow
- Shop-to-driver invitation chats

---

## High-Level Design

Use 2 websocket connections:

1. Driver realtime socket
   - Used for available orders, assigned orders, order state changes
   - One socket per logged-in driver

2. Driver-customer chat socket
   - Opened only when driver presses the chat icon
   - One socket per order chat session

Why 2 sockets:

- Order updates and chat traffic should stay separate
- Chat events are noisy and should not affect order-list screens
- Flutter can manage lifecycle more cleanly

---

## Authentication

All REST endpoints require the normal driver JWT.

All websocket connections require the same JWT in query params:

```text
?token=<JWT_TOKEN>&lang=ar
```

---

## Realtime Socket

### URL

```text
ws://<host>/ws/driver/<driver_id>/?token=<JWT_TOKEN>&lang=ar
```

### Socket Responsibilities

- Available orders screen
- Assigned orders screen
- Remove order when cancelled/transferred/taken by another driver
- Update order detail screen in realtime

---

## Chat Socket

### URL

```text
ws://<host>/ws/chat/order/<order_id>/?token=<JWT_TOKEN>&chat_type=driver_customer&lang=ar
```

### Chat Rule

The driver-customer chat must not start automatically after order acceptance.

It starts only when the driver presses the chat button for the first time.

---

## REST Endpoints

### 1. Get available orders

```http
GET /api/driver/orders/available/
```

Response:

```json
{
  "success": true,
  "data": {
    "results": [
      {
        "order_id": 123,
        "order_number": "10294",
        "status": "pending",
        "driver_status": "pending",
        "shop": {
          "id": 7,
          "name": "صيدلية الشفاء",
          "logo_url": null,
          "branch_label": "منطقة التجمع"
        },
        "customer": {
          "id": 22,
          "name": "أحمد محمود",
          "phone_number": "01000000000",
          "profile_image_url": null
        },
        "delivery_address": {
          "id": 11,
          "text": "شارع التسعين الشمالي، التجمع",
          "latitude": 30.0,
          "longitude": 31.0,
          "landmark": "بجوار بنك مصر"
        },
        "distance_km": 2.5,
        "payment_method": {
          "code": "cash",
          "label": "نقدي عند الاستلام"
        },
        "collection_amount": 150.0,
        "delivery_fee": 20.0,
        "invoice": {
          "items": [
            {
              "name": "وجبة برجر كلاسيك",
              "quantity": 2,
              "line_total": 100.0
            }
          ],
          "subtotal": 130.0,
          "total": 150.0
        },
        "timestamps": {
          "created_at": "2026-04-12T20:00:00Z",
          "updated_at": "2026-04-12T20:10:00Z",
          "accepted_at": null,
          "assigned_at": null
        }
      }
    ]
  }
}
```

### 2. Accept available order

```http
POST /api/driver/orders/{order_id}/accept/
```

Response:

```json
{
  "success": true,
  "data": {
    "order": {
      "order_id": 123,
      "status": "assigned",
      "driver_status": "assigned"
    }
  }
}
```

### 3. Reject available order

```http
POST /api/driver/orders/{order_id}/reject/
```

Response:

```json
{
  "success": true,
  "data": {
    "order_id": 123,
    "status": "rejected",
    "driver_status": "rejected"
  }
}
```

### 4. Get assigned orders

```http
GET /api/driver/orders/
```

This screen contains only orders already accepted/assigned to the current driver.

### 5. Get order details

```http
GET /api/driver/orders/{order_id}/
```

Must include:

- Order data
- Customer data
- Delivery address
- Invoice details
- Payment method
- Collection amount
- Chat availability
- Transfer availability

### 6. Transfer order

```http
POST /api/driver/orders/{order_id}/transfer/
```

Body:

```json
{
  "reason_key": "vehicle_issue",
  "note": ""
}
```

Allowed `reason_key` values:

- `vehicle_issue`
- `emergency`
- `store_delay`
- `other`

If `reason_key=other`, `note` is required.

### 7. Open driver-customer chat

```http
POST /api/driver/orders/{order_id}/chat/open/
```

Purpose:

- If chat does not exist yet, create it logically
- If chat already exists, return the existing session

Response:

```json
{
  "success": true,
  "data": {
    "conversation_id": "order_123_driver_customer",
    "order_id": 123,
    "created": true,
    "chat_type": "driver_customer",
    "ws_url": "/ws/chat/order/123/?token=<JWT>&chat_type=driver_customer&lang=ar"
  }
}
```

### 8. Get chat messages

```http
GET /api/driver/orders/{order_id}/chat/
```

### 9. Send chat message using REST fallback

```http
POST /api/driver/orders/{order_id}/chat/
```

Body:

```json
{
  "message_type": "text",
  "content": "أنا في الطريق"
}
```

Primary chat transport should still be WebSocket.

---

## Driver Status Mapping

Backend may keep internal order statuses as currently implemented, but Flutter should rely on `driver_status`.

### Driver-facing statuses

- `pending`
- `accepted`
- `assigned`
- `in_delivery`
- `transferred`
- `cancelled`
- `rejected`

### Recommended mapping

- internal `confirmed` -> `pending` or `assigned`
- internal `preparing` -> `assigned`
- internal `on_way` -> `in_delivery`
- internal `cancelled` -> `cancelled`

The backend should always send both:

- `status`: raw backend status
- `driver_status`: normalized driver-app status

---

## WebSocket Event Envelope

All driver realtime events should use this envelope:

```json
{
  "type": "driver.available_orders.upsert",
  "event_id": "evt_123",
  "occurred_at": "2026-04-12T20:15:00Z",
  "data": {}
}
```

Fields:

- `type`: event name
- `event_id`: unique event id
- `occurred_at`: ISO UTC timestamp
- `data`: event payload

---

## Driver Realtime Events

### 1. Initial snapshot for available orders

```json
{
  "type": "driver.available_orders.snapshot",
  "event_id": "evt_1",
  "occurred_at": "2026-04-12T20:15:00Z",
  "data": {
    "results": []
  }
}
```

### 2. Add or update available order

```json
{
  "type": "driver.available_orders.upsert",
  "event_id": "evt_2",
  "occurred_at": "2026-04-12T20:15:01Z",
  "data": {
    "order": {
      "order_id": 123,
      "status": "pending",
      "driver_status": "pending"
    }
  }
}
```

### 3. Remove available order

```json
{
  "type": "driver.available_orders.remove",
  "event_id": "evt_3",
  "occurred_at": "2026-04-12T20:15:02Z",
  "data": {
    "order_id": 123,
    "reason": "accepted_by_another_driver"
  }
}
```

### 4. Initial snapshot for assigned orders

```json
{
  "type": "driver.assigned_orders.snapshot",
  "event_id": "evt_4",
  "occurred_at": "2026-04-12T20:15:03Z",
  "data": {
    "results": []
  }
}
```

### 5. Add or update assigned order

```json
{
  "type": "driver.assigned_orders.upsert",
  "event_id": "evt_5",
  "occurred_at": "2026-04-12T20:15:04Z",
  "data": {
    "order": {
      "order_id": 123,
      "status": "assigned",
      "driver_status": "assigned"
    }
  }
}
```

### 6. Remove assigned order

```json
{
  "type": "driver.assigned_orders.remove",
  "event_id": "evt_6",
  "occurred_at": "2026-04-12T20:15:05Z",
  "data": {
    "order_id": 123,
    "reason": "transferred"
  }
}
```

### 7. Order detail changed

```json
{
  "type": "driver.order.updated",
  "event_id": "evt_7",
  "occurred_at": "2026-04-12T20:15:06Z",
  "data": {
    "order": {
      "order_id": 123,
      "status": "in_delivery",
      "driver_status": "in_delivery"
    }
  }
}
```

### 8. Accepted confirmation

```json
{
  "type": "driver.order.accepted",
  "event_id": "evt_8",
  "occurred_at": "2026-04-12T20:15:07Z",
  "data": {
    "order_id": 123
  }
}
```

### 9. Rejected confirmation

```json
{
  "type": "driver.order.rejected",
  "event_id": "evt_9",
  "occurred_at": "2026-04-12T20:15:08Z",
  "data": {
    "order_id": 123
  }
}
```

### 10. Transferred

```json
{
  "type": "driver.order.transferred",
  "event_id": "evt_10",
  "occurred_at": "2026-04-12T20:15:09Z",
  "data": {
    "order_id": 123,
    "reason_key": "vehicle_issue",
    "reason_label": "عطل في المركبة"
  }
}
```

### 11. Cancelled

```json
{
  "type": "driver.order.cancelled",
  "event_id": "evt_11",
  "occurred_at": "2026-04-12T20:15:10Z",
  "data": {
    "order_id": 123
  }
}
```

---

## Chat Events

Chat socket uses the existing `driver_customer` order chat channel.

### On connect

```json
{
  "type": "driver.chat.ready",
  "data": {
    "order_id": 123,
    "chat_type": "driver_customer"
  }
}
```

### New message

```json
{
  "type": "driver.chat.message.created",
  "data": {
    "order_id": 123,
    "message": {
      "id": 1,
      "message_type": "text",
      "content": "أنا في الطريق",
      "created_at": "2026-04-12T20:20:00Z",
      "is_mine": true
    }
  }
}
```

### Mark as read

```json
{
  "type": "driver.chat.message.read",
  "data": {
    "order_id": 123
  }
}
```

---

## Flutter Screen Behavior

### Available Orders Screen

- Load initial data from `GET /api/driver/orders/available/`
- Subscribe to driver socket
- On `driver.available_orders.upsert`: insert or update card
- On `driver.available_orders.remove`: remove card
- On accept success:
  - remove from available list
  - add to assigned list

### Assigned Orders Screen

- Load initial data from `GET /api/driver/orders/`
- Subscribe to driver socket
- On `driver.assigned_orders.upsert`: insert or update card
- On `driver.assigned_orders.remove`: remove card
- On `driver.order.updated`: update visible detail screen if open

### Order Detail Screen

- Load from `GET /api/driver/orders/{id}/`
- Keep listening to driver socket
- If event belongs to same `order_id`, update UI in place
- If transferred/cancelled, close or pop screen with refresh

### Chat Screen

- Do not open automatically after accept
- When driver presses chat:
  1. call `POST /api/driver/orders/{id}/chat/open/`
  2. connect to returned chat websocket
  3. load old messages from `GET /api/driver/orders/{id}/chat/`

---

## Acceptance Flow

1. Shop sends order for delivery
2. Backend publishes `driver.available_orders.upsert`
3. Driver taps accept
4. Flutter calls `POST /api/driver/orders/{id}/accept/`
5. Backend responds success and emits:
   - `driver.available_orders.remove`
   - `driver.assigned_orders.upsert`
   - `driver.order.accepted`

---

## Reject Flow

1. Driver taps reject
2. Flutter calls `POST /api/driver/orders/{id}/reject/`
3. Backend emits:
   - `driver.available_orders.remove`
4. If business logic reoffers order later, backend may emit another `driver.available_orders.upsert`

---

## Transfer Flow

1. Driver opens transfer screen
2. Flutter loads transfer reasons from:

```http
GET /api/driver/orders/transfer-reasons/
```

3. Driver submits:

```http
POST /api/driver/orders/{id}/transfer/
```

4. Backend emits for current driver:
   - `driver.assigned_orders.remove`
   - `driver.order.transferred`

5. Backend may emit for another driver:
   - `driver.available_orders.upsert`
   - or `driver.assigned_orders.upsert`

Depending on assignment strategy.

---

## Cancellation Flow

If order is cancelled by store or system:

- remove from available list if still pending
- remove from assigned list if already assigned
- emit `driver.order.cancelled`

---

## Required Backend Guarantees

- Accept must be atomic
- Two drivers must not accept the same order successfully
- Every event must carry `order_id`
- Payload shape must stay stable
- `driver_status` must always be included

---

## Recommended Flutter Models

### DriverRealtimeOrder

```json
{
  "order_id": 123,
  "order_number": "10294",
  "status": "confirmed",
  "driver_status": "assigned",
  "shop": {},
  "customer": {},
  "delivery_address": {},
  "distance_km": 2.5,
  "payment_method": {},
  "collection_amount": 150.0,
  "delivery_fee": 20.0,
  "invoice": {},
  "timestamps": {}
}
```

### DriverRealtimeEvent

```json
{
  "type": "driver.assigned_orders.upsert",
  "event_id": "evt_123",
  "occurred_at": "2026-04-12T20:15:00Z",
  "data": {}
}
```

---

## Backend Notes

Current project already has:

- driver realtime socket base: `ws/driver/{driver_id}/`
- driver orders list: `GET /api/driver/orders/`
- driver transfer: `POST /api/driver/orders/{id}/transfer/`
- driver order chat: `GET/POST /api/driver/orders/{id}/chat/`
- order chat websocket base: `ws/chat/order/{order_id}/?chat_type=driver_customer`

What still needs backend implementation/normalization:

- `GET /api/driver/orders/available/`
- `POST /api/driver/orders/{id}/accept/`
- `POST /api/driver/orders/{id}/reject/`
- `POST /api/driver/orders/{id}/chat/open/`
- unified realtime event names above
- stable driver order payload with full details

---

## Delivery Checklist For Flutter

- Implement one driver realtime socket after login
- Keep local stores for:
  - available orders
  - assigned orders
  - open order details
- Open chat socket only on chat button press
- Handle remove events immediately
- Use `driver_status` for UI state, not raw backend status
# Driver Realtime Orders + Chat Handoff

## Scope

- Available delivery orders
- Assigned driver orders
- Driver order details
- Driver-to-customer chat
- Order transfer

Out of scope:

- Invitation flow
- Shop-to-driver invitation chats

## Recommended Transport Split

Use 2 websocket connections:

1. `ws/driver/{driver_id}/`
   Handles available orders, assigned orders, order updates, transfer/cancel/remove events.

2. `ws/chat/order/{order_id}/?chat_type=driver_customer`
   Open only after the driver presses the chat button.

Reason:

- Order traffic and chat traffic stay isolated
- Order screens stay quiet and predictable
- Chat lifecycle becomes explicit and easier on Flutter

## Auth

REST:

- Standard driver JWT

WebSocket:

- `?token=<JWT>&lang=ar`

## REST Endpoints

- `GET /api/driver/orders/available/`
- `POST /api/driver/orders/{order_id}/accept/`
- `POST /api/driver/orders/{order_id}/reject/`
- `GET /api/driver/orders/`
- `GET /api/driver/orders/{order_id}/`
- `GET /api/driver/orders/transfer-reasons/`
- `POST /api/driver/orders/{order_id}/transfer/`
- `POST /api/driver/orders/{order_id}/chat/open/`
- `GET /api/driver/orders/{order_id}/chat/`
- `POST /api/driver/orders/{order_id}/chat/`

## Driver Socket

URL:

```text
ws://<host>/ws/driver/<driver_id>/?token=<JWT>&lang=ar
```

On connect the backend sends:

- `driver.available_orders.snapshot`
- `driver.assigned_orders.snapshot`

## Driver Socket Event Names

- `driver.available_orders.snapshot`
- `driver.available_orders.upsert`
- `driver.available_orders.remove`
- `driver.assigned_orders.snapshot`
- `driver.assigned_orders.upsert`
- `driver.assigned_orders.remove`
- `driver.order.updated`
- `driver.order.accepted`
- `driver.order.rejected`
- `driver.order.transferred`
- `driver.order.cancelled`

## Event Envelope

```json
{
  "type": "driver.available_orders.upsert",
  "sent_at": "2026-04-12T20:10:00Z",
  "data": {}
}
```

## Order Payload

```json
{
  "order_id": 123,
  "order_number": "10294",
  "status": "confirmed",
  "driver_status": "pending",
  "shop": {
    "id": 7,
    "name": "صيدلية الشفاء",
    "logo_url": null,
    "branch_label": "منطقة التجمع"
  },
  "customer": {
    "id": 22,
    "name": "أحمد محمود",
    "phone_number": "01000000000",
    "profile_image_url": null,
    "is_online": false,
    "last_seen": null
  },
  "delivery_address": {
    "id": 11,
    "text": "شارع التسعين الشمالي، التجمع",
    "latitude": 30.0,
    "longitude": 31.0,
    "landmark": "بجوار بنك مصر",
    "city": "القاهرة",
    "area": "التجمع",
    "street_name": "شارع التسعين"
  },
  "distance_km": null,
  "payment_method": {
    "code": "cash",
    "label": "نقداً عند الاستلام"
  },
  "collection_amount": 150.0,
  "invoice": {
    "items": [
      {
        "name": "وجبة برجر كلاسيك",
        "quantity": 2,
        "line_total": 100.0
      }
    ],
    "subtotal": 130.0,
    "delivery_fee": 20.0,
    "total": 150.0
  },
  "chat": {
    "conversation_id": "order_123_driver_customer",
    "chat_type": "driver_customer",
    "can_open": true,
    "ws_path": "/ws/chat/order/123/?chat_type=driver_customer"
  },
  "transfer": {
    "can_transfer": true
  },
  "timestamps": {
    "created_at": "2026-04-12T20:00:00Z",
    "updated_at": "2026-04-12T20:10:00Z",
    "accepted_at": null,
    "assigned_at": null
  }
}
```

## Driver Status Mapping

- Unassigned `confirmed` or `preparing` => `pending`
- Assigned `confirmed` or `preparing` => `assigned`
- Assigned `on_way` => `in_delivery`
- `cancelled` => `cancelled`
- `rejected` and `transferred` are action/event states, not persistent order DB statuses

## Core Flows

### 1. Shop sends order for delivery

1. Order becomes available with no driver
2. Backend emits `driver.available_orders.upsert`
3. Drivers insert/update the card instantly

### 2. Driver accepts order

1. Flutter calls `POST /api/driver/orders/{id}/accept/`
2. Backend assigns the driver atomically
3. Current driver receives:
   - `driver.available_orders.remove`
   - `driver.assigned_orders.upsert`
   - `driver.order.accepted`
4. Other eligible drivers receive:
   - `driver.available_orders.remove`

### 3. Driver rejects order

1. Flutter calls `POST /api/driver/orders/{id}/reject/`
2. Backend stores rejection for this driver only
3. Current driver receives:
   - `driver.available_orders.remove`
   - `driver.order.rejected`
4. Other drivers are unchanged

### 4. Order updated while still available

- Backend emits `driver.available_orders.upsert`

Examples:

- address changed
- invoice changed
- collection amount changed

### 5. Order transferred by current driver

1. Flutter calls `POST /api/driver/orders/{id}/transfer/`
2. Backend removes assignment and returns the order to the available pool
3. Current driver receives:
   - `driver.assigned_orders.remove`
   - `driver.order.transferred`
4. Eligible drivers receive:
   - `driver.available_orders.upsert`

Note:

- Current backend choice is to clear previous rejections when the order returns to the pool after transfer/re-offer

### 6. Order cancelled

- If available:
  - drivers receive `driver.available_orders.remove`
- If assigned:
  - current driver receives `driver.assigned_orders.remove`
  - current driver receives `driver.order.cancelled`

### 7. Open driver-customer chat

1. Driver presses chat icon
2. Flutter calls `POST /api/driver/orders/{id}/chat/open/`
3. Response returns:
   - `conversation_id`
   - `chat_type=driver_customer`
   - `ws_url`
   - `is_new` / `is_existing`
4. Flutter opens chat websocket only then
5. Flutter loads old messages from `GET /api/driver/orders/{id}/chat/`

## Chat Socket

URL:

```text
ws://<host>/ws/chat/order/<order_id>/?token=<JWT>&chat_type=driver_customer&lang=ar
```

Rules:

- Chat does not auto-start on accept
- First press on chat button is the start point
- Existing backend chat channel is reused

## Flutter Screen Rules

### Available Orders Screen

- Load initial state from `GET /api/driver/orders/available/`
- Subscribe to driver socket
- Handle:
  - `driver.available_orders.snapshot`
  - `driver.available_orders.upsert`
  - `driver.available_orders.remove`

### Assigned Orders Screen

- Load initial state from `GET /api/driver/orders/`
- Use `assigned_orders` for the normalized flat payload
- Subscribe to driver socket
- Handle:
  - `driver.assigned_orders.snapshot`
  - `driver.assigned_orders.upsert`
  - `driver.assigned_orders.remove`
  - `driver.order.updated`
  - `driver.order.cancelled`
  - `driver.order.transferred`

### Order Details Screen

- Load from `GET /api/driver/orders/{id}/`
- Keep driver socket connected
- Update UI on `driver.order.updated`

## Important Backend Notes

- No driver-side "delivered" confirmation is included in this flow
- Acceptance is atomic to prevent two drivers from winning the same order
- Rejection is persisted per driver using `DriverOrderRejection`
