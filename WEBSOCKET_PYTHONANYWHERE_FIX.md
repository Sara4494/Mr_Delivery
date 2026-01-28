# حل مشكلة WebSocket 404 على PythonAnywhere

## المشكلة
```
WebSocket connection failed: Error during WebSocket handshake: Unexpected response code: 404
```

هذا يعني أن WebSocket URL غير مُعرّف في PythonAnywhere Dashboard.

## الحل خطوة بخطوة:

### الخطوة 1: التحقق من ASGI Configuration

تأكد من أن `mr_delivery/asgi.py` يحتوي على:

```python
import os
from django.core.asgi import get_asgi_application
from channels.routing import ProtocolTypeRouter, URLRouter
from channels.middleware import BaseMiddlewareStack
import shop.routing
from shop.middleware import JWTAuthMiddleware

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'mr_delivery.settings')

django_asgi_app = get_asgi_application()

application = ProtocolTypeRouter({
    "http": django_asgi_app,
    "websocket": BaseMiddlewareStack(
        JWTAuthMiddleware(
            URLRouter(
                shop.routing.websocket_urlpatterns
            )
        )
    ),
})
```

### الخطوة 2: إعداد WebSocket في PythonAnywhere Dashboard

1. **سجل الدخول** إلى PythonAnywhere Dashboard
2. اذهب إلى **Web** tab
3. ابحث عن قسم **WebSocket** (في الأسفل)
4. أضف WebSocket URLs التالية:

#### WebSocket 1 - للشات:
```
URL: /ws/chat/order/<int:order_id>/
Handler: mr_delivery.asgi.application
```

#### WebSocket 2 - لتحديثات الطلبات:
```
URL: /ws/orders/shop/<int:shop_owner_id>/
Handler: mr_delivery.asgi.application
```

5. **احفظ** التغييرات
6. اضغط على **Reload** لإعادة تحميل التطبيق

### الخطوة 3: التحقق من المسار

تأكد من أن:
- المسار في `Handler` صحيح: `mr_delivery.asgi.application`
- إذا كان المشروع في مجلد فرعي، استخدم المسار الكامل

### الخطوة 4: التحقق من الحساب

- **الحساب المجاني:** قد لا يدعم WebSocket بشكل كامل
- **الحساب المدفوع:** يدعم WebSocket بشكل كامل

إذا كان لديك حساب مجاني و WebSocket لا يعمل:
1. راجع PythonAnywhere Documentation
2. أو فكر في الترقية للحساب المدفوع

### الخطوة 5: اختبار الاتصال

بعد إعداد WebSocket، اختبر الاتصال:

```javascript
const ws = new WebSocket(
    'wss://mrdelivery.pythonanywhere.com/ws/chat/order/1/?token=your_token'
);

ws.onopen = () => console.log('متصل!');
ws.onerror = (error) => console.error('خطأ:', error);
```

## استكشاف الأخطاء الإضافية:

### خطأ: "Module not found: channels"
```bash
# في Bash Console على PythonAnywhere
pip3.10 install --user channels channels-redis daphne redis
```

### خطأ: "Redis connection failed"
- تأكد من إعداد `CHANNEL_LAYERS` في `settings.py`:
```python
CHANNEL_LAYERS = {
    'default': {
        'BACKEND': 'channels_redis.core.RedisChannelLayer',
        'CONFIG': {
            "hosts": [('redis.pythonanywhere.com', 6379)],
        },
    },
}
```

### خطأ: "Handler not found"
- تأكد من أن `mr_delivery.asgi.application` موجود
- تحقق من المسار في PythonAnywhere Dashboard

## مثال إعداد كامل:

### في PythonAnywhere Dashboard → Web → WebSocket:

```
WebSocket URL 1:
URL: /ws/chat/order/<int:order_id>/
Handler: mr_delivery.asgi.application

WebSocket URL 2:
URL: /ws/orders/shop/<int:shop_owner_id>/
Handler: mr_delivery.asgi.application
```

### في settings.py:

```python
CHANNEL_LAYERS = {
    'default': {
        'BACKEND': 'channels_redis.core.RedisChannelLayer',
        'CONFIG': {
            "hosts": [('redis.pythonanywhere.com', 6379)],
        },
    },
}
```

## بعد الإعداد:

1. اضغط **Reload** في Web tab
2. انتظر بضع ثوان
3. جرب الاتصال مرة أخرى من Frontend

## إذا استمرت المشكلة:

1. تحقق من **Error log** في PythonAnywhere Dashboard
2. تحقق من **Server log** في Web tab
3. تأكد من تثبيت جميع المكتبات المطلوبة
4. تأكد من أن الحساب يدعم WebSocket (مدفوع)
