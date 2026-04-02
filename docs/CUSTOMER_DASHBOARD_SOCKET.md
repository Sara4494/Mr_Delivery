# Customer Dashboard Socket

هذا الملف مخصص لجزء لوحة العميل التي أصبحت تعمل عبر WebSocket بدل REST للقراءة.

## الهدف

السوكت الخاص بالعميل أصبح هو المصدر الأساسي لبيانات:

- قائمة الطلبات
- قائمة المحلات / المحادثات
- قائمة "في الطريق"

القراءة لم تعد تتم من REST لهذه القوائم. الآن البيانات ترجع من الـ WebSocket كالتالي:

- الطلبات من `dashboard_snapshot.data.orders`
- المحلات / المحادثات من `dashboard_snapshot.data.shops.results`
- طلبات "في الطريق" من `dashboard_snapshot.data.on_way.results`

المسارات التالية لم تعد مصدر القراءة للعميل:

- `GET /api/customer/orders/`
- `GET /api/customer/shops-conversations/`
- `GET /api/customer/orders/on-way/`

مهم:

- إنشاء الطلب ما زال عبر `POST /api/customer/orders/`
- تأكيد ورفض الطلب ما زالا عبر REST

## رابط الاتصال

```text
/ws/orders/customer/{customer_id}/?token=<JWT>&lang=ar
```

مثال:

```text
ws://server/ws/orders/customer/7/?token=JWT_TOKEN&lang=ar
```

الشروط:

- المستخدم يجب أن يكون `customer`
- `customer_id` داخل الـ URL يجب أن يساوي `user.id` من التوكن

## ما الذي يصل عند الاتصال

بمجرد نجاح الاتصال، السيرفر يرسل بالترتيب:

1. `connection`
2. `dashboard_snapshot`
3. `orders_snapshot`
4. `shops_snapshot`
5. `on_way_snapshot`

مهم:

- `dashboard_snapshot` هو الـ event الأساسي الجديد
- الـ 3 events الأخرى ما زالت موجودة للتوافق الخلفي مع العميل القديم

## الحدث الأساسي

### `dashboard_snapshot`

هذا هو الحدث الذي يجب أن يعتمد عليه العميل الآن لعرض:

- الطلبات
- المحلات / المحادثات
- طلبات "في الطريق"

```json
{
  "type": "dashboard_snapshot",
  "data": {
    "orders": [
      {
        "...": "same shape as OrderSerializer"
      }
    ],
    "shops": {
      "count": 2,
      "results": [
        {
          "shop_id": 8,
          "shop_name": "برجر كنچ",
          "shop_logo_url": "/media/shops/logo.png",
          "subtitle": "تم التواصل مؤخراً",
          "chat": {
            "order_id": 15,
            "chat_type": "shop_customer",
            "shop_id": 8
          }
        }
      ]
    },
    "on_way": {
      "count": 1,
      "results": [
        {
          "order_id": 15,
          "status_key": "on_way",
          "status_label": "في الطريق",
          "shop_id": 8,
          "shop_name": "برجر كنچ",
          "shop_logo_url": "/media/shops/logo.png",
          "driver_id": 12,
          "driver_name": "أحمد محمود",
          "driver_image_url": "/media/drivers/driver.jpg",
          "driver_role_label": "مندوب التوصيل",
          "chat": {
            "order_id": 15,
            "chat_type": "driver_customer",
            "driver_id": 12
          }
        }
      ]
    }
  },
  "message": "تمت مزامنة لوحة العميل بنجاح"
}
```

## الـ legacy snapshots

هذه الأحداث ما زالت تصل بعد `dashboard_snapshot`:

### `orders_snapshot`

```json
{
  "type": "orders_snapshot",
  "data": {
    "orders": []
  }
}
```

### `shops_snapshot`

```json
{
  "type": "shops_snapshot",
  "data": {
    "count": 0,
    "results": []
  }
}
```

### `on_way_snapshot`

```json
{
  "type": "on_way_snapshot",
  "data": {
    "count": 0,
    "results": []
  }
}
```

## تحديث البيانات يدويًا

إذا احتاج العميل يعمل refresh من نفس السوكت:

```json
{
  "type": "sync_dashboard",
  "request_id": "sync-1001"
}
```

ويمكن أيضًا استخدام:

```json
{
  "type": "refresh_dashboard"
}
```

بعدها السيرفر يعيد:

1. `dashboard_snapshot`
2. `orders_snapshot`
3. `shops_snapshot`
4. `on_way_snapshot`
5. `ack`

## الأحداث اللحظية الأخرى على نفس السوكت

العميل ما زال يستقبل أيضًا:

- `order_update`
- `new_message`
- `support_conversation_update`
- `support_message`
- `driver_location`
- `ring`
- `presence_update`
- `ack`
- `error`

وفي الحالات التالية، السيرفر يعيد إرسال snapshot كامل:

- بعد `order_update`
- بعد `new_message`
- بعد `support_conversation_update`
- بعد `support_message`

أما `driver_location` فهو incremental فقط ولا يفرض refresh كامل وحده.

## توصية التكامل في العميل

استخدمي `dashboard_snapshot` كمرجع أساسي، ثم خزني:

- `data.orders` لشاشة الطلبات
- `data.shops.results` لشاشة المحلات / المحادثات
- `data.on_way.results` لشاشة "في الطريق"

ولو ما زال عندكم كود قديم، يمكن الإبقاء مؤقتًا على التعامل مع:

- `orders_snapshot`
- `shops_snapshot`
- `on_way_snapshot`

لكن الأفضل الآن أن يكون الاعتماد الرئيسي على `dashboard_snapshot`.

## مرجع التنفيذ

- `shop/consumers.py`
- `shop/routing.py`
- `docs/WEBSOCKET_CUSTOMER_CONTRACT.md`
