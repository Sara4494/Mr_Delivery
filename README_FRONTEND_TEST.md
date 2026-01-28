# دليل استخدام ملف اختبار Frontend

## الملفات

- `frontend_test.html` - ملف HTML كامل لاختبار WebSocket

## كيفية الاستخدام

### 1. للتطوير المحلي:

1. افتح `frontend_test.html` في المتصفح
2. اختر "التطوير المحلي" من قائمة رابط الخادم
3. أدخل:
   - **معرف الطلب:** رقم الطلب (مثلاً: 1)
   - **Access Token:** التوكن من API تسجيل الدخول
4. اضغط على "الاتصال"
5. ابدأ بإرسال الرسائل

### 2. لـ PythonAnywhere:

1. افتح `frontend_test.html` في المتصفح
2. اختر "PythonAnywhere" من قائمة رابط الخادم
3. أدخل:
   - **معرف الطلب:** رقم الطلب
   - **Access Token:** التوكن من API تسجيل الدخول
4. اضغط على "الاتصال"
5. ابدأ بإرسال الرسائل

## الحصول على Access Token

### طريقة 1: من Postman

1. افتح Postman Collection
2. قم بتسجيل الدخول باستخدام `/api/shop/login/`
3. انسخ `access_token` من الـ Response
4. الصقه في حقل Access Token

### طريقة 2: من المتصفح (Console)

```javascript
// تسجيل الدخول
fetch('http://localhost:8000/api/shop/login/', {
    method: 'POST',
    headers: {
        'Content-Type': 'application/json',
    },
    body: JSON.stringify({
        shop_number: '01027153917',
        password: 'your_password'
    })
})
.then(response => response.json())
.then(data => {
    console.log('Access Token:', data.data.access);
    // انسخ هذا التوكن واستخدمه في الصفحة
});
```

### طريقة 3: من cURL

```bash
curl -X POST http://localhost:8000/api/shop/login/ \
  -H "Content-Type: application/json" \
  -d '{"shop_number": "01027153917", "password": "your_password"}'
```

## الميزات

✅ **اتصال WebSocket** - اتصال مباشر مع الخادم  
✅ **إرسال الرسائل** - نص، صوت، صورة  
✅ **استقبال الرسائل** - عرض الرسائل في الوقت الفعلي  
✅ **مؤشر الكتابة** - يظهر عندما يكتب المستخدم  
✅ **تعليم كمقروء** - تعليم الرسائل كمقروءة  
✅ **حالة الاتصال** - عرض حالة الاتصال بوضوح  
✅ **تصميم جميل** - واجهة مستخدم عصرية وسهلة الاستخدام  

## استكشاف الأخطاء

### خطأ: "Connection refused"
- تأكد من تشغيل الخادم (Daphne)
- تأكد من صحة رابط الخادم
- للتطوير المحلي: استخدم `ws://localhost:8000`
- لـ PythonAnywhere: استخدم `wss://mrdelivery.pythonanywhere.com`

### خطأ: "Authentication failed"
- تأكد من صحة Access Token
- تأكد من أن Token لم ينتهِ صلاحيته
- احصل على Token جديد من API تسجيل الدخول

### خطأ: "Order not found"
- تأكد من وجود الطلب في قاعدة البيانات
- تأكد من أن الطلب يخص صاحب المحل المتصل

### الرسائل لا تظهر
- تحقق من Console في المتصفح (F12)
- تأكد من أن الاتصال نشط (Status: متصل)
- تحقق من أن الرسائل يتم حفظها في قاعدة البيانات

## ملاحظات

1. **HTTPS/WSS:** على PythonAnywhere، يجب استخدام `wss://` وليس `ws://`
2. **CORS:** إذا واجهت مشاكل CORS، تأكد من إعدادات الخادم
3. **Token Expiry:** Access Token ينتهي بعد 24 ساعة، احصل على واحد جديد عند الحاجة

## مثال كود JavaScript للاستخدام في مشروعك

```javascript
// الاتصال
const ws = new WebSocket('ws://localhost:8000/ws/chat/order/1/?token=your_token');

// عند الاتصال
ws.onopen = () => {
    console.log('متصل');
};

// استقبال الرسائل
ws.onmessage = (event) => {
    const data = JSON.parse(event.data);
    console.log('رسالة:', data);
};

// إرسال رسالة
ws.send(JSON.stringify({
    type: 'chat_message',
    content: 'مرحباً',
    message_type: 'text'
}));

// قطع الاتصال
ws.close();
```
