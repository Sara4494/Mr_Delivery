# دليل إعداد Postman Collection

## خطوات الاستيراد

### 1. استيراد Collection
1. افتح Postman
2. اضغط على **Import** (أعلى يسار الشاشة)
3. اختر **File** أو **Upload Files**
4. اختر ملف `Mr_Delivery_API.postman_collection.json`
5. اضغط **Import**

### 2. استيراد Environment (موصى به)
1. في Postman، اضغط على **Import**
2. اختر ملف `Mr_Delivery_Environment.postman_environment.json`
3. اضغط **Import**
4. من القائمة المنسدلة في أعلى يمين Postman، اختر **Mr Delivery Environment**

## استخدام Collection

### المتغيرات (Variables)

#### في Collection:
- `{{base_url}}` - رابط API الأساسي (افتراضي: `http://localhost:8000`)

#### في Environment:
- `base_url` - رابط API الأساسي
- `shop_number` - رقم المحل الافتراضي
- `access_token` - Token للوصول (يتم حفظه تلقائياً بعد تسجيل الدخول)
- `refresh_token` - Token للتحديث (يتم حفظه تلقائياً بعد تسجيل الدخول)

### خطوات الاستخدام

#### 1. تسجيل الدخول
1. نفذ request **"تسجيل الدخول"**
2. سيتم حفظ `access_token` و `refresh_token` تلقائياً في Environment
3. يمكنك رؤية Token في Environment variables

#### 2. استخدام APIs الأخرى
- جميع requests الأخرى تستخدم `{{access_token}}` تلقائياً في Header
- لا حاجة لإضافة Token يدوياً
- إذا انتهى Token، استخدم **"تحديث Token"** request

### تحديث المتغيرات

#### تحديث base_url:
1. اختر Environment من القائمة المنسدلة
2. اضغط على أيقونة العين 👁️ بجانب Environment
3. عدّل قيمة `base_url` حسب الحاجة
   - للتطوير المحلي: `http://localhost:8000`
   - للإنتاج: `https://yourdomain.com`

#### تحديث shop_number:
- يمكنك تحديثه في Environment
- أو استبدله مباشرة في request "تسجيل الدخول"

## المجموعات (Folders)

### 1. Authentication
- **تسجيل الدخول** - يحفظ Token تلقائياً
- **تحديث Token** - لتحديث access token

### 2. Shop Profile
- عرض الملف الشخصي (يتطلب Token)
- تحديث الملف الشخصي (يتطلب Token)

### 3. Work Schedule
- عرض مواعيد العمل (يتطلب Token)
- تحديث مواعيد العمل (يتطلب Token)

### 4. Gallery
- جميع APIs تتطلب Token في Header
- عرض قائمة الصور
- إضافة صورة جديدة
- عرض/تحديث/حذف صورة
- الإعجاب/إلغاء الإعجاب

### 5. Statistics
- إحصائيات المحل (يتطلب Token)

## نصائح للاستخدام

### 1. Token تلقائي
- بعد تسجيل الدخول، Token يُحفظ تلقائياً
- جميع requests تستخدم Token من Environment
- لا حاجة لإضافة Token يدوياً

### 2. رفع الصور
- في request "إضافة صورة جديدة":
  - اختر **Body** → **form-data**
  - في حقل `image`، اختر **File** من القائمة المنسدلة
  - اضغط **Select Files** واختر الصورة

### 3. تحديث Token
- إذا انتهى Token (401 Unauthorized):
  1. نفذ request "تحديث Token"
  2. سيتم تحديث `access_token` تلقائياً

### 4. Testing
- بعد كل request، تحقق من:
  - Status Code (يجب أن يكون 200 أو 201 للنجاح)
  - Response Body (يجب أن يحتوي على `"success": true`)

## استكشاف الأخطاء

### خطأ: 401 Unauthorized
- **السبب:** Token منتهي أو غير صحيح
- **الحل:** 
  1. نفذ "تسجيل الدخول" مرة أخرى
  2. أو استخدم "تحديث Token"

### خطأ: "Could not get response"
- تحقق من أن السيرفر يعمل: `python manage.py runserver`
- تحقق من `base_url` في Environment

### خطأ: 404 Not Found
- تحقق من URL
- تأكد من أن الـ endpoint موجود في `urls.py`

### خطأ: 400 Bad Request
- تحقق من Request Body
- تأكد من أن جميع الحقول المطلوبة موجودة
- تحقق من تنسيق البيانات (JSON صحيح)

### Token لا يُحفظ تلقائياً
- تأكد من أن Environment مفعّل
- تحقق من Test Script في request "تسجيل الدخول"
- تأكد من أن response يحتوي على `success: true` و `data.access`
