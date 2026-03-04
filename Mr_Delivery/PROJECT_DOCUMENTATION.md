# توثيق مشروع Mr Delivery

## نظرة عامة

**Mr Delivery** نظام إدارة وتوصيل للمحلات، يسمح لصاحب المحل بإدارة:
- الملف الشخصي والمحل
- العملاء والموظفين والسائقين
- الطلبات والفواتير
- معرض الصور ومواعيد العمل
- المحادثات مع العملاء (WebSocket)

المشروع مبني بـ **Django** و **Django REST Framework** مع **JWT** للمصادقة، ويدعم الاتصال الفوري عبر **Django Channels** و **WebSockets**.

---

## التقنيات المستخدمة

| التقنية | الاستخدام |
|---------|-----------|
| **Django 6** | إطار العمل الرئيسي |
| **Django REST Framework** | بناء الـ API |
| **djangorestframework-simplejwt** | تسجيل الدخول وإصدار JWT |
| **Django Channels** | WebSockets والمحادثات الفورية |
| **Daphne** | تشغيل التطبيق (ASGI) |
| **Redis** (اختياري) | طبقة Channels على السيرفر |
| **SQLite** (افتراضي) | قاعدة البيانات |

---

## هيكل المشروع

```
Mr_Delivery/
├── mr_delivery/          # إعدادات المشروع
│   ├── settings.py
│   ├── urls.py           # توجيه /api/ للتطبيقات
│   ├── asgi.py           # لـ Daphne و Channels
│   └── wsgi.py
├── user/                 # تطبيق المستخدمين والمصادقة
│   ├── models.py         # ShopOwner
│   ├── authentication.py # JWT لصاحب المحل
│   ├── permissions.py    # IsShopOwner
│   ├── urls.py           # /api/shop/login/ و token/refresh
│   └── ...
├── gallery/              # الملف الشخصي + المعرض + مواعيد العمل
│   ├── models.py         # WorkSchedule, GalleryImage, ImageLike
│   ├── views.py          # profile, schedule, gallery, statistics
│   ├── urls.py           # /api/shop/profile/, gallery/, schedule/, statistics/
│   └── ...
├── shop/                 # إدارة المحل (عملاء، موظفين، سائقين، طلبات، فواتير)
│   ├── models.py         # Customer, Employee, Driver, Order, Invoice, ChatMessage
│   ├── views.py          # كل الـ APIs الخاصة بالمحل
│   ├── urls.py           # /api/shop/... و /api/employee/login/, /api/driver/login/
│   ├── consumers.py      # WebSocket للمحادثات
│   └── routing.py       # مسارات WebSocket
├── deploy.sh             # سكربت الرفع على السيرفر
├── requirements.txt
├── API_DOCUMENTATION.md  # تفاصيل الـ API
├── Mr_Delivery_API.postman_collection.json
└── Mr_Delivery_Environment.postman_environment.json
```

---

## التطبيقات والمسؤوليات

### 1. تطبيق `user`
- **صاحب المحل (ShopOwner):** تسجيل الدخول برقم المحل وكلمة المرور، والحصول على JWT (access + refresh).
- **Endpoints:**  
  - `POST /api/shop/login/` — تسجيل دخول صاحب المحل  
  - `POST /api/shop/token/refresh/` — تجديد الـ access token

### 2. تطبيق `gallery`
- **الملف الشخصي:** عرض وتحديث بيانات المحل وصورة البروفيل (endpoint واحد، الأونر فقط).
- **مواعيد العمل:** عرض وتحديث أيام وساعات العمل.
- **معرض الصور:** رفع، تعديل، حذف، نشر صور المعرض + الإعجاب وإلغاء الإعجاب.
- **إحصائيات:** إحصائيات المحل (صور، إعجابات، إلخ).
- **الصلاحية:** `IsShopOwner` على بروفيل المحل (الأونر فقط يعدّل).

### 3. تطبيق `shop`
- **حالة المحل:** عرض/تحديث (مفتوح، مشغول، مغلق).
- **العملاء:** CRUD للعملاء.
- **الموظفون:** CRUD + إحصائيات الموظفين، تسجيل دخول الموظف JWT.
- **السائقون:** CRUD، تسجيل دخول السائق JWT.
- **الطلبات:** قائمة، تفاصيل، رسائل الطلب، تحديد كمقروءة.
- **الفواتير:** قائمة وتفاصيل.
- **لوحة التحكم:** إحصائيات عامة.
- **المحادثات:** WebSocket لمحادثات الطلبات.

---

## النماذج (Models)

### تطبيق `user`
| النموذج | الوصف |
|---------|--------|
| **ShopOwner** | صاحب المحل: owner_name, shop_name, shop_number, password, profile_image |

### تطبيق `gallery`
| النموذج | الوصف |
|---------|--------|
| **WorkSchedule** | مواعيد عمل المحل (أيام، ساعات) |
| **GalleryImage** | صورة في المعرض (وصف، حالة draft/published، عدد الإعجابات) |
| **ImageLike** | إعجاب على صورة (معرف المستخدم) |

### تطبيق `shop`
| النموذج | الوصف |
|---------|--------|
| **ShopStatus** | حالة المحل (مفتوح / مشغول / مغلق) |
| **Customer** | عميل: اسم، هاتف، عنوان، صورة |
| **Employee** | موظف: اسم، هاتف، كلمة مرور، دور (كاشير، محاسب، إلخ) |
| **Driver** | سائق: اسم، هاتف، كلمة مرور، حالة (متاح، مشغول، أوفلاين) |
| **Order** | طلب: عميل، سائق، حالة، أصناف، مبلغ، عنوان، ملاحظات |
| **ChatMessage** | رسالة في محادثة الطلب (نص، صوت، صورة) |
| **Invoice** | فاتورة مرتبطة بطلب/عميل |

---

## المصادقة (Authentication)

1. **صاحب المحل (Shop Owner)**  
   - تسجيل الدخول: `POST /api/shop/login/`  
   - Body: `{ "shop_number": "...", "password": "..." }`  
   - الرد يحتوي على `access` و `refresh` وبيانات صاحب المحل.  
   - استخدام الـ token: `Authorization: Bearer <access_token>` لجميع APIs الخاصة بالمحل.

2. **الموظف (Employee)**  
   - تسجيل الدخول: `POST /api/employee/login/`  
   - Body: `{ "phone_number": "...", "password": "..." }`  
   - يرجع JWT (access + refresh).

3. **السائق (Driver)**  
   - تسجيل الدخول: `POST /api/driver/login/`  
   - Body: `{ "phone_number": "...", "password": "..." }`  
   - يرجع JWT (access + refresh).

APIs إدارة الموظفين/السائقين/العملاء/الطلبات/الفواتير تتطلب توكين **صاحب المحل** (ما عدا login الموظف والسائق).

---

## هيكل الـ API (البادئة `/api/`)

| البادئة | التطبيق | أمثلة |
|---------|---------|--------|
| `/api/shop/login/` | user | تسجيل دخول الأونر |
| `/api/shop/token/refresh/` | user | تجديد التوكين |
| `/api/shop/profile/` | gallery | عرض/تحديث الملف الشخصي (بيانات + صورة) — الأونر فقط |
| `/api/shop/schedule/` | gallery | مواعيد العمل |
| `/api/shop/gallery/` | gallery | معرض الصور + إعجاب |
| `/api/shop/statistics/` | gallery | إحصائيات المحل |
| `/api/shop/status/` | shop | حالة المحل |
| `/api/shop/customers/` | shop | العملاء |
| `/api/shop/employees/` | shop | الموظفين + إحصائياتهم |
| `/api/shop/drivers/` | shop | السائقين |
| `/api/shop/orders/` | shop | الطلبات والرسائل |
| `/api/shop/invoices/` | shop | الفواتير |
| `/api/shop/dashboard/statistics/` | shop | إحصائيات الداشبورد |
| `/api/employee/login/` | shop | تسجيل دخول الموظف |
| `/api/driver/login/` | shop | تسجيل دخول السائق |

تفاصيل كل endpoint (Body، Response، Headers) موجودة في **API_DOCUMENTATION.md** وفي **Postman Collection**.

---

## التشغيل محلياً

1. **إنشاء بيئة افتراضية وتثبيت المتطلبات:**
   ```bash
   python -m venv venv
   # Windows:
   venv\Scripts\activate
   # Linux/macOS:
   source venv/bin/activate
   pip install -r requirements.txt
   ```

2. **تطبيق migrations:**
   ```bash
   python manage.py migrate
   ```

3. **تشغيل السيرفر:**
   ```bash
   python manage.py runserver
   ```
   أو مع Daphne (للمحادثات WebSocket):
   ```bash
   daphne -b 0.0.0.0 -p 8000 mr_delivery.asgi:application
   ```

4. **اختياري — Redis للمحادثات على السيرفر:**  
   ضبط `REDIS_URL` أو استخدام Redis محلي حسب `settings.py` (CHANNEL_LAYERS).

---

## الرفع على السيرفر (Deploy)

1. **رفع الكود:**  
   - إما `git push` ثم على السيرفر `git pull`، أو رفع الملفات يدوياً.

2. **تشغيل سكربت الرفع (على السيرفر):**
   ```bash
   cd /home/Mr_Delivery
   ./deploy.sh
   ```
   السكربت يقوم بـ:
   - سحب التحديثات (إن وُجد Git)
   - تفعيل الـ venv وتثبيت المتطلبات
   - تشغيل `migrate` و `collectstatic`
   - إعادة تشغيل Supervisor (Daphne)
   - إعادة تحميل Nginx

3. **بدون السكربت (يدوي):**  
   بعد تحديث الكود نفّذ على الأقل:
   ```bash
   sudo supervisorctl restart mr_delivery_daphne
   ```
   حتى تُحمّل التعديلات الجديدة.

تفاصيل السيرفر (المسار، اسم الخدمة) موجودة في `deploy.sh` و `supervisor_config.conf` و `nginx_config.conf`.

---

## الملفات المرجعية

| الملف | المحتوى |
|------|---------|
| **API_DOCUMENTATION.md** | تفاصيل الـ API (طلب/رد، أمثلة) |
| **PROJECT_DOCUMENTATION.md** | هذا الملف — شرح المشروع وهيكله |
| **DESIGN_ANALYSIS.md** | تحليل التصميم والقرارات |
| **Mr_Delivery_API.postman_collection.json** | مجموعة Postman لجميع الـ APIs |
| **Mr_Delivery_Environment.postman_environment.json** | متغيرات البيئة (مثل base_url و access_token) |

---

## ملاحظات أمنية

- في الإنتاج: تغيير `SECRET_KEY` وعدم استخدام `DEBUG = True`.
- ضبط `ALLOWED_HOSTS` و `CSRF_TRUSTED_ORIGINS` حسب الدومين المستخدم.
- حماية مسارات الـ media والـ static حسب إعدادات Nginx/السيرفر.
