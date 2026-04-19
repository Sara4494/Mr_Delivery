# Shop Support Center WebSocket

هذا الملف خاص بفرونت `المحل` فقط في مركز الدعم.

## الهدف

تشغيل تذاكر الدعم والمحادثة اللحظية بين المحل والشركة عبر WebSocket.

المحل يقدر:

- يفتح تذكرة جديدة
- يجلب snapshot كامل للتذاكر والإحصائيات
- يشترك في thread تذكرة معينة
- يرسل رسائل `text`, `image`, `audio`, `location`
- يرسل `typing`
- يرسل `mark read`

المحل لا يقدر:

- يغير حالة التذكرة
- يعين التذكرة لنفسه

## المصادقة

الاتصال يتم بـ JWT في query string:

```text
ws://HOST/ws/support-center/shop/{shop_owner_id}/?token={SHOP_OR_EMPLOYEE_ACCESS_TOKEN}&lang=ar
```

## من يقدر يدخل

- `shop_owner` لنفس `shop_owner_id`
- `employee` بشرط أن `employee.shop_owner_id == shop_owner_id`

## رسائل السيرفر عند الاتصال

عند نجاح الاتصال السيرفر يرسل رسالتين:

### 1) `support.connection`

```json
{
  "type": "support.connection",
  "data": {
    "actor_type": "shop_owner",
    "shop_owner_id": 12,
    "chat_type": "shop_admin_support"
  },
  "sent_at": "2026-04-18T21:40:00Z"
}
```

### 2) `support.snapshot`

```json
{
  "type": "support.snapshot",
  "data": {
    "actor_type": "shop_owner",
    "scope": "shop",
    "stats": {
      "total": 4,
      "open": 1,
      "in_progress": 1,
      "waiting_shop": 0,
      "waiting_support": 1,
      "resolved": 1,
      "closed": 0,
      "resolved_today": 1
    },
    "tickets": [
      {
        "ticket_id": "ticket_14",
        "subject": "POS app crashes when confirming order",
        "priority": "high",
        "priority_display": "عالية",
        "status": "waiting_support",
        "status_display": "بانتظار الدعم",
        "shop": {
          "id": 12,
          "shop_name": "ZAYGO Store",
          "shop_number": "SHOP-001",
          "owner_name": "Ahmed",
          "profile_image_url": "https://..."
        },
        "created_by": {
          "type": "employee",
          "id": 8,
          "name": "Cashier 1"
        },
        "assigned_admin": {
          "id": 3,
          "name": "Support Agent",
          "role": "technical_support",
          "role_display": "الدعم الفني",
          "profile_image_url": "https://..."
        },
        "unread_for_shop_count": 0,
        "unread_for_admin_count": 1,
        "last_message_preview": "التطبيق بيقفل عند الضغط على تأكيد الطلب.",
        "last_message_at": "2026-04-18T21:41:00Z",
        "resolved_at": null,
        "closed_at": null,
        "created_at": "2026-04-18T21:41:00Z",
        "updated_at": "2026-04-18T21:41:00Z",
        "chat": {
          "thread_id": "ticket_14",
          "ticket_id": "ticket_14",
          "chat_type": "shop_admin_support"
        }
      }
    ]
  },
  "sent_at": "2026-04-18T21:40:00Z"
}
```

## الأكشنات التي يرسلها فرونت المحل

كل الأكشنات ترسل بهذا الشكل العام:

```json
{
  "action": "support.some_action",
  "request_id": "req-123"
}
```

## 1) مزامنة كاملة

```json
{
  "action": "support.sync",
  "request_id": "sync-1"
}
```

## 2) إنشاء تذكرة جديدة

```json
{
  "action": "support.ticket.create",
  "request_id": "create-1",
  "subject": "الطابعة لا تتزامن مع الكاشير",
  "priority": "medium",
  "initial_message": "الطابعة لا تطبع الطلبات الجديدة منذ 10 دقائق"
}
```

القيم المتاحة لـ `priority`:

- `low`
- `medium`
- `high`
- `urgent`

## 3) الاشتراك في Thread تذكرة

```json
{
  "action": "support.ticket.subscribe",
  "request_id": "sub-1",
  "ticket_id": "ticket_14"
}
```

السيرفر يعيد:

```json
{
  "type": "support.ticket.thread",
  "data": {
    "ticket": {
      "ticket_id": "ticket_14",
      "subject": "POS app crashes when confirming order",
      "priority": "high",
      "status": "in_progress"
    },
    "messages": [
      {
        "id": 51,
        "ticket_id": "ticket_14",
        "thread_id": "ticket_14",
        "sender_type": "shop_owner",
        "sender_type_display": "صاحب المحل",
        "sender_name": "Ahmed",
        "sender_id": 12,
        "message_type": "text",
        "message_type_display": "نصي",
        "content": "التطبيق بيقفل عند الضغط على تأكيد الطلب.",
        "image_url": null,
        "audio_url": null,
        "latitude": null,
        "longitude": null,
        "metadata": {},
        "is_read": false,
        "created_at": "2026-04-18T21:41:00Z"
      }
    ]
  },
  "sent_at": "2026-04-18T21:42:30Z"
}
```

## 4) إرسال رسالة داخل التذكرة

### نص

```json
{
  "action": "support.ticket.send_message",
  "request_id": "msg-text-1",
  "ticket_id": "ticket_14",
  "message_type": "text",
  "content": "من فضلكم راجعوا المشكلة"
}
```

### صورة

```json
{
  "action": "support.ticket.send_message",
  "request_id": "msg-image-1",
  "ticket_id": "ticket_14",
  "message_type": "image",
  "content": "لقطة شاشة من الخطأ",
  "image_url": "https://cdn.example.com/support/error-1.jpg"
}
```

### صوت

```json
{
  "action": "support.ticket.send_message",
  "request_id": "msg-audio-1",
  "ticket_id": "ticket_14",
  "message_type": "audio",
  "content": "شرح صوتي",
  "audio_url": "https://cdn.example.com/support/error-1.m4a"
}
```

### موقع

```json
{
  "action": "support.ticket.send_message",
  "request_id": "msg-loc-1",
  "ticket_id": "ticket_14",
  "message_type": "location",
  "content": "موقع الفرع",
  "latitude": 30.0444,
  "longitude": 31.2357
}
```

الأنواع المدعومة:

- `text`
- `image`
- `audio`
- `location`

مهم:

- في `image` و `audio` السيرفر الحالي يستقبل `image_url` و `audio_url`
- يعني الفرونت يرفع الملف أولًا على أي storage/CDN داخلي عندكم ثم يرسل الرابط داخل الـ WebSocket
- يوجد REST upload مباشر لتذاكر الدعم إذا كان العميل يحتاج multipart بدل رفع URL مسبقًا:
  `POST /api/chat/ticket/{ticket_id}/send-media/`
- الـ REST upload يقبل أيضًا الصيغة الحالية من بعض العملاء:
  `file` + `media_type=image|audio`
- كما يقبل الصيغة القياسية:
  `image_file` أو `audio_file` + `message_type=image|audio`

## 5) typing indicator

```json
{
  "action": "support.ticket.typing",
  "request_id": "typing-1",
  "ticket_id": "ticket_14",
  "is_typing": true
}
```

## 6) mark read

```json
{
  "action": "support.ticket.mark_read",
  "request_id": "read-1",
  "ticket_id": "ticket_14"
}
```

## الأحداث التي يستقبلها فرونت المحل

## `support.ticket.created`

```json
{
  "type": "support.ticket.created",
  "data": {
    "ticket": {
      "ticket_id": "ticket_14",
      "subject": "POS app crashes when confirming order",
      "priority": "high",
      "status": "waiting_support"
    }
  },
  "sent_at": "2026-04-18T21:41:00Z"
}
```

## `support.ticket.updated`

ترسل عند:

- رسالة جديدة
- `mark read`
- تغيير حالة من الأدمن
- `assign to me` من الأدمن

```json
{
  "type": "support.ticket.updated",
  "data": {
    "ticket": {
      "ticket_id": "ticket_14",
      "status": "in_progress",
      "unread_for_shop_count": 1,
      "unread_for_admin_count": 0,
      "assigned_admin": {
        "id": 3,
        "name": "Support Agent"
      }
    }
  },
  "sent_at": "2026-04-18T21:45:00Z"
}
```

## `support.ticket.message_created`

```json
{
  "type": "support.ticket.message_created",
  "data": {
    "ticket_id": "ticket_14",
    "message": {
      "id": 52,
      "ticket_id": "ticket_14",
      "thread_id": "ticket_14",
      "sender_type": "admin_desktop",
      "sender_name": "Support Agent",
      "sender_id": 3,
      "message_type": "text",
      "content": "تم استلام البلاغ وجاري الفحص الآن.",
      "image_url": null,
      "audio_url": null,
      "latitude": null,
      "longitude": null,
      "metadata": {},
      "is_read": false,
      "created_at": "2026-04-18T21:45:00Z"
    }
  },
  "sent_at": "2026-04-18T21:45:00Z"
}
```

## `support.ticket.thread`

يرجع عند `subscribe` أو بعد إنشاء التذكرة من نفس socket.

## `support.ticket.typing`

```json
{
  "type": "support.ticket.typing",
  "data": {
    "ticket_id": "ticket_14",
    "actor_type": "admin_desktop",
    "actor_name": "Support Agent",
    "is_typing": true
  },
  "sent_at": "2026-04-18T21:46:00Z"
}
```

## `support.ack`

```json
{
  "type": "support.ack",
  "request_id": "msg-1",
  "action": "support.ticket.send_message",
  "success": true,
  "data": {
    "ticket_id": "ticket_14",
    "message_id": 52
  },
  "sent_at": "2026-04-18T21:45:00Z"
}
```

## `support.error`

```json
{
  "type": "support.error",
  "request_id": "msg-1",
  "success": false,
  "data": {
    "code": "TICKET_NOT_FOUND",
    "message": "التذكرة غير موجودة"
  },
  "sent_at": "2026-04-18T21:45:10Z"
}
```

## أكواد الأخطاء المتوقعة

- `INVALID_JSON`
- `INVALID_ACTION`
- `SUBJECT_REQUIRED`
- `INVALID_PRIORITY`
- `TICKET_NOT_FOUND`
- `TICKET_ACCESS_DENIED`
- `INVALID_MESSAGE_TYPE`
- `CONTENT_REQUIRED`
- `IMAGE_URL_REQUIRED`
- `AUDIO_URL_REQUIRED`
- `LOCATION_REQUIRED`
- `INVALID_DATA`
- `UNEXPECTED_ERROR`

## منطق مهم لفرونت المحل

### فتح الشاشة

1. افتح الـ socket.
2. انتظر `support.connection`.
3. خزّن `support.snapshot` كـ source of truth.

### شاشة القائمة

- اعرض `data.tickets` من `support.snapshot`
- عند وصول `support.ticket.created` أضف أو حدّث التذكرة
- عند وصول `support.ticket.updated` اعمل upsert للتذكرة

### شاشة المحادثة

1. عند اختيار تذكرة ارسل `support.ticket.subscribe`
2. استخدم `support.ticket.thread.messages` لعرض الرسائل
3. عند وصول `support.ticket.message_created`:
   إذا كانت `ticket_id` هي المفتوحة حاليًا أضف الرسالة للشات
4. بعد فتح التذكرة ارسل `support.ticket.mark_read`

### إعادة الاتصال

- عند انقطاع الـ socket أعد الاتصال
- بعد reconnect ارسل `support.sync`
- لا تعتمد على state قديم بدون resync
