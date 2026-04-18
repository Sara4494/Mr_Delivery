# Project Structure Refactor

هذا الملف يشرح التقسيمة الجديدة للمشروع بعد تنظيمه Domain-Based بدون نقل الموديلز بين Django apps الحالية، حتى لا تتأثر الجداول أو الـ migrations.

## الهدف

تنظيم الكود بحيث يكون كل مسار وظيفي واضح لوحده:

- `shop_app`: كل ما يخص المحل
- `driver_app`: كل ما يخص السائق
- `customer_app`: كل ما يخص العميل
- `admin_desktop_app`: كل ما يخص الأدمن دسكتوب
- `support_center`: كل ما يخص الدعم والشاتات الخاصة بالدعم
- `platform_core`: الخدمات المشتركة العامة

## مهم

هذا Refactor آمن تنظيميًا:

- لم يتم نقل الموديلز من `shop` و `user`
- لم يتم تغيير أسماء الجداول
- لم يتم تغيير الـ API paths الحالية
- لم يتم كسر imports القديمة الأساسية

## أين بقيت الموديلز؟

حاليًا:

- موديلز المحل / العميل / السائق / الطلبات / الشات: داخل `shop`
- موديلز الأدمن دسكتوب / صاحب المحل / الصلاحيات: داخل `user`

السبب:

نقل الموديلز بين apps في Django يحتاج migrations حساسة جدًا وقد يسبب كسرًا للداتا لو اتعمل مرة واحدة.

## التقسيمة الجديدة

### `admin_desktop_app`

- URLs الخاصة بالأدمن دسكتوب
- تسجيل الدخول
- المستخدمين
- التقارير
- الموافقات
- البلاغات
- إدارة الحسابات

الملف:

- [admin_desktop_app/urls.py](/e:/Mr_Delivery/admin_desktop_app/urls.py)

### `shop_app`

- لوحة المحل
- العملاء
- الموظفين
- الطلبات
- الفواتير
- إعدادات المحل
- Driver chats من ناحية المحل

الملفات:

- [shop_app/urls.py](/e:/Mr_Delivery/shop_app/urls.py)
- [shop_app/routing.py](/e:/Mr_Delivery/shop_app/routing.py)

### `driver_app`

- تسجيل ودخول السائق
- لوحة السائق
- الطلبات
- التحويل
- البروفايل
- driver chats من ناحية السائق

الملفات:

- [driver_app/urls.py](/e:/Mr_Delivery/driver_app/urls.py)
- [driver_app/routing.py](/e:/Mr_Delivery/driver_app/routing.py)

### `customer_app`

- public shops
- profile العميل
- الطلبات
- العناوين
- وسائل الدفع
- الإشعارات

الملفات:

- [customer_app/urls.py](/e:/Mr_Delivery/customer_app/urls.py)
- [customer_app/routing.py](/e:/Mr_Delivery/customer_app/routing.py)

### `support_center`

- customer support chats
- shop/admin support center
- websocket support center

الملفات:

- [support_center/urls.py](/e:/Mr_Delivery/support_center/urls.py)
- [support_center/routing.py](/e:/Mr_Delivery/support_center/routing.py)

### `platform_core`

- `app/status`
- FCM device endpoints
- shared media upload endpoints

الملف:

- [platform_core/urls.py](/e:/Mr_Delivery/platform_core/urls.py)

## ربط المشروع

### HTTP

تم توصيله من:

- [mr_delivery/urls.py](/e:/Mr_Delivery/mr_delivery/urls.py)

### WebSocket

تم تجميعه في:

- [mr_delivery/websocket_urls.py](/e:/Mr_Delivery/mr_delivery/websocket_urls.py)

ثم استخدامه من:

- [mr_delivery/asgi.py](/e:/Mr_Delivery/mr_delivery/asgi.py)

## التوافق مع الكود القديم

الملفات القديمة لم يتم الاعتماد عليها كـ root routing رئيسي، لكن بعض ملفات التوافق ما زالت موجودة حتى لا ينهار أي import قديم.

مثال:

- [shop/routing.py](/e:/Mr_Delivery/shop/routing.py) الآن مجرد re-export للتجميع الجديد.

## المرحلة القادمة المقترحة

لو عايزين نكمل التنظيم بشكل أقوى بدون ريسك:

1. فصل `views.py` الكبير داخل `shop` إلى modules داخلية حسب الدومين.
2. فصل `serializers.py` الكبير بنفس الطريقة.
3. بعد استقرار النظام نبدأ نقل الموديلز نفسها بحذر شديد وعلى migrations مدروسة.
