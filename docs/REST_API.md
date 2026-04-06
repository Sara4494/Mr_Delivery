# 📡 REST API Reference

Complete REST API documentation for Mr Delivery.

---

## 🌐 Base URL

```
Development: http://86.48.3.103/api/
Production: https://your-domain.com/api/
```

---

## 📋 Response Format

All responses follow this structure:

### Success Response
```json
{
    "status": 200,
    "success": true,
    "message": "Operation successful",
    "data": { ... }
}
```

### Error Response
```json
{
    "status": 400,
    "success": false,
    "message": "Error description",
    "errors": { ... }
}
```

---

## 🔐 Authentication

### Login
```http
POST /api/auth/login/
Content-Type: application/json

{
    "role": "customer|shop_owner|employee|driver",
    "phone_number": "01012345678",  // for customer/employee/driver
    "shop_number": "12345",          // for shop_owner
    "password": "password123"
}
```

### Register (Customer)
```http
POST /api/auth/register/
Content-Type: application/json

{
    "role": "customer",
    "name": "Ahmed Mohamed",
    "phone_number": "01012345678",
    "email": "ahmed@example.com",
    "password": "password123"
}
```

### Refresh Token
```http
POST /api/shop/token/refresh/
Content-Type: application/json

{
    "refresh": "your_refresh_token"
}
```

---

## 🏪 Shop Management

### Shop Status
```http
GET /api/shop/status/
Authorization: Bearer {access_token}
```

```http
PUT /api/shop/status/
Authorization: Bearer {access_token}
Content-Type: application/json

{
    "is_open": true,
    "accepting_orders": true
}
```

### Dashboard Statistics
```http
GET /api/shop/dashboard/statistics/
Authorization: Bearer {access_token}
```

---

## 👥 Customer Management (Shop Owner)

### List Customers
```http
GET /api/shop/customers/
Authorization: Bearer {access_token}
```

### Create Customer
```http
POST /api/shop/customers/
Authorization: Bearer {access_token}
Content-Type: application/json

{
    "name": "Customer Name",
    "phone_number": "01012345678",
    "email": "customer@example.com"
}
```

### Get/Update/Delete Customer
```http
GET|PUT|DELETE /api/shop/customers/{customer_id}/
Authorization: Bearer {access_token}
```

---

## 👨‍💼 Employee Management

### List Employees
```http
GET /api/shop/employees/
Authorization: Bearer {access_token}
```

### Create Employee
```http
POST /api/shop/employees/
Authorization: Bearer {access_token}
Content-Type: application/json

{
    "name": "Employee Name",
    "phone_number": "01000000000",
    "password": "password123",
    "role": "cashier"  // cashier, accountant, manager
}
```

### Get/Update/Delete Employee
```http
GET|PUT|DELETE /api/shop/employees/{employee_id}/
Authorization: Bearer {access_token}
```

### Employee Statistics
```http
GET /api/shop/employees/statistics/
Authorization: Bearer {access_token}
```

---

## 🚗 Driver Management

### List Drivers
```http
GET /api/shop/drivers/
Authorization: Bearer {access_token}
```

### Create Driver
```http
POST /api/shop/drivers/
Authorization: Bearer {access_token}
Content-Type: application/json

{
    "name": "Driver Name",
    "phone_number": "01000000001",
    "password": "password123",
    "status": "available"  // available, busy, offline, pending
}
```

### Approve Driver
```http
POST /api/shop/drivers/{driver_id}/approve/
Authorization: Bearer {access_token}
```

### Update Driver Location
```http
PUT /api/driver/location/
Authorization: Bearer {driver_token}
Content-Type: application/json

{
    "latitude": "24.7136",
    "longitude": "46.6753"
}
```

### Driver App Profile
```http
GET /api/user/profile/
Authorization: Bearer {driver_token}
```

Returns:
- `id`
- `name`
- `phone_number`
- `profile_image_url`
- `vehicle_type`
- `stats.overall_rating`
- `stats.completed_orders_count`

### Update Driver Personal Info
```http
PATCH /api/user/profile/
Authorization: Bearer {driver_token}
Content-Type: multipart/form-data
```

Supported fields:
- `name`
- `phone_number` (changing it requires OTP verification first)
- `vehicle_type` (`motorcycle` or `bicycle`)
- `profile_image`

### Driver Phone Change OTP
```http
POST /api/user/profile/phone/send-otp/
POST /api/user/profile/phone/verify-otp/
Authorization: Bearer {driver_token}
Content-Type: application/json
```

Example:
```json
{
    "phone_number": "+201012345678"
}
```

```json
{
    "phone_number": "+201012345678",
    "otp": "123456"
}
```

### Driver Password Change
```http
POST /api/driver/password/change/
Authorization: Bearer {driver_token}
Content-Type: application/json
```

```json
{
    "current_password": "old_password",
    "new_password": "new_password",
    "confirm_password": "new_password"
}
```

### Driver Logout
```http
POST /api/driver/logout/
Authorization: Bearer {driver_token}
Content-Type: application/json
```

---

## 📦 Products & Categories

### Categories
```http
GET /api/shop/categories/
POST /api/shop/categories/
GET|PUT|DELETE /api/shop/categories/{category_id}/
Authorization: Bearer {access_token}
```

### Products
```http
GET /api/shop/products/
POST /api/shop/products/
GET|PUT|DELETE /api/shop/products/{product_id}/
Authorization: Bearer {access_token}
```

**Create Product:**
```json
{
    "name": "Product Name",
    "description": "Description",
    "price": "25.00",
    "discount_price": "20.00",
    "category": 1,
    "is_available": true,
    "is_featured": false
}
```

---

## 📋 Orders

### List Orders
```http
GET /api/shop/orders/
Authorization: Bearer {access_token}

Query Parameters:
- status: new|confirmed|preparing|on_way|delivered|cancelled
- search: order number or customer name
- sort_by: created_at|-created_at|total_amount
- page: 1
- page_size: 20
```

### Create Order
```http
POST /api/shop/orders/
Authorization: Bearer {access_token}
Content-Type: application/json

{
    "customer_id": 1,
    "items": "2x Burger, 1x Fries",
    "total_amount": "50.00",
    "delivery_fee": "10.00",
    "address": "123 Street Name",
    "notes": "No onions"
}
```

### Update Order
```http
PUT /api/shop/orders/{order_id}/
Authorization: Bearer {access_token}
Content-Type: application/json

{
    "status": "preparing",
    "driver_id": 1
}
```

### Track Order
```http
GET /api/shop/orders/{order_id}/track/
Authorization: Bearer {customer_token}
```

---

## 👤 Customer Profile

### Get/Update Profile
```http
GET|PUT|PATCH /api/customer/profile/
Authorization: Bearer {customer_token}
```

**Update body**
```json
{
    "name": "أحمد محمد",
    "phone_number": "01012345678",
    "current_password": "old-password",
    "new_password": "new-password"
}
```

- يدعم `application/json` لتعديل الاسم/الهاتف/الباسورد
- ويدعم `multipart/form-data` عند إرسال `profile_image`
- يمكن استخدام `old_password` بدل `current_password`

### Addresses
```http
GET /api/customer/addresses/
POST /api/customer/addresses/
GET|PUT|DELETE /api/customer/addresses/{address_id}/
Authorization: Bearer {customer_token}
```

**Add Address:**
```json
{
    "title": "Home",
    "address_type": "home",
    "full_address": "123 Street, City",
    "building_number": "15",
    "floor": "2",
    "apartment": "5",
    "latitude": "24.7136",
    "longitude": "46.6753",
    "is_default": true
}
```

### Payment Methods
```http
GET /api/customer/payment-methods/
POST /api/customer/payment-methods/
DELETE /api/customer/payment-methods/{method_id}/
Authorization: Bearer {customer_token}
```

---

## 🛒 Shopping Cart

### View Cart
```http
GET /api/cart/{shop_id}/
Authorization: Bearer {customer_token}
```

### Add to Cart
```http
POST /api/cart/{shop_id}/add/
Authorization: Bearer {customer_token}
Content-Type: application/json

{
    "product_id": 1,
    "quantity": 2,
    "notes": "No onions"
}
```

### Update Cart Item
```http
PUT /api/cart/{shop_id}/items/{item_id}/
Authorization: Bearer {customer_token}
Content-Type: application/json

{
    "quantity": 3
}
```

### Delete Cart Item
```http
DELETE /api/cart/{shop_id}/items/{item_id}/
Authorization: Bearer {customer_token}
```

### Clear Cart
```http
DELETE /api/cart/{shop_id}/clear/
Authorization: Bearer {customer_token}
```

---

## ⭐ Order Rating

### Rate Order (Customer)
```http
POST /api/orders/rate/
Authorization: Bearer {customer_token}
Content-Type: application/json

{
    "order_id": 1,
    "shop_rating": 5,
    "driver_rating": 4,
    "food_rating": 5,
    "comment": "Excellent service!"
}
```

### View Rating (Shop Owner)
```http
GET /api/shop/orders/{order_id}/rating/
Authorization: Bearer {access_token}
```

---

## 🔔 Notifications

### List Notifications
```http
GET /api/notifications/
Authorization: Bearer {any_token}

Query Parameters:
- is_read: true|false
```

### Mark as Read
```http
POST /api/notifications/{notification_id}/read/
Authorization: Bearer {any_token}
```

### Mark All as Read
```http
POST /api/notifications/read-all/
Authorization: Bearer {any_token}
```

---

## 🖼️ Gallery (Shop Images)

### List Images
```http
GET /api/shop/gallery/
Authorization: Bearer {access_token}

Query Parameters:
- status: draft|published
- sort_by: uploaded_at|-uploaded_at|likes_count
- page: 1
- page_size: 12
```

### Upload Image
```http
POST /api/shop/gallery/
Authorization: Bearer {access_token}
Content-Type: multipart/form-data

image: (file)
description: "Image description"
status: "published"
```

### Like Image
```http
POST /api/shop/gallery/{image_id}/like/
Authorization: Bearer {access_token}
Content-Type: application/json

{
    "user_identifier": "966501234567"
}
```

---

## 📄 Invoices

### List Invoices
```http
GET /api/shop/invoices/
Authorization: Bearer {access_token}
```

### Create Quick Invoice
```http
POST /api/shop/invoices/
Authorization: Bearer {access_token}
Content-Type: application/json

{
    "customer_name": "Customer Name",
    "phone_number": "01012345678",
    "address": "123 Street",
    "items": [
        {"name": "Item 1", "quantity": 2, "price": 25.00},
        {"name": "Item 2", "quantity": 1, "price": 15.00}
    ]
}
```

---

## 📁 Related Files

- `shop/views.py` - All view functions
- `shop/serializers.py` - Data serialization
- `shop/urls.py` - URL routing
- `user/urls.py` - Auth URL routing
