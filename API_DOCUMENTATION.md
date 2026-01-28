# توثيق APIs المشروع

## Authentication APIs (user app)

### 1. تسجيل الدخول
**Endpoint:** `POST /api/shop/login/`

**Request Body:**
```json
{
    "shop_number": "12345",
    "password": "password123"
}
```

**Response:**
```json
{
    "success": true,
    "message": "تم تسجيل الدخول بنجاح",
    "data": {
        "access": "eyJ0eXAiOiJKV1QiLCJhbGc...",
        "refresh": "eyJ0eXAiOiJKV1QiLCJhbGc...",
        "shop_owner": {
            "id": 1,
            "owner_name": "سارة أحمد",
            "shop_name": "مصور فوتوغرافي",
            "shop_number": "12345"
        }
    }
}
```

### 2. تحديث Token
**Endpoint:** `POST /api/shop/token/refresh/`

**Request Body:**
```json
{
    "refresh": "eyJ0eXAiOiJKV1QiLCJhbGc..."
}
```

**Response:**
```json
{
    "access": "eyJ0eXAiOiJKV1QiLCJhbGc..."
}
```

---

## استخدام Token في Header

**جميع APIs في gallery تتطلب Token في Header:**

```
Authorization: Bearer {access_token}
```

**مثال:**
```
Authorization: Bearer eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9...
```

---

## Shop Profile APIs (gallery app)

### 1. عرض الملف الشخصي
**Endpoint:** `GET /api/shop/profile/`

**Headers:**
```
Authorization: Bearer {access_token}
```

**Response:**
```json
{
    "success": true,
    "data": {
        "id": 1,
        "owner_name": "سارة أحمد",
        "shop_name": "مصور فوتوغرافي",
        "shop_number": "12345",
        "work_schedule": {
            "work_days": "الأحد - الخميس",
            "work_hours": "9:00 صباحاً - 5:00 مساءً"
        },
        "total_images": 248,
        "published_images": 200,
        "total_likes": 12400,
        ...
    }
}
```

### 2. تحديث الملف الشخصي
**Endpoint:** `PUT /api/shop/profile/`

**Headers:**
```
Authorization: Bearer {access_token}
Content-Type: application/json
```

**Request Body:**
```json
{
    "owner_name": "سارة أحمد المالكي",
    "shop_name": "مصور فوتوغرافي محترف"
}
```

**ملاحظة:** هذا API لتحديث البيانات فقط (الاسم واسم المحل). لتحديث صورة البروفيل، استخدم API منفصل أدناه.

### 3. تحديث صورة البروفيل
**Endpoint:** `PUT /api/shop/profile/image/`

**Headers:**
```
Authorization: Bearer {access_token}
```

**Request (multipart/form-data):**
```
profile_image: [file]
```

**Response:**
```json
{
    "status": 200,
    "message": "تم تحديث صورة البروفيل بنجاح",
    "data": {
        "id": 1,
        "owner_name": "سارة أحمد",
        "shop_name": "مصور فوتوغرافي",
        "profile_image": "/media/shop_profiles/image.jpg",
        "profile_image_url": "http://localhost:8000/media/shop_profiles/image.jpg",
        ...
    }
}
```

---

## Work Schedule APIs (gallery app)

### 1. عرض مواعيد العمل
**Endpoint:** `GET /api/shop/schedule/`

**Headers:**
```
Authorization: Bearer {access_token}
```

**Response:**
```json
{
    "success": true,
    "data": {
        "id": 1,
        "work_days": "الأحد - الخميس",
        "work_hours": "9:00 صباحاً - 5:00 مساءً",
        "created_at": "2026-01-27T10:00:00Z",
        "updated_at": "2026-01-27T10:00:00Z"
    }
}
```

### 2. تحديث مواعيد العمل
**Endpoint:** `PUT /api/shop/schedule/`

**Headers:**
```
Authorization: Bearer {access_token}
Content-Type: application/json
```

**Request Body:**
```json
{
    "work_days": "السبت - الأربعاء",
    "work_hours": "10:00 صباحاً - 6:00 مساءً"
}
```

---

## Gallery APIs (gallery app)

### 1. عرض قائمة الصور
**Endpoint:** `GET /api/shop/gallery/`

**Headers:**
```
Authorization: Bearer {access_token}
```

**Query Parameters:**
- `status` (optional): `draft` أو `published`
- `search` (optional): البحث في وصف الصور
- `sort_by` (optional): `uploaded_at`, `likes_count`, `updated_at` (مع `-` للترتيب العكسي)
- `page` (optional): رقم الصفحة
- `page_size` (optional): عدد العناصر في الصفحة (افتراضي: 12)

**Response:**
```json
{
    "success": true,
    "count": 248,
    "next": "http://localhost:8000/api/shop/gallery/?page=2",
    "previous": null,
    "data": [
        {
            "id": 1,
            "image": "/media/gallery_images/image1.jpg",
            "image_url": "http://localhost:8000/media/gallery_images/image1.jpg",
            "description": "وصف الصورة",
            "status": "published",
            "uploaded_at": "2026-01-27T10:00:00Z",
            "updated_at": "2026-01-27T10:00:00Z",
            "likes_count": 150,
            "is_liked": false
        },
        ...
    ]
}
```

### 2. إضافة صورة جديدة
**Endpoint:** `POST /api/shop/gallery/`

**Headers:**
```
Authorization: Bearer {access_token}
```

**Request (multipart/form-data):**
```
image: [file]
description: وصف الصورة (اختياري)
status: draft أو published (افتراضي: draft)
```

**Response:**
```json
{
    "success": true,
    "message": "تم رفع الصورة بنجاح",
    "data": {
        "id": 1,
        "image_url": "...",
        "description": "وصف الصورة",
        "status": "draft",
        ...
    }
}
```

### 3. عرض صورة محددة
**Endpoint:** `GET /api/shop/gallery/{image_id}/`

**Headers:**
```
Authorization: Bearer {access_token}
```

### 4. تحديث صورة
**Endpoint:** `PUT /api/shop/gallery/{image_id}/`

**Headers:**
```
Authorization: Bearer {access_token}
Content-Type: application/json
```

**Request Body:**
```json
{
    "description": "وصف جديد",
    "status": "published"
}
```

### 5. حذف صورة
**Endpoint:** `DELETE /api/shop/gallery/{image_id}/`

**Headers:**
```
Authorization: Bearer {access_token}
```

**Response:**
```json
{
    "success": true,
    "message": "تم حذف الصورة بنجاح"
}
```

### 6. الإعجاب بصورة
**Endpoint:** `POST /api/shop/gallery/{image_id}/like/`

**Headers:**
```
Authorization: Bearer {access_token}
Content-Type: application/json
```

**Request Body:**
```json
{
    "user_identifier": "966501234567"
}
```

**Response:**
```json
{
    "success": true,
    "message": "تم الإعجاب بالصورة",
    "liked": true
}
```

### 7. إلغاء الإعجاب
**Endpoint:** `DELETE /api/shop/gallery/{image_id}/like/`

**Headers:**
```
Authorization: Bearer {access_token}
Content-Type: application/json
```

**Request Body:**
```json
{
    "user_identifier": "966501234567"
}
```

---

## Statistics API (gallery app)

### 1. إحصائيات المحل
**Endpoint:** `GET /api/shop/statistics/`

**Headers:**
```
Authorization: Bearer {access_token}
```

**Response:**
```json
{
    "success": true,
    "data": {
        "total_images": 248,
        "published_images": 200,
        "draft_images": 48,
        "total_likes": 12400
    }
}
```

---

## ملاحظات مهمة

1. **Authentication:** جميع APIs في gallery تتطلب JWT Token في Header:
   - بعد تسجيل الدخول، احصل على `access_token` من response
   - أضف Header: `Authorization: Bearer {access_token}`
   - Token صالح لمدة 24 ساعة
   - استخدم `/api/shop/token/refresh/` لتحديث Token

2. **Pagination:** معرض الصور يدعم pagination تلقائياً. استخدم `page` و `page_size` في query parameters.

3. **Sorting:** يمكنك ترتيب الصور باستخدام `sort_by`:
   - `uploaded_at` (الأحدث أولاً)
   - `-uploaded_at` (الأقدم أولاً)
   - `likes_count` (الأكثر إعجاباً)
   - `-likes_count` (الأقل إعجاباً)

4. **Image Status:**
   - `draft`: مسودة (غير منشورة)
   - `published`: منشورة (ظاهرة في المعرض)

5. **File Upload:** استخدم `multipart/form-data` عند رفع الصور.

6. **Error Responses:** جميع الأخطاء تأتي بهذا الشكل:
```json
{
    "success": false,
    "message": "رسالة الخطأ",
    "errors": {...}
}
```
