# Shop Frontend Support Chat Guide

هذا الدكمنت مخصص لفرونت المحل.

الهدف:

- دعم `الاستفسار` و`الشكوى` داخل نفس شاشة الشات المستخدمة للأوردر
- بدون فتح WebSocket جديد مختلف في شكل الاستخدام
- مع إعادة استخدام نفس socket builder ونفس media upload pattern قدر الإمكان

## الفكرة العامة

عندنا الآن نوعان أساسيان من شات المحل مع العميل:

1. شات أوردر عادي
2. شات دعم بدون أوردر

شات الدعم يشمل:

- `inquiry` = استفسار
- `complaint` = شكوى

بالنسبة للفرونت:

- شات الأوردر يظل كما هو
- شات الدعم يفتح من نفس مسار شات الأوردر
- الفرق فقط في `chat_type` والـ `thread_id`

## كيف يميز الفرونت بين النوعين

### Order thread

```json
{
  "chat": {
    "thread_id": "15",
    "order_id": 15,
    "chat_type": "shop_customer",
    "shop_id": 8
  }
}
```

### Support thread

```json
{
  "chat": {
    "thread_id": "support_12",
    "support_conversation_id": "support_12",
    "chat_type": "support_customer",
    "conversation_type": "complaint",
    "shop_id": 8
  }
}
```

الخلاصة:

- لو `chat_type == "shop_customer"` يبقى هذا شات أوردر
- لو `chat_type == "support_customer"` يبقى هذا شات استفسار/شكوى

## Dashboard socket الخاص بالمحل

المحل بالفعل متصل على:

```text
/ws/orders/shop/{shop_owner_id}/?token=<JWT>
```

ومن نفس القناة سيصل للفرونت أيضًا:

- `support_conversation_update`
- `support_message`

Ù…Ù‡Ù…:

- Ø¹Ù†Ø¯ reopen Ø£Ùˆ reconnect Ù„Ø³ÙˆÙƒØª Ø§Ù„Ù…Ø­Ù„ØŒ Ø§Ù„Ø¨Ø§Ùƒ Ø¥Ù†Ø¯ Ø³ÙŠØ¹ÙŠØ¯ Ø¨Ø« Ø¬Ù…ÙŠØ¹ Ù…Ø­Ø§Ø¯Ø«Ø§Øª Ø§Ù„Ø¯Ø¹Ù… Ø§Ù„Ù…ÙˆØ¬ÙˆØ¯Ø© ÙƒØ£Ø­Ø¯Ø§Ø« `support_conversation_update`
- Ù„Ø°Ù„Ùƒ Ø§Ù„ÙØ±ÙˆÙ†Øª ÙŠØªØ¹Ø§Ù…Ù„ Ù…Ø¹ `support_conversation_update` ÙƒÙ€ upsert Ø¯Ø§Ø¦Ù…Ù‹Ø§ØŒ Ø³ÙˆØ§Ø¡ Ø¬Ø§Ø¡Øª live Ø£Ùˆ Ø¬Ø§Ø¡Øª Ø¨Ø¹Ø¯ reconnect

## event: `support_conversation_update`

يصل عند:

- إنشاء استفسار/شكوى جديدة
- تحديث حالة المحادثة
- تحديث آخر رسالة / unread counters

مثال payload:

```json
{
  "type": "support_conversation_update",
  "data": {
    "support_conversation_id": "support_12",
    "conversation_type": "complaint",
    "conversation_type_display": "شكوى",
    "status": "open",
    "status_display": "مفتوحة",
    "shop_id": 8,
    "shop_name": "برجر كنچ",
    "shop_logo_url": "/media/shops/logo.png",
    "customer_id": 7,
    "customer_name": "Ahmed",
    "customer_profile_image_url": "/media/customers/7/profile.jpg",
    "customer": {
      "id": 7,
      "name": "Ahmed",
      "phone_number": "01000000000",
      "profile_image_url": "/media/customers/7/profile.jpg",
      "is_online": true,
      "last_seen": "2026-04-02T20:14:00+02:00"
    },
    "subtitle": "أرسلت رسالة من قبل ولم يصلني رد",
    "last_message_preview": "أرسلت رسالة من قبل ولم يصلني رد",
    "last_message_at": "2026-04-02T20:15:00+02:00",
    "unread_for_customer_count": 0,
    "unread_for_shop_count": 1,
    "created_at": "2026-04-02T20:10:00+02:00",
    "updated_at": "2026-04-02T20:15:00+02:00",
    "chat": {
      "thread_id": "support_12",
      "support_conversation_id": "support_12",
      "chat_type": "support_customer",
      "conversation_type": "complaint",
      "shop_id": 8
    }
  }
}
```

المطلوب من الفرونت:

- اعمل `upsert` للثريد في قائمة المحادثات
- استخدم `customer_name` كاسم العميل
- استخدم `conversation_type_display` كعنوان فرعي أو badge مثل `استفسار` أو `شكوى`

## event: `support_message`

يصل عند وصول رسالة جديدة داخل الاستفسار/الشكوى.

مثال payload:

```json
{
  "type": "support_message",
  "data": {
    "support_conversation_id": "support_12",
    "thread_id": "support_12",
    "chat_type": "support_customer",
    "conversation_type": "complaint",
    "message": {
      "id": 44,
      "thread_id": "support_12",
      "support_conversation_id": "support_12",
      "chat_type": "support_customer",
      "conversation_type": "complaint",
      "conversation_type_display": "شكوى",
      "sender_type": "customer",
      "sender_name": "Ahmed",
      "sender_id": 7,
      "customer_profile_image_url": "/media/customers/7/profile.jpg",
      "message_type": "text",
      "content": "أحتاج متابعة من المتجر",
      "is_read": false,
      "created_at": "2026-04-02T20:15:00+02:00",
      "audio_file_url": null,
      "image_file_url": null,
      "latitude": null,
      "longitude": null
    },
    "conversation": {
      "support_conversation_id": "support_12",
      "conversation_type": "complaint",
      "conversation_type_display": "شكوى",
      "status": "open",
      "status_display": "مفتوحة",
      "shop_id": 8,
      "shop_name": "برجر كنچ",
      "customer_id": 7,
      "customer_name": "Ahmed",
      "customer_profile_image_url": "/media/customers/7/profile.jpg",
      "customer": {
        "id": 7,
        "name": "Ahmed",
        "phone_number": "01000000000",
        "profile_image_url": "/media/customers/7/profile.jpg",
        "is_online": true,
        "last_seen": "2026-04-02T20:14:00+02:00"
      },
      "subtitle": "أحتاج متابعة من المتجر",
      "last_message_preview": "أحتاج متابعة من المتجر",
      "chat": {
        "thread_id": "support_12",
        "support_conversation_id": "support_12",
        "chat_type": "support_customer",
        "conversation_type": "complaint",
        "shop_id": 8
      }
    },
    "shop_id": 8,
    "shop_name": "برجر كنچ",
    "customer_id": 7,
    "customer_name": "Ahmed",
    "customer_profile_image_url": "/media/customers/7/profile.jpg",
    "customer": {
      "id": 7,
      "name": "Ahmed",
      "phone_number": "01000000000",
      "profile_image_url": "/media/customers/7/profile.jpg",
      "is_online": true,
      "last_seen": "2026-04-02T20:14:00+02:00"
    }
  }
}
```

المطلوب من الفرونت:

- حدّث قائمة المحادثات من `data.conversation`
- لو الشات المفتوح حاليًا هو نفس `thread_id` أضف الرسالة فورًا داخل نافذة المحادثة
- لو ليس مفتوحًا، اعرض badge أو unread indicator

## فتح الشات نفسه

الفرونت يجب أن يعيد استخدام نفس شكل socket path:

```text
/ws/chat/order/{thread_id}/?token=<JWT>&chat_type={chat_type}
```

### مثال أوردر

```text
/ws/chat/order/15/?token=JWT&chat_type=shop_customer
```

### مثال استفسار/شكوى

```text
/ws/chat/order/support_12/?token=JWT&chat_type=support_customer
```

مهم:

- لا يوجد `order_id` هنا في حالة الاستفسار/الشكوى
- استخدم `thread_id` مباشرة كما هو

## ماذا يصل من chat socket

عند فتح شات الدعم سيصل:

### connection

```json
{
  "type": "connection",
  "thread_id": "support_12",
  "support_conversation_id": "support_12",
  "chat_type": "support_customer",
  "conversation_type": "complaint",
  "user_type": "shop_owner"
}
```

### previous_messages

```json
{
  "type": "previous_messages",
  "messages": [
    {
      "id": 44,
      "thread_id": "support_12",
      "support_conversation_id": "support_12",
      "chat_type": "support_customer",
      "conversation_type": "complaint",
      "conversation_type_display": "شكوى",
      "sender_type": "customer",
      "sender_name": "Ahmed",
      "sender_id": 7,
      "message_type": "text",
      "content": "أحتاج متابعة من المتجر",
      "is_read": false,
      "created_at": "2026-04-02T20:15:00+02:00",
      "audio_file_url": null,
      "image_file_url": null,
      "latitude": null,
      "longitude": null
    }
  ]
}
```

### chat_message

نفس شكل الرسالة السابقة تقريبًا داخل `data`.

## إرسال رسالة نصية

يتم عبر نفس socket:

```json
{
  "type": "send_message",
  "request_id": "msg-171208",
  "message_type": "text",
  "content": "تم استلام الشكوى وسيتم المتابعة"
}
```

## mark read

نفس السلوك:

```json
{
  "type": "mark_read",
  "request_id": "read-171208"
}
```

## typing

نفس السلوك:

```json
{
  "type": "typing",
  "is_typing": true
}
```

## رفع صورة أو صوت

يعاد استخدام نفس pattern الخاص بالأوردر:

```text
POST /api/chat/order/{thread_id}/send-media/
```

### مثال لشات شكوى / استفسار

```text
POST /api/chat/order/support_12/send-media/
```

form-data:

- `chat_type=support_customer`
- `message_type=image` أو `message_type=audio`
- `image_file` أو `audio_file`
- `content` اختياري

## منطق الفرونت المقترح

### 1. عند وصول `support_conversation_update`

- أضف/حدّث العنصر داخل قائمة محادثات المحل
- خزّن:
  - `thread_id`
  - `chat_type`
  - `customer_name`
  - `conversation_type`
  - `conversation_type_display`
  - `last_message_preview`
  - `unread_for_shop_count`

### 2. عند الضغط على المحادثة

- افتح نفس شاشة الشات الموجودة حاليًا
- لا تستخدم `order_id`
- استخدم:
  - `thread_id`
  - `chat_type`

### 3. عند عرض الهيدر

في شات الدعم اعرض مثلًا:

- الاسم: `customer_name`
- badge: `استفسار` أو `شكوى`

ولا تعتمد على:

- `order_number`
- `invoice`
- `order status`

## Pseudocode بسيط

```js
function openThread(thread) {
  const threadId = thread.chat.thread_id;
  const chatType = thread.chat.chat_type;

  const socket = new WebSocket(
    `${wsBase}/chat/order/${threadId}/?token=${token}&chat_type=${chatType}`
  );
}
```

```js
function mediaUrl(thread) {
  return `/api/chat/order/${thread.chat.thread_id}/send-media/`;
}
```

```js
function isSupportThread(thread) {
  return thread?.chat?.chat_type === 'support_customer';
}
```

## مهم جدًا

إذا كانت الشاشة الحالية في المحل تفترض دائمًا أن أي شات له:

- `order_id`
- `order_number`
- order detail API

فهذا يحتاج تعديل فرونت.

لكن التعديل المطلوب صغير وواضح:

- استخدم `thread_id` بدل `order_id` وقت فتح الشات
- لو `chat_type == support_customer` لا تطلب تفاصيل أوردر
- اعرض بيانات المحادثة نفسها بدل بيانات الأوردر

## مرجع التنفيذ في الباك إند

- `shop/routing.py`
- `shop/urls.py`
- `shop/consumers.py`
- `shop/serializers.py`
- `shop/views.py`
