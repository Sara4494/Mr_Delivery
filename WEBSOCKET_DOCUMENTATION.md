# WebSocket API Documentation

## نظرة عامة

تم إضافة دعم WebSocket للشات باستخدام Django Channels. يتيح WebSocket اتصالاً ثنائي الاتجاه في الوقت الفعلي للمحادثات.

## المتطلبات

1. تثبيت المكتبات المطلوبة:
```bash
pip install channels channels-redis daphne redis
```

2. تشغيل Redis Server:
```bash
# Windows (باستخدام Chocolatey)
choco install redis-64

# أو استخدام Docker
docker run -p 6379:6379 redis:latest
```

3. تشغيل الخادم باستخدام Daphne بدلاً من runserver:
```bash
daphne -b 0.0.0.0 -p 8000 mr_delivery.asgi:application
```

## WebSocket Endpoints

### 1. Chat WebSocket
**URL:** `ws://localhost:8000/ws/chat/order/{order_id}/?token={access_token}`

**الوصف:** اتصال WebSocket لمحادثة طلب معين

**المعاملات:**
- `order_id` (path parameter): معرف الطلب
- `token` (query parameter): JWT Access Token

**مثال الاتصال:**
```javascript
const ws = new WebSocket('ws://localhost:8000/ws/chat/order/1/?token=your_access_token');
```

### 2. Orders WebSocket
**URL:** `ws://localhost:8000/ws/orders/shop/{shop_owner_id}/?token={access_token}`

**الوصف:** اتصال WebSocket لتحديثات الطلبات للمحل

**المعاملات:**
- `shop_owner_id` (path parameter): معرف صاحب المحل
- `token` (query parameter): JWT Access Token

**مثال الاتصال:**
```javascript
const ws = new WebSocket('ws://localhost:8000/ws/orders/shop/1/?token=your_access_token');
```

## رسائل WebSocket

### رسائل الإرسال (من العميل إلى الخادم)

#### 1. إرسال رسالة نصية
```json
{
  "type": "chat_message",
  "content": "مرحباً، متى يصل الطلب؟",
  "message_type": "text"
}
```

#### 2. إرسال رسالة صوتية
```json
{
  "type": "chat_message",
  "content": "رسالة صوتية",
  "message_type": "audio",
  "audio_file": "base64_encoded_audio_or_url"
}
```

#### 3. إرسال رسالة مع صورة
```json
{
  "type": "chat_message",
  "content": "هذه صورة المنتج",
  "message_type": "image",
  "image_file": "base64_encoded_image_or_url"
}
```

#### 4. تعليم الرسائل كمقروءة
```json
{
  "type": "mark_read"
}
```

#### 5. مؤشر الكتابة
```json
{
  "type": "typing",
  "is_typing": true
}
```

### رسائل الاستقبال (من الخادم إلى العميل)

#### 1. رسالة اتصال ناجح
```json
{
  "type": "connection",
  "message": "تم الاتصال بنجاح",
  "order_id": 1
}
```

#### 2. رسالة شات جديدة
```json
{
  "type": "chat_message",
  "data": {
    "id": 1,
    "sender_type": "shop",
    "sender_type_display": "المحل",
    "message_type": "text",
    "message_type_display": "نص",
    "content": "مرحباً، متى يصل الطلب؟",
    "audio_file": null,
    "audio_file_url": null,
    "image_file": null,
    "image_file_url": null,
    "is_read": false,
    "created_at": "2026-01-28T12:00:00Z"
  }
}
```

#### 3. تأكيد قراءة الرسائل
```json
{
  "type": "messages_read",
  "order_id": 1
}
```

#### 4. مؤشر الكتابة
```json
{
  "type": "typing",
  "user_type": "shop",
  "is_typing": true
}
```

#### 5. تحديث الطلب
```json
{
  "type": "order_update",
  "data": {
    "id": 1,
    "order_number": "010271539171234",
    "status": "on_way",
    ...
  }
}
```

#### 6. طلب جديد
```json
{
  "type": "new_order",
  "data": {
    "id": 2,
    "order_number": "010271539175678",
    ...
  }
}
```

#### 7. رسالة خطأ
```json
{
  "type": "error",
  "message": "محتوى الرسالة مطلوب"
}
```

## مثال كود JavaScript

```javascript
// الاتصال بالـ WebSocket
const orderId = 1;
const accessToken = 'your_access_token';
const ws = new WebSocket(`ws://localhost:8000/ws/chat/order/${orderId}/?token=${accessToken}`);

// عند الاتصال
ws.onopen = function(event) {
    console.log('تم الاتصال بنجاح');
};

// عند استقبال رسالة
ws.onmessage = function(event) {
    const data = JSON.parse(event.data);
    
    switch(data.type) {
        case 'connection':
            console.log('اتصال ناجح:', data.message);
            break;
        case 'chat_message':
            console.log('رسالة جديدة:', data.data);
            // عرض الرسالة في الواجهة
            displayMessage(data.data);
            break;
        case 'messages_read':
            console.log('تم تعليم الرسائل كمقروءة');
            break;
        case 'typing':
            console.log('المستخدم يكتب:', data.is_typing);
            showTypingIndicator(data.user_type, data.is_typing);
            break;
        case 'error':
            console.error('خطأ:', data.message);
            break;
    }
};

// عند إغلاق الاتصال
ws.onclose = function(event) {
    console.log('تم إغلاق الاتصال');
};

// عند حدوث خطأ
ws.onerror = function(error) {
    console.error('خطأ في WebSocket:', error);
};

// إرسال رسالة نصية
function sendMessage(content) {
    ws.send(JSON.stringify({
        type: 'chat_message',
        content: content,
        message_type: 'text'
    }));
}

// تعليم الرسائل كمقروءة
function markAsRead() {
    ws.send(JSON.stringify({
        type: 'mark_read'
    }));
}

// إرسال مؤشر الكتابة
function sendTyping(isTyping) {
    ws.send(JSON.stringify({
        type: 'typing',
        is_typing: isTyping
    }));
}
```

## مثال كود Python (Client)

```python
import asyncio
import websockets
import json

async def chat_client():
    order_id = 1
    token = "your_access_token"
    uri = f"ws://localhost:8000/ws/chat/order/{order_id}/?token={token}"
    
    async with websockets.connect(uri) as websocket:
        # استقبال رسالة الترحيب
        welcome = await websocket.recv()
        print(f"Received: {welcome}")
        
        # إرسال رسالة
        message = {
            "type": "chat_message",
            "content": "مرحباً، متى يصل الطلب؟",
            "message_type": "text"
        }
        await websocket.send(json.dumps(message))
        
        # استقبال الرد
        response = await websocket.recv()
        print(f"Received: {response}")

asyncio.run(chat_client())
```

## الأمان

- جميع اتصالات WebSocket تتطلب JWT Token في query parameter
- يتم التحقق من صحة التوكن قبل قبول الاتصال
- يتم التحقق من أن الطلب يخص صاحب المحل المتصل
- في حالة فشل التحقق، يتم إغلاق الاتصال تلقائياً

## ملاحظات

1. **Redis مطلوب:** يجب تشغيل Redis Server للـ Channel Layers
2. **Daphne:** يجب استخدام Daphne بدلاً من runserver لتشغيل WebSocket
3. **التوكن:** يجب استخدام Access Token وليس Refresh Token
4. **الرسائل:** الرسائل يتم حفظها تلقائياً في قاعدة البيانات
5. **المجموعات:** كل طلب له مجموعة WebSocket منفصلة

## استكشاف الأخطاء

### خطأ: "Connection refused"
- تأكد من تشغيل Redis Server
- تأكد من استخدام Daphne وليس runserver

### خطأ: "Authentication failed"
- تأكد من صحة التوكن
- تأكد من أن التوكن لم ينتهِ صلاحيته

### خطأ: "Order not found"
- تأكد من أن معرف الطلب صحيح
- تأكد من أن الطلب يخص صاحب المحل المتصل
