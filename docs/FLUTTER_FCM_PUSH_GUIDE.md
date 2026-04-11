# Flutter FCM Push Guide

هذا المستند هو handoff لفريق Flutter بخصوص تكامل Push Notifications مع باك إند Mr Delivery.

يعتمد على السلوك الحالي في:

- `shop/fcm_service.py`
- `shop/fcm_views.py`
- `shop/fcm_serializers.py`
- `shop/urls.py`

## 1. الهدف

التطبيق مربوط مع Firebase بالفعل.

المطلوب من تطبيق Flutter:

- إرسال `fcm_token` للباك إند بعد تسجيل الدخول
- تحديث التوكن عند تغيّره
- إلغاء تسجيل الجهاز عند `logout`
- استقبال إشعارات:
  - رسالة جديدة
  - incoming ring
  - broadcast / general notification
- فتح الشاشة الصحيحة عند الضغط على الإشعار

## 2. Base URLs

- REST base: `/api`

أمثلة:

```text
POST   /api/devices/fcm/register
POST   /api/devices/fcm/refresh
DELETE /api/devices/fcm/unregister
```

## 3. Authentication

استخدم نفس JWT access token العادي للتطبيق.

في REST:

```http
Authorization: Bearer <access_token>
```

بديلًا عن الهيدر، الباك إند يقبل أيضًا `access_token` داخل الـ body عند الحاجة.

## 4. متى يرسل Flutter التوكن

يجب على التطبيق استدعاء register أو refresh في الحالات التالية:

1. بعد login مباشرة
2. بعد app launch إذا كان `fcmToken` تغيّر
3. عند `FirebaseMessaging.onTokenRefresh`
4. بعد إعادة تثبيت التطبيق أو حذف بيانات التطبيق

ويجب استدعاء unregister عند:

1. logout

## 5. Register Device

### Endpoint

```http
POST /api/devices/fcm/register
Content-Type: application/json
Authorization: Bearer <access_token>
```

### Request body

```json
{
  "device_id": "17758959909409221380063272",
  "platform": "android",
  "fcm_token": "FCM_TOKEN_FROM_FIREBASE",
  "app_version": "1.0.0"
}
```

### Notes

- `device_id` يجب أن يكون ثابتًا لنفس تثبيت التطبيق
- `platform` حاليًا:
  - `android`
  - `ios`
- نفس المستخدم يمكن أن يملك أكثر من جهاز
- إذا تم إرسال نفس التوكن من مستخدم آخر، الباك إند سيعطل الربط القديم تلقائيًا

### Example response

```json
{
  "status": 200,
  "success": true,
  "message": "FCM device token registered successfully.",
  "data": {
    "id": 6,
    "user_type": "customer",
    "user_id": 6,
    "device_id": "17758959909409221380063272",
    "platform": "android",
    "fcm_token": "FCM_TOKEN_FROM_FIREBASE",
    "app_version": "1.0.0",
    "is_active": true,
    "last_seen_at": "2026-04-11T14:38:25Z",
    "last_used_at": "2026-04-11T14:38:25Z",
    "created_at": "2026-04-11T14:10:00Z",
    "updated_at": "2026-04-11T14:38:25Z"
  }
}
```

## 6. Refresh Device Token

### Endpoint

```http
POST /api/devices/fcm/refresh
```

### Request body

```json
{
  "device_id": "17758959909409221380063272",
  "platform": "android",
  "fcm_token": "NEW_FCM_TOKEN",
  "app_version": "1.0.1"
}
```

### الاستخدام

استخدم هذا endpoint عندما يرجع Firebase توكن جديد من:

```dart
FirebaseMessaging.instance.onTokenRefresh.listen(...)
```

## 7. Unregister Device

### Endpoint

```http
DELETE /api/devices/fcm/unregister
```

### Request body

```json
{
  "device_id": "17758959909409221380063272"
}
```

أو:

```json
{
  "fcm_token": "FCM_TOKEN_FROM_FIREBASE"
}
```

## 8. What Flutter Will Receive

الباك إند يرسل دائمًا:

- `notification`
- `data`

هذا مهم لأن:

- `notification` يجعل النظام يعرض الإشعار عندما التطبيق في background أو مغلق
- `data` يحدد للشاشة أي route يجب فتحه عند الضغط

## 9. Chat Message Payload

هذا هو الشكل المتوقع لإشعار رسالة جديدة:

### notification

```json
{
  "title": "اسم المحل أو اسم المرسل",
  "body": "معاينة الرسالة"
}
```

### data

```json
{
  "type": "chat_message",
  "chat_id": "148",
  "chat_type": "shop_customer",
  "order_id": "148",
  "order_number": "OD123456",
  "shop_id": "3",
  "shop_name": "Mr Delivery",
  "shop_profile_image_url": "https://...",
  "sender_id": "3",
  "sender_type": "shop_owner",
  "sender_name": "اسم المرسل",
  "content_type": "text",
  "message_preview": "مرحبا",
  "route": "/chat",
  "click_action": "OPEN_CHAT"
}
```

### Flutter handling

إذا كان:

- `type == chat_message`
- `route == /chat`

يفتح التطبيق شاشة الشات المناسبة باستخدام:

- `order_id`
- `chat_type`
- `chat_id`

## 10. Incoming Ring Payload

هذا الإشعار يرسل كـ high priority.

### notification

```json
{
  "title": "Mr Delivery",
  "body": "يوجد اتصال أو رنة جديدة"
}
```

### data

```json
{
  "type": "incoming_ring",
  "ring_id": "ring-1",
  "call_id": "ring-1",
  "order_id": "148",
  "order_number": "OD123456",
  "shop_id": "3",
  "shop_name": "Mr Delivery",
  "shop_profile_image_url": "https://...",
  "target": "customer",
  "chat_type": "shop_customer",
  "sender_id": "3",
  "sender_type": "shop_owner",
  "sender_name": "اسم المرسل",
  "caller_name": "اسم المتصل",
  "route": "/incoming-ring",
  "click_action": "OPEN_CHAT"
}
```

### Flutter handling

إذا كان:

- `type == incoming_ring`
- `route == /incoming-ring`

يفتح شاشة incoming ring أو call UI.

## 11. Broadcast / General Notification Payload

قد يستقبل التطبيق إشعارات عامة مثل:

```json
{
  "type": "broadcast",
  "route": "/notifications",
  "click_action": "OPEN_NOTIFICATIONS"
}
```

وقد تكون معها بيانات إضافية مثل:

```json
{
  "type": "broadcast",
  "route": "/notifications",
  "campaign_id": "15",
  "audience": "customers"
}
```

### Flutter handling

- إذا `route == /notifications` افتح شاشة الإشعارات
- وإذا عندكم deep link داخلي مختلف يمكن الاعتماد على `type`

## 12. Important Notes For Flutter

### Android 13+

لازم طلب صلاحية الإشعارات:

```dart
await FirebaseMessaging.instance.requestPermission();
```

### onTokenRefresh

لازم ربط:

```dart
FirebaseMessaging.instance.onTokenRefresh.listen((token) {
  // call /api/devices/fcm/refresh
});
```

### Background handler

لازم تعريف handler للخلفية:

```dart
FirebaseMessaging.onBackgroundMessage(_firebaseMessagingBackgroundHandler);
```

### Foreground

عندما التطبيق مفتوح foreground:

- النظام قد لا يعرض الإشعار تلقائيًا على Android
- يمكنكم عرض local notification يدويًا إذا أردتم نفس تجربة background

### Force stop

إذا المستخدم عمل force stop من إعدادات Android:

- FCM غالبًا لن يصل حتى يفتح التطبيق مرة أخرى

هذا سلوك طبيعي من النظام وليس مشكلة من الباك إند.

## 13. Recommended Flutter Flow

### On login

1. سجل الدخول
2. احصل على `fcmToken`
3. احصل على `deviceId`
4. نادِ:
   - `POST /api/devices/fcm/register`

### On token refresh

1. استقبل التوكن الجديد
2. نادِ:
   - `POST /api/devices/fcm/refresh`

### On logout

1. نادِ:
   - `DELETE /api/devices/fcm/unregister`
2. ثم نفّذ logout المحلي

## 14. Suggested Flutter Parsing Logic

يفضل الاعتماد على `message.data` أولًا.

مثال pseudo-code:

```dart
void handlePushData(Map<String, dynamic> data) {
  final type = data['type'];
  final route = data['route'];

  if (type == 'chat_message' && route == '/chat') {
    openChatScreen(
      orderId: data['order_id'],
      chatType: data['chat_type'],
    );
    return;
  }

  if (type == 'incoming_ring' && route == '/incoming-ring') {
    openIncomingRingScreen(
      orderId: data['order_id'],
      ringId: data['ring_id'],
      callerName: data['caller_name'],
    );
    return;
  }

  if (route == '/notifications') {
    openNotificationsScreen();
    return;
  }
}
```

## 15. Do Not Depend On These Assumptions

- لا تعتمدوا على `message_type` داخل FCM data
  - الباك إند يرسل `content_type`
- لا تعتمدوا على وجود socket مفتوح حتى تصل الإشعارات
- لا تفترضوا أن كل مستخدم يملك جهازًا واحدًا فقط

## 16. Summary

المطلوب من Flutter باختصار:

1. إرسال `register` بعد login
2. إرسال `refresh` عند تغيّر التوكن
3. إرسال `unregister` عند logout
4. التعامل مع `chat_message`
5. التعامل مع `incoming_ring`
6. التعامل مع `broadcast`
7. فتح الشاشة المناسبة بالاعتماد على `data.route` و`data.type`

