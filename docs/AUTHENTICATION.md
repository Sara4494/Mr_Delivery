# 🔐 Authentication System

Mr Delivery uses **JWT (JSON Web Tokens)** for authentication across all user types.

---

## 📍 Unified Auth Endpoints

### Base URL
```
/api/auth/
```

---

## 1. Login (All Users)

**Endpoint**: `POST /api/auth/login/`

### Request Body by Role:

#### Shop Owner
```json
{
    "role": "shop_owner",
    "shop_number": "12345",
    "password": "your_password"
}
```

#### Customer
```json
{
    "role": "customer",
    "phone_number": "01012345678",
    "password": "your_password"
}
```

#### Employee
```json
{
    "role": "employee",
    "phone_number": "01000000000",
    "password": "your_password"
}
```

#### Driver
```json
{
    "role": "driver",
    "phone_number": "01000000001",
    "password": "your_password"
}
```

### Success Response (200)
```json
{
    "status": 200,
    "message": "Login successful",
    "data": {
        "refresh": "eyJhbGciOiJIUzI1NiIs...",
        "access": "eyJhbGciOiJIUzI1NiIs...",
        "user": {
            "id": 1,
            "name": "User Name",
            "phone_number": "01012345678"
        },
        "role": "customer"
    }
}
```

### Error Response (401)
```json
{
    "status": 401,
    "message": "Invalid phone number or password",
    "success": false
}
```

---

## 2. Register (Customers Only)

**Endpoint**: `POST /api/auth/register/`

### Request Body
```json
{
    "role": "customer",
    "name": "Ahmed Mohamed",
    "phone_number": "01012345678",
    "email": "ahmed@example.com",
    "password": "password123"
}
```

### Success Response (201)
```json
{
    "status": 201,
    "message": "Account created successfully",
    "data": {
        "refresh": "eyJhbGciOiJIUzI1NiIs...",
        "access": "eyJhbGciOiJIUzI1NiIs...",
        "user": {
            "id": 1,
            "name": "Ahmed Mohamed",
            "phone_number": "01012345678",
            "email": "ahmed@example.com",
            "is_verified": false
        },
        "role": "customer"
    }
}
```

> **Note**: Employees and Drivers are created by Shop Owners only.

---

## 3. Token Refresh

**Endpoint**: `POST /api/shop/token/refresh/`

### Request Body
```json
{
    "refresh": "eyJhbGciOiJIUzI1NiIs..."
}
```

### Response
```json
{
    "status": 200,
    "message": "Token refreshed successfully",
    "data": {
        "access": "eyJhbGciOiJIUzI1NiIs..."
    }
}
```

---

## 🔑 Using JWT Tokens

### In HTTP Headers
```
Authorization: Bearer <access_token>
```

### In WebSocket Connection
```
ws://server/ws/chat/order/1/?token=<access_token>&chat_type=shop_customer
```

---

## ⏱️ Token Expiration

| Token Type | Default Expiration |
|------------|-------------------|
| Access Token | 24 hours |
| Refresh Token | 7 days |

> Configure in `settings.py` under `SIMPLE_JWT`

---

## 🔐 JWT Token Payload

### Shop Owner Token
```json
{
    "token_type": "access",
    "exp": 1769953369,
    "shop_owner_id": 1,
    "shop_number": "12345",
    "user_type": "shop_owner"
}
```

### Customer Token
```json
{
    "token_type": "access",
    "exp": 1769953369,
    "customer_id": 1,
    "phone_number": "01012345678",
    "user_type": "customer"
}
```

### Employee Token
```json
{
    "token_type": "access",
    "exp": 1769953369,
    "employee_id": 1,
    "phone_number": "01000000000",
    "user_type": "employee",
    "shop_owner_id": 1,
    "role": "cashier"
}
```

### Driver Token
```json
{
    "token_type": "access",
    "exp": 1769953369,
    "driver_id": 1,
    "phone_number": "01000000001",
    "user_type": "driver",
    "shop_owner_id": 1
}
```

---

## 📁 Related Files

- `user/authentication.py` - Custom JWT Authentication
- `user/views.py` - Auth Views (unified_login_view, unified_register_view)
- `user/token_serializers.py` - Token Serializers
- `shop/middleware.py` - WebSocket JWT Middleware
