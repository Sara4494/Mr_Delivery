#!/bin/bash

# سكريبت رفع المشروع على VPS
# الاستخدام: ./deploy.sh

set -e

echo "🚀 بدء عملية الرفع..."

# متغيرات
PROJECT_DIR="/home/Mr_Delivery"
VENV_DIR="$PROJECT_DIR/venv"
USER="www-data"

# التحقق من وجود المشروع
if [ ! -d "$PROJECT_DIR" ]; then
    echo "❌ مجلد المشروع غير موجود: $PROJECT_DIR"
    exit 1
fi

cd $PROJECT_DIR

# تفعيل virtual environment
echo "📦 تفعيل virtual environment..."
source $VENV_DIR/bin/activate

# سحب التحديثات (إذا كنت تستخدم Git)
if [ -d ".git" ]; then
    echo "📥 سحب التحديثات من Git..."
    git pull
fi

# تثبيت/تحديث المتطلبات
echo "📚 تثبيت المتطلبات..."
pip install --upgrade pip
pip install -r requirements.txt

# تشغيل migrations
echo "🗄️ تشغيل migrations..."
python manage.py migrate --noinput

# جمع static files
echo "📁 جمع static files..."
python manage.py collectstatic --noinput

# إعادة تشغيل Supervisor
echo "🔄 إعادة تشغيل Supervisor..."
sudo supervisorctl restart mr_delivery_daphne

# إعادة تحميل Nginx
echo "🌐 إعادة تحميل Nginx..."
sudo systemctl reload nginx

echo "✅ تم الرفع بنجاح!"
echo "📊 حالة الخدمات:"
sudo supervisorctl status mr_delivery_daphne
