# 🚀 Installation Guide

Step-by-step guide to set up Mr Delivery on your local machine or server.

---

## 📋 Prerequisites

- Python 3.9+
- pip (Python package manager)
- Redis Server (for WebSocket)
- PostgreSQL (recommended) or SQLite
- Git

---

## 🖥️ Local Development Setup

### 1. Clone the Repository
```bash
git clone https://github.com/your-repo/Mr_Delivery.git
cd Mr_Delivery
```

### 2. Create Virtual Environment
```bash
# Windows
python -m venv venv
venv\Scripts\activate

# Linux/Mac
python3 -m venv venv
source venv/bin/activate
```

### 3. Install Dependencies
```bash
pip install -r requirements.txt
```

### 4. Configure Environment
Create `.env` file in project root:
```env
DEBUG=True
SECRET_KEY=your-secret-key-here
DATABASE_URL=sqlite:///db.sqlite3
REDIS_URL=redis://localhost:6379/0
ALLOWED_HOSTS=localhost,127.0.0.1
```

### 5. Run Migrations
```bash
python manage.py makemigrations
python manage.py migrate
```

### 6. Create Superuser
```bash
python manage.py createsuperuser
```

### 7. Start Redis Server
```bash
# Windows (using Redis for Windows)
redis-server

# Linux
sudo systemctl start redis
```

### 8. Run Development Server
```bash
# For WebSocket support, use Daphne
daphne -b 0.0.0.0 -p 8000 Mr_Delivery.asgi:application

# Or for simple REST API testing
python manage.py runserver
```

### 9. Access the Application
- **API**: http://86.48.3.103/api/
- **Admin**: http://86.48.3.103/admin/
- **WebSocket Test**: Open `frontend_test.html` in browser

---

## 🐧 Linux Server Setup

### 1. Update System
```bash
sudo apt update && sudo apt upgrade -y
```

### 2. Install Python & Dependencies
```bash
sudo apt install python3 python3-pip python3-venv -y
sudo apt install redis-server nginx supervisor -y
```

### 3. Clone & Setup Project
```bash
cd /home
git clone https://github.com/your-repo/Mr_Delivery.git
cd Mr_Delivery

python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 4. Configure Environment
```bash
nano .env
```
```env
DEBUG=False
SECRET_KEY=your-production-secret-key
DATABASE_URL=postgresql://user:pass@localhost/mr_delivery
REDIS_URL=redis://localhost:6379/0
ALLOWED_HOSTS=your-domain.com,your-ip
```

### 5. Run Migrations
```bash
python manage.py makemigrations
python manage.py migrate
python manage.py collectstatic --noinput
```

### 6. Configure Supervisor
```bash
sudo nano /etc/supervisor/conf.d/mr_delivery_daphne.conf
```
```ini
[program:mr_delivery_daphne]
directory=/home/Mr_Delivery
command=/home/Mr_Delivery/venv/bin/daphne -b 0.0.0.0 -p 8000 Mr_Delivery.asgi:application
user=root
autostart=true
autorestart=true
redirect_stderr=true
stdout_logfile=/var/log/mr_delivery_daphne.log
```

### 7. Configure Nginx
```bash
sudo nano /etc/nginx/sites-available/mr_delivery
```
```nginx
server {
    listen 80;
    server_name your-domain.com;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }

    location /static/ {
        alias /home/Mr_Delivery/staticfiles/;
    }

    location /media/ {
        alias /home/Mr_Delivery/media/;
    }
}
```

### 8. Enable & Start Services
```bash
# Enable Nginx site
sudo ln -s /etc/nginx/sites-available/mr_delivery /etc/nginx/sites-enabled/
sudo nginx -t
sudo systemctl restart nginx

# Start Supervisor
sudo supervisorctl reread
sudo supervisorctl update
sudo supervisorctl start mr_delivery_daphne

# Start Redis
sudo systemctl enable redis
sudo systemctl start redis
```

---

## 🔄 Updating the Application

### On Server
```bash
cd /home/Mr_Delivery
source venv/bin/activate
git pull origin main
pip install -r requirements.txt
python manage.py migrate
python manage.py collectstatic --noinput
sudo supervisorctl restart mr_delivery_daphne
```

---

## ✅ Verify Installation

### Check Django
```bash
python manage.py check
```

### Check Services
```bash
# Supervisor status
sudo supervisorctl status

# Nginx status
sudo systemctl status nginx

# Redis status
sudo systemctl status redis
```

### Test API
```bash
curl http://86.48.3.103/api/auth/login/ \
  -X POST \
  -H "Content-Type: application/json" \
  -d '{"role":"shop_owner","shop_number":"12345","password":"test123"}'
```

---

## 🔧 Troubleshooting

### Module Not Found Error
```bash
# Make sure venv is activated
source venv/bin/activate
pip install -r requirements.txt
```

### Redis Connection Error
```bash
# Check if Redis is running
sudo systemctl status redis
sudo systemctl start redis
```

### Permission Denied
```bash
# Fix file permissions
sudo chown -R $USER:$USER /home/Mr_Delivery
```

### Port Already in Use
```bash
# Find and kill process
sudo lsof -i :8000
sudo kill -9 <PID>
```

---

## 📁 Project Structure

```
Mr_Delivery/
├── Mr_Delivery/          # Main Django project
│   ├── settings.py
│   ├── urls.py
│   └── asgi.py
├── user/                 # User/Auth app
│   ├── models.py
│   ├── views.py
│   └── authentication.py
├── shop/                 # Main shop app
│   ├── models.py
│   ├── views.py
│   ├── serializers.py
│   ├── consumers.py      # WebSocket
│   └── permissions.py
├── gallery/              # Gallery app
├── docs/                 # Documentation
├── requirements.txt
├── manage.py
└── frontend_test.html    # WebSocket testing
```
