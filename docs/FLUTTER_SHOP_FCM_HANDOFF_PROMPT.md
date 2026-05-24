# Flutter Shop FCM Handoff Prompt

استخدم هذا البرومبت مع فريق Flutter الخاص بتطبيق المحل فقط.

لا تعدل أي منطق قائم في تطبيق العميل أو تطبيق الدليفري إلا إذا كان التعديل مشتركًا وآمنًا 100%، لأن إشعاراتهم شغالة بالفعل. المطلوب هو ربط تطبيق المحل مع الـ FCM payloads الجديدة من الباك إند مع الحفاظ على توافق كامل مع السلوك الحالي.

## Prompt

```text
أنت تعمل على تطبيق Flutter الخاص بالمحل فقط داخل مشروع Mr Delivery.

مهم جدًا:
1. لا تكسر أي سلوك حالي في customer app أو driver app.
2. لا تغيّر payload parsing القديم إلا بإضافة دعم backward-compatible.
3. اعتمد على message.data أولًا للتوجيه داخل التطبيق.
4. التطبيق لازم يدعم foreground / background / terminated.
5. عند terminated الصوت والظهور يعتمد على notification payload + Android notification channel + APNs sound، لذلك لا تعتمد على background Dart handler فقط.

اربط إشعارات FCM في تطبيق المحل مع 3 أنواع أساسية:

A) Orders
- data.type = order_update
- data.route = /orders
- data.click_action = OPEN_ORDER
- channel_id = orders_notifications
- sound = order_ring على Android
- aps.sound = order_ring.aiff على iOS
- افتح شاشة الطلبات أو تفاصيل الطلب باستخدام:
  - order_id
  - thread_id إن وجد
  - order_number
  - status

B) Shop-Customer Chat
- data.type = chat
- data.route = /chat
- data.chat_type = shop_customer
- data.click_action = OPEN_CHAT
- channel_id = chat_notifications
- sound = chat_ring على Android
- aps.sound = chat_ring.aiff على iOS
- افتح شات الطلب مباشرة باستخدام:
  - thread_id
  - chat_id
  - order_id
  - order_number
  - shop_id
  - customer_id
  - message_id

C) Driver Chat
- data.type = chat
- data.route = /chat
- data.chat_type = driver_chat
- data.click_action = OPEN_CHAT
- channel_id = driver_notifications
- sound = driver_ring على Android
- aps.sound = driver_ring.aiff على iOS
- افتح محادثة الدليفري باستخدام:
  - conversation_id
  - driver_id
  - order_id
  - order_number
  - message_id

نفذ المطلوب التالي:

1. أنشئ Android notification channels الثلاثة بأسماء ثابتة:
- orders_notifications
- chat_notifications
- driver_notifications

2. اربط كل channel بالصوت المناسب بدون امتداد في Android:
- order_ring
- chat_ring
- driver_ring

3. أضف handlers لهذه الحالات:
- FirebaseMessaging.onMessage
- FirebaseMessaging.onMessageOpenedApp
- FirebaseMessaging.getInitialMessage
- FirebaseMessaging.onBackgroundMessage

4. في foreground:
- اعرض local notification بنفس channel_id القادم من الرسالة لو احتجنا نفس تجربة النظام.
- استخدم title/body من notification إن وجدت، وإلا ابنِ fallback من data.

5. عند الضغط على الإشعار:
- اقرأ route + click_action + type + chat_type
- نفذ navigation مرة واحدة فقط
- امنع تكرار فتح نفس الشاشة إذا كانت مفتوحة بالفعل لنفس المحادثة أو نفس الطلب

6. اجعل parsing backward-compatible:
- لو type == chat_message اعتبره Chat قديم
- لو route == /driver-chats اعتبره Driver Chat قديم
- لو route == /notifications افتح شاشة الإشعارات العامة

7. لا تفترض أن كل القيم موجودة دائمًا:
- استخدم null-safe parsing
- حوّل القيم النصية إلى int فقط عند الحاجة

8. أعطني التعديلات النهائية كودًا كاملًا للملفات المتأثرة مع شرح قصير لمسار التشغيل:
- app bootstrap
- FCM permission + token refresh
- channel creation
- foreground display
- notification tap routing
- terminated launch routing
```

