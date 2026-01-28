# حل سريع للمشاكل الحالية على VPS

## المشكلة 1: AppRegistryNotReady

**الخطأ:**
```
django.core.exceptions.AppRegistryNotReady: Apps aren't loaded yet.
```

**الحل:** تم تعديل `asgi.py` - رفع الملف المحدث على السيرفر.

## المشكلة 2: deploy.sh لا يعمل

**الخطأ:**
```
-bash: ./deploy.sh: cannot execute: required file not found
```

**الحل:** مشكلة في line endings (Windows vs Linux):

```bash
# على VPS
dos2unix deploy.sh
# أو
sed -i 's/\r$//' deploy.sh
chmod +x deploy.sh
```

## المشكلة 3: Supervisor spawn error

**الخطأ:**
```
mr_delivery_daphne: ERROR (spawn error)
```

**الحل:**

1. تحقق من الـ logs:
```bash
sudo tail -f /var/log/mr_delivery/daphne_error.log
```

2. تأكد من المسارات في supervisor config:
```bash
sudo cat /etc/supervisor/conf.d/mr_delivery.conf
```

3. تأكد من وجود venv:
```bash
ls -la /home/Mr_Delivery/venv/bin/daphne
```

4. تأكد من الصلاحيات:
```bash
sudo chown -R www-data:www-data /home/Mr_Delivery
sudo chmod +x /home/Mr_Delivery/venv/bin/daphne
```

## المشكلة 4: Nginx conflicting server name

**التحذير:**
```
conflicting server name "86.48.3.103" on 0.0.0.0:80, ignored
```

**الحل:** فيه ملف nginx تاني بيستخدم نفس الـ server_name. شوف:

```bash
# شوف الملفات الموجودة
ls -la /etc/nginx/sites-enabled/

# أوقف الملفات التانية
sudo rm /etc/nginx/sites-enabled/default
# أو عدّل server_name في الملفات التانية
```

## خطوات الإصلاح السريعة:

### 1. رفع asgi.py المحدث:

```bash
# من جهازك المحلي
scp mr_delivery/asgi.py user@86.48.3.103:/home/Mr_Delivery/mr_delivery/
```

### 2. إصلاح deploy.sh:

```bash
# على VPS
cd /home/Mr_Delivery
dos2unix deploy.sh  # أو sed -i 's/\r$//' deploy.sh
chmod +x deploy.sh
```

### 3. إعادة تشغيل Supervisor:

```bash
sudo supervisorctl stop mr_delivery_daphne
sudo supervisorctl start mr_delivery_daphne
sudo supervisorctl status mr_delivery_daphne
```

### 4. التحقق من الـ logs:

```bash
sudo tail -50 /var/log/mr_delivery/daphne_error.log
```

### 5. اختبار الاتصال:

```bash
curl http://127.0.0.1:8000/api/shop/login/
```

## إذا استمرت المشكلة:

1. شغّل Daphne يدوياً للاختبار:
```bash
cd /home/Mr_Delivery
source venv/bin/activate
daphne -b 127.0.0.1 -p 8000 mr_delivery.asgi:application
```

2. لو شغّل يدوياً، المشكلة في Supervisor config
3. لو ما شغّلش، المشكلة في الكود أو المتطلبات
