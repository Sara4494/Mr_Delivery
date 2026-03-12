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

## 2. Register (Customers Only) — Create Account then OTP

**الخطوات:**
1. إنشاء الحساب: `POST /api/auth/register/`
2. إرسال OTP: `POST /api/auth/otp/send/` مع `"purpose": "register"`
3. تفعيل الحساب: `POST /api/auth/otp/verify/` مع `"purpose": "register"`

**Endpoint**: `POST /api/auth/register/`

### Request Body
```json
{
    "role": "customer",
    "name": "Ahmed Mohamed",
    "phone_number": "01012345678",
    "password": "password123"
}
```

### Success Response (201)
```json
{
    "status": 201,
    "message": "Account created successfully. Complete OTP verification",
    "data": {
        "user": {
            "id": 1,
            "name": "Ahmed Mohamed",
            "phone_number": "01012345678",
            "is_verified": false
        },
        "role": "customer"
    }
}
```

> **Note**: Employees and Drivers are created by Shop Owners only.

---

## 3. OTP Login (WhatsApp via UltraMsg)

تسجيل دخول العملاء برمز OTP يُرسل عبر واتساب (بدون كلمة مرور).

### 3.1 إرسال رمز OTP

**Endpoint**: `POST /api/auth/otp/send/`

**Request Body**
```json
{
    "phone_number": "+201012345678",
    "purpose": "login"
}
```
- `purpose` اختياري: `"login"` | `"register"` | `"reset_password"`
- للتسجيل: الرقم يجب ألا يكون مسجلاً
- لاستعادة كلمة المرور: الرقم يجب أن يكون مسجلاً

**Success Response (200)**
```json
{
    "status": 200,
    "message": "تم إرسال رمز التحقق إلى واتساب الخاص بك",
    "data": {}
}
```

**Error Response (400)**
```json
{
    "status": 400,
    "message": "يرجى الانتظار دقيقة قبل إعادة إرسال الرمز"
}
```

### 3.2 التحقق من OTP وتسجيل الدخول

**Endpoint**: `POST /api/auth/otp/verify/`

**Request Body**
```json
{
    "phone_number": "+201012345678",
    "otp": "123456"
}
```

**Success Response (200)** — نفس شكل استجابة Login
```json
{
    "status": 200,
    "message": "تم تسجيل الدخول بنجاح",
    "data": {
        "refresh": "eyJ...",
        "access": "eyJ...",
        "user": { "id": 1, "name": "...", "phone_number": "..." },
        "role": "customer"
    }
}
```

**Error Response (404)** — رقم غير مسجل
```json
{
    "status": 404,
    "message": "رقم الهاتف غير مسجل. يرجى التسجيل أولاً"
}
```

### متغيرات البيئة (UltraMsg)
```
ULTRAMSG_INSTANCE=instance160549
ULTRAMSG_TOKEN=your_token
```

---

## 4. استعادة كلمة المرور (Reset Password) — لجميع المستخدمين

**الخطوات:**
1. إرسال OTP: `POST /api/auth/otp/send/` مع `purpose=reset_password` و `role`
2. تغيير كلمة المرور: `POST /api/auth/password-reset/`

### إرسال OTP للاستعادة
```json
{
    "phone_number": "+201012345678",
    "purpose": "reset_password",
    "role": "customer"
}
```
- **customer**: `phone_number` فقط
- **shop_owner**: `phone_number` فقط (يجب إضافته في إعدادات المحل أولاً)
- **employee**: `phone_number` فقط يكفي في الوضع الطبيعي، و`shop_number` اختياري إذا كان نفس الرقم مرتبطًا بأكثر من محل
- **driver**: مطلوب `phone_number` + `shop_number`

### تغيير كلمة المرور
**Endpoint**: `POST /api/auth/password-reset/`

**Request Body**
```json
{
    "role": "customer",
    "phone_number": "+201012345678",
    "shop_number": "12345",
    "otp": "123456",
    "new_password": "newpassword123"
}
```
- `shop_number` اختياري للـ employee عند الحاجة لتحديد الحساب، ومطلوب فقط للـ driver

**Success Response (200)**
```json
{
    "status": 200,
    "message": "تم تغيير كلمة المرور بنجاح",
    "data": {}
}
```

---

## 5. Token Refresh

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
- `user/views.py` - Auth Views (unified_login_view, unified_register_view, OTP views)
- `user/otp_service.py` - OTP service (UltraMsg WhatsApp)
- `user/token_serializers.py` - Token Serializers
- `shop/middleware.py` - WebSocket JWT Middleware
