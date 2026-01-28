# إعداد WebSocket على PythonAnywhere

## متطلبات PythonAnywhere

PythonAnywhere يدعم WebSocket ولكن يحتاج إعداد خاص. اتبع الخطوات التالية:

## الخطوة 1: تحديث الإعدادات

### 1. تحديث `ALLOWED_HOSTS` في `settings.py`:

```python
ALLOWED_HOSTS = ['yourusername.pythonanywhere.com']
```

### 2. إعداد Channel Layers لـ PythonAnywhere:

في `settings.py`، استخدم Redis المتوفر على PythonAnywhere:

```python
CHANNEL_LAYERS = {
    'default': {
        'BACKEND': 'channels_redis.core.RedisChannelLayer',
        'CONFIG': {
            "hosts": [('redis.pythonanywhere.com', 6379)],
            "password": "your-redis-password",  # إذا كان مطلوباً
        },
    },
}
```

**ملاحظة:** على PythonAnywhere، Redis متوفر على `redis.pythonanywhere.com` للمستخدمين المدفوعين.

### 3. للتطوير المجاني (Free Account):

إذا كان لديك حساب مجاني ولا يتوفر Redis، استخدم In-Memory:

```python
CHANNEL_LAYERS = {
    'default': {
        'BACKEND': 'channels.layers.InMemoryChannelLayer',
    },
}
```

**تحذير:** In-Memory يعمل فقط مع worker واحد، وقد لا يعمل بشكل صحيح مع WebSocket على PythonAnywhere.

## الخطوة 2: تثبيت المكتبات

في Bash Console على PythonAnywhere:

```bash
pip3.10 install --user channels channels-redis daphne redis
```

أو إذا كنت تستخدم Python 3.11:
```bash
pip3.11 install --user channels channels-redis daphne redis
```

## الخطوة 3: إعداد Web App

### في PythonAnywhere Dashboard:

1. اذهب إلى **Web** tab
2. اضغط على **Add a new web app**
3. اختر **Manual configuration**
4. اختر Python version (3.10 أو 3.11)

### إعداد WSGI:

في **WSGI configuration file**، استبدل الكود بـ:

```python
import os
import sys

# مسار المشروع
path = '/home/yourusername/mr_delivery'  # غيّر yourusername
if path not in sys.path:
    sys.path.insert(0, path)

os.environ['DJANGO_SETTINGS_MODULE'] = 'mr_delivery.settings'

from django.core.wsgi import get_wsgi_application
application = get_wsgi_application()
```

### إعداد ASGI (لـ WebSocket):

أنشئ ملف `asgi.py` في مجلد المشروع (إذا لم يكن موجوداً) أو تأكد من وجوده.

## الخطوة 4: إعداد WebSocket على PythonAnywhere

PythonAnywhere يدعم WebSocket ولكن يحتاج إعداد خاص:

### ⚠️ مهم جداً: إعداد WebSocket في Dashboard

1. اذهب إلى **Web** tab في PythonAnywhere Dashboard
2. ابحث عن قسم **WebSocket** (أسفل الصفحة)
3. أضف WebSocket URLs التالية:

**WebSocket 1:**
- **URL:** `/ws/chat/order/<int:order_id>/`
- **Handler:** `mr_delivery.asgi.application`

**WebSocket 2:**
- **URL:** `/ws/orders/shop/<int:shop_owner_id>/`
- **Handler:** `mr_delivery.asgi.application`

4. اضغط على **Reload** لإعادة تحميل التطبيق

### ملاحظات مهمة:

- **الحساب المجاني:** قد لا يدعم WebSocket. يُنصح بالترقية للحساب المدفوع
- **URL Pattern:** استخدم `<int:order_id>` وليس `{order_id}` في PythonAnywhere
- **Handler:** يجب أن يشير إلى `mr_delivery.asgi.application` (تأكد من المسار الصحيح)

### خيار 2: استخدام Daphne (موصى به)

1. في **Web** tab، في **Source code** section:
   - **Working directory:** `/home/yourusername/mr_delivery`
   
2. في **Static files** section:
   - **URL:** `/static/`
   - **Directory:** `/home/yourusername/mr_delivery/static`
   
   - **URL:** `/media/`
   - **Directory:** `/home/yourusername/mr_delivery/media`

3. في **WSGI configuration file**، استبدل الكود بـ:

```python
import os
import sys

path = '/home/yourusername/mr_delivery'
if path not in sys.path:
    sys.path.insert(0, path)

os.environ['DJANGO_SETTINGS_MODULE'] = 'mr_delivery.settings'

# استخدام Daphne لـ WebSocket
from daphne.server import Server
from mr_delivery.asgi import application

server = Server(application, endpoints=['tcp:8000:interface=127.0.0.1'])
server.run()
```

**ملاحظة:** PythonAnywhere قد لا يدعم Daphne مباشرة. استخدم الخيار 1 بدلاً منه.

## الخطوة 5: تحديث URLs

في Frontend، استخدم HTTPS وليس HTTP:

```javascript
// استبدل
ws://localhost:8000/ws/chat/order/1/?token=...

// بـ
wss://yourusername.pythonanywhere.com/ws/chat/order/1/?token=...
```

**ملاحظة:** استخدم `wss://` (WebSocket Secure) وليس `ws://` على PythonAnywhere.

## الخطوة 6: إعدادات إضافية

### تحديث `settings.py`:

```python
# إعدادات PythonAnywhere
DEBUG = False  # للإنتاج
ALLOWED_HOSTS = ['yourusername.pythonanywhere.com']

# Media files
MEDIA_URL = '/media/'
MEDIA_ROOT = '/home/yourusername/mr_delivery/media'

# Static files
STATIC_URL = '/static/'
STATIC_ROOT = '/home/yourusername/mr_delivery/static'
```

### جمع Static Files:

```bash
python3.10 manage.py collectstatic
```

## الخطوة 7: تشغيل Migrations

```bash
python3.10 manage.py migrate
```

## استكشاف الأخطاء

### خطأ: "WebSocket connection failed"
- تأكد من استخدام `wss://` وليس `ws://`
- تأكد من أن WebSocket مفعّل في PythonAnywhere Dashboard
- تحقق من أن Token صحيح

### خطأ: "Redis connection failed"
- تأكد من أن لديك حساب مدفوع (Redis متوفر للمستخدمين المدفوعين فقط)
- أو استخدم In-Memory Channel Layer للتطوير

### خطأ: "Module not found"
- تأكد من تثبيت جميع المكتبات في Bash Console
- استخدم `pip3.10 install --user` أو `pip3.11 install --user`

## ملاحظات مهمة

1. **الحساب المجاني:** قد لا يدعم WebSocket بشكل كامل. يُنصح بالترقية للحساب المدفوع.

2. **Redis:** متوفر فقط للمستخدمين المدفوعين على `redis.pythonanywhere.com`

3. **HTTPS:** PythonAnywhere يستخدم HTTPS، لذلك يجب استخدام `wss://` في WebSocket URLs

4. **Port:** PythonAnywhere يستخدم منافذ محددة، لا حاجة لتحديد المنفذ في URL

## مثال كود Frontend محدث:

```javascript
// الحصول على اسم المستخدم من البيئة
const username = 'yourusername'; // أو من متغير البيئة
const orderId = 1;
const token = 'your_access_token';

// استخدام wss:// بدلاً من ws://
const ws = new WebSocket(
    `wss://${username}.pythonanywhere.com/ws/chat/order/${orderId}/?token=${token}`
);

ws.onopen = function(event) {
    console.log('تم الاتصال بنجاح');
};

ws.onmessage = function(event) {
    const data = JSON.parse(event.data);
    console.log('رسالة:', data);
};
```

## الدعم

إذا واجهت مشاكل:
1. تحقق من PythonAnywhere Documentation: https://help.pythonanywhere.com/
2. تحقق من Channels Documentation: https://channels.readthedocs.io/
3. راجع WebSocket logs في PythonAnywhere Dashboard
