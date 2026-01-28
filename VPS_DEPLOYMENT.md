# دليل رفع المشروع على VPS

## معلومات السيرفر
- **IP:** 86.48.3.103
- **Domain:** (يمكن إضافته لاحقاً)

## المتطلبات الأساسية

### 1. تثبيت المتطلبات على VPS

```bash
# تحديث النظام
sudo apt update && sudo apt upgrade -y

# تثبيت Python و pip
sudo apt install python3 python3-pip python3-venv -y

# تثبيت Redis
sudo apt install redis-server -y

# تثبيت Nginx
sudo apt install nginx -y

# تثبيت Supervisor (لإدارة العمليات)
sudo apt install supervisor -y

# تثبيت Git
sudo apt install git -y
```

### 2. إعداد Redis

```bash
# تشغيل Redis
sudo systemctl start redis-server
sudo systemctl enable redis-server

# التحقق من حالة Redis
sudo systemctl status redis-server

# اختبار Redis
redis-cli ping
# يجب أن يرد: PONG
```

### 3. رفع المشروع

```bash
# إنشاء مجلد للمشروع
sudo mkdir -p /var/www/mr_delivery
sudo chown $USER:$USER /var/www/mr_delivery

# رفع الملفات (من جهازك المحلي)
# استخدم scp أو git clone
scp -r /path/to/Mr_Delivery/* user@86.48.3.103:/var/www/mr_delivery/

# أو باستخدام Git
cd /var/www/mr_delivery
git clone <your-repo-url> .
```

### 4. إعداد Python Virtual Environment

```bash
cd /var/www/mr_delivery

# إنشاء virtual environment
python3 -m venv venv

# تفعيل virtual environment
source venv/bin/activate

# تثبيت المتطلبات
pip install --upgrade pip
pip install -r requirements.txt

# تثبيت gunicorn و daphne للإنتاج
pip install gunicorn daphne
```

### 5. تحديث إعدادات Django

#### تحديث `settings.py`:

```python
# في settings.py
DEBUG = False
ALLOWED_HOSTS = ['86.48.3.103', 'yourdomain.com']  # أضف domain إذا كان متوفر

# إعدادات Media و Static
STATIC_ROOT = '/var/www/mr_delivery/staticfiles'
MEDIA_ROOT = '/var/www/mr_delivery/media'

# إعدادات Channels للـ VPS
CHANNEL_LAYERS = {
    'default': {
        'BACKEND': 'channels_redis.core.RedisChannelLayer',
        'CONFIG': {
            "hosts": [('127.0.0.1', 6379)],
        },
    },
}
```

### 6. إعداد قاعدة البيانات

```bash
# تفعيل virtual environment
source venv/bin/activate

# تشغيل migrations
python manage.py migrate

# جمع static files
python manage.py collectstatic --noinput

# إنشاء superuser (اختياري)
python manage.py createsuperuser
```

### 7. إعداد Supervisor

أنشئ ملف `/etc/supervisor/conf.d/mr_delivery.conf`:

```ini
[program:mr_delivery_daphne]
command=/var/www/mr_delivery/venv/bin/daphne -b 127.0.0.1 -p 8000 mr_delivery.asgi:application
directory=/var/www/mr_delivery
user=www-data
autostart=true
autorestart=true
redirect_stderr=true
stdout_logfile=/var/log/mr_delivery/daphne.log
environment=DJANGO_SETTINGS_MODULE="mr_delivery.settings"
```

```bash
# إنشاء مجلد للـ logs
sudo mkdir -p /var/log/mr_delivery
sudo chown www-data:www-data /var/log/mr_delivery

# تحديث Supervisor
sudo supervisorctl reread
sudo supervisorctl update
sudo supervisorctl start mr_delivery_daphne

# التحقق من الحالة
sudo supervisorctl status mr_delivery_daphne
```

### 8. إعداد Nginx

أنشئ ملف `/etc/nginx/sites-available/mr_delivery`:

```nginx
upstream django {
    server 127.0.0.1:8000;
}

server {
    listen 80;
    server_name 86.48.3.103;  # أو domain name إذا كان متوفر

    client_max_body_size 100M;

    # Static files
    location /static/ {
        alias /var/www/mr_delivery/staticfiles/;
    }

    # Media files
    location /media/ {
        alias /var/www/mr_delivery/media/;
    }

    # WebSocket
    location /ws/ {
        proxy_pass http://django;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 86400;
    }

    # Django application
    location / {
        proxy_pass http://django;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

```bash
# تفعيل الموقع
sudo ln -s /etc/nginx/sites-available/mr_delivery /etc/nginx/sites-enabled/

# اختبار إعدادات Nginx
sudo nginx -t

# إعادة تشغيل Nginx
sudo systemctl restart nginx
sudo systemctl enable nginx
```

### 9. إعداد SSL (Let's Encrypt) - اختياري

```bash
# تثبيت Certbot
sudo apt install certbot python3-certbot-nginx -y

# الحصول على شهادة SSL (إذا كان لديك domain)
sudo certbot --nginx -d yourdomain.com

# أو بدون domain (استخدم IP فقط)
# SSL غير متاح بدون domain name
```

### 10. فتح المنافذ في Firewall

```bash
# فتح المنافذ المطلوبة
sudo ufw allow 22/tcp    # SSH
sudo ufw allow 80/tcp    # HTTP
sudo ufw allow 443/tcp   # HTTPS (إذا كان SSL مفعّل)

# تفعيل Firewall
sudo ufw enable
sudo ufw status
```

### 11. تحديث Frontend

في `frontend_test.html`، غيّر:

```javascript
// من
const serverUrl = 'ws://localhost:8000';

// إلى
const serverUrl = 'ws://86.48.3.103';  // أو wss:// إذا كان SSL مفعّل
```

### 12. اختبار التطبيق

```bash
# اختبار HTTP
curl http://86.48.3.103/api/shop/login/

# اختبار WebSocket (من المتصفح)
# افتح frontend_test.html وغيّر serverUrl إلى ws://86.48.3.103
```

## الأوامر المفيدة

### إعادة تشغيل الخدمات

```bash
# إعادة تشغيل Supervisor
sudo supervisorctl restart mr_delivery_daphne

# إعادة تشغيل Nginx
sudo systemctl restart nginx

# إعادة تشغيل Redis
sudo systemctl restart redis-server
```

### عرض الـ Logs

```bash
# Supervisor logs
sudo tail -f /var/log/mr_delivery/daphne.log

# Nginx logs
sudo tail -f /var/log/nginx/error.log
sudo tail -f /var/log/nginx/access.log

# Supervisor status
sudo supervisorctl status
```

### تحديث المشروع

```bash
cd /var/www/mr_delivery
source venv/bin/activate

# سحب التحديثات
git pull  # إذا كنت تستخدم Git

# تثبيت المتطلبات الجديدة
pip install -r requirements.txt

# تشغيل migrations
python manage.py migrate

# جمع static files
python manage.py collectstatic --noinput

# إعادة تشغيل Supervisor
sudo supervisorctl restart mr_delivery_daphne
```

## استكشاف الأخطاء

### مشكلة: WebSocket لا يعمل

1. تحقق من Redis:
```bash
redis-cli ping
```

2. تحقق من Supervisor:
```bash
sudo supervisorctl status mr_delivery_daphne
```

3. تحقق من Nginx logs:
```bash
sudo tail -f /var/log/nginx/error.log
```

### مشكلة: Static files لا تظهر

```bash
# تأكد من جمع static files
python manage.py collectstatic --noinput

# تحقق من الصلاحيات
sudo chown -R www-data:www-data /var/www/mr_delivery/staticfiles
```

### مشكلة: Media files لا تظهر

```bash
# تحقق من الصلاحيات
sudo chown -R www-data:www-data /var/www/mr_delivery/media
sudo chmod -R 755 /var/www/mr_delivery/media
```

## ملاحظات مهمة

1. **SECRET_KEY**: تأكد من تغيير `SECRET_KEY` في `settings.py` للإنتاج
2. **Database**: يمكنك استخدام PostgreSQL للإنتاج بدلاً من SQLite
3. **Backup**: قم بعمل backup دوري لقاعدة البيانات
4. **Monitoring**: استخدم أدوات مراقبة مثل `htop` أو `monit`
5. **Security**: راجع إعدادات الأمان في Django للإنتاج

## مثال إعدادات Production

في `settings.py`:

```python
# Security settings
SECURE_SSL_REDIRECT = False  # True إذا كان SSL مفعّل
SESSION_COOKIE_SECURE = False  # True إذا كان SSL مفعّل
CSRF_COOKIE_SECURE = False  # True إذا كان SSL مفعّل
SECURE_BROWSER_XSS_FILTER = True
SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS = 'DENY'
```

## الدعم

إذا واجهت مشاكل:
1. راجع الـ logs في `/var/log/mr_delivery/`
2. تحقق من حالة الخدمات: `sudo supervisorctl status`
3. راجع إعدادات Nginx: `sudo nginx -t`
