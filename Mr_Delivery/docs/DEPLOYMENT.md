# 🚀 Server Deployment Guide

Complete guide to deploy Mr Delivery on a production server.

---

## 📋 Server Requirements

| Requirement | Minimum | Recommended |
|-------------|---------|-------------|
| RAM | 1 GB | 2 GB+ |
| CPU | 1 Core | 2 Cores+ |
| Storage | 10 GB | 20 GB+ |
| OS | Ubuntu 20.04+ | Ubuntu 22.04 |

---

## 🛠️ Initial Server Setup

### 1. Connect to Server
```bash
ssh root@your-server-ip
```

### 2. Update System
```bash
apt update && apt upgrade -y
```

### 3. Install Required Packages
```bash
apt install -y python3 python3-pip python3-venv \
    nginx supervisor redis-server \
    postgresql postgresql-contrib \
    git curl
```

### 4. Create App User (Optional but Recommended)
```bash
adduser mrdelivery
usermod -aG sudo mrdelivery
```

---

## 📦 Application Setup

### 1. Clone Repository
```bash
cd /home
git clone https://github.com/your-repo/Mr_Delivery.git
cd Mr_Delivery
```

### 2. Create Virtual Environment
```bash
python3 -m venv venv
source venv/bin/activate
```

### 3. Install Python Dependencies
```bash
pip install --upgrade pip
pip install -r requirements.txt
pip install gunicorn daphne psycopg2-binary
```

### 4. Create Environment File
```bash
nano .env
```

```env
# Django Settings
DEBUG=False
SECRET_KEY=your-very-long-random-secret-key-here
ALLOWED_HOSTS=your-domain.com,your-server-ip

# Database
DATABASE_URL=postgresql://mrdelivery:password@localhost/mr_delivery

# Redis
REDIS_URL=redis://localhost:6379/0

# Security
CSRF_TRUSTED_ORIGINS=https://your-domain.com
CORS_ALLOWED_ORIGINS=https://your-frontend-domain.com
```

---

## 🗄️ Database Setup

### PostgreSQL
```bash
# Access PostgreSQL
sudo -u postgres psql

# Create database and user
CREATE DATABASE mr_delivery;
CREATE USER mrdelivery WITH PASSWORD 'your-secure-password';
ALTER ROLE mrdelivery SET client_encoding TO 'utf8';
ALTER ROLE mrdelivery SET default_transaction_isolation TO 'read committed';
ALTER ROLE mrdelivery SET timezone TO 'UTC';
GRANT ALL PRIVILEGES ON DATABASE mr_delivery TO mrdelivery;
\q
```

### Run Migrations
```bash
source venv/bin/activate
python manage.py makemigrations
python manage.py migrate
python manage.py createsuperuser
python manage.py collectstatic --noinput
```

---

## ⚙️ Supervisor Configuration

### Create Daphne Config
```bash
sudo nano /etc/supervisor/conf.d/mr_delivery_daphne.conf
```

```ini
[program:mr_delivery_daphne]
directory=/home/Mr_Delivery
command=/home/Mr_Delivery/venv/bin/daphne -b 127.0.0.1 -p 8000 Mr_Delivery.asgi:application
user=root
autostart=true
autorestart=true
stopasgroup=true
killasgroup=true
redirect_stderr=true
stdout_logfile=/var/log/mr_delivery_daphne.log
stderr_logfile=/var/log/mr_delivery_daphne_error.log
environment=LANG=en_US.UTF-8,LC_ALL=en_US.UTF-8
```

### Apply Configuration
```bash
sudo supervisorctl reread
sudo supervisorctl update
sudo supervisorctl start mr_delivery_daphne
```

### Check Status
```bash
sudo supervisorctl status mr_delivery_daphne
```

---

## 🌐 Nginx Configuration

### Create Site Config
```bash
sudo nano /etc/nginx/sites-available/mr_delivery
```

```nginx
upstream mr_delivery_app {
    server 127.0.0.1:8000;
}

server {
    listen 80;
    server_name your-domain.com your-server-ip;
    
    # Redirect HTTP to HTTPS (uncomment after SSL setup)
    # return 301 https://$server_name$request_uri;
    
    client_max_body_size 20M;
    
    # Static files
    location /static/ {
        alias /home/Mr_Delivery/staticfiles/;
        expires 30d;
        add_header Cache-Control "public, immutable";
    }
    
    # Media files
    location /media/ {
        alias /home/Mr_Delivery/media/;
        expires 7d;
    }
    
    # WebSocket
    location /ws/ {
        proxy_pass http://mr_delivery_app;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 86400;
    }
    
    # API and Admin
    location / {
        proxy_pass http://mr_delivery_app;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

### Enable Site
```bash
sudo ln -s /etc/nginx/sites-available/mr_delivery /etc/nginx/sites-enabled/
sudo rm /etc/nginx/sites-enabled/default  # Remove default site
sudo nginx -t
sudo systemctl restart nginx
```

---

## 🔒 SSL Certificate (HTTPS)

### Using Certbot (Let's Encrypt)
```bash
apt install certbot python3-certbot-nginx -y
certbot --nginx -d your-domain.com
```

### Auto-Renewal
```bash
# Test renewal
certbot renew --dry-run

# Add to crontab
crontab -e
# Add this line:
0 12 * * * /usr/bin/certbot renew --quiet
```

---

## 🔧 Service Management

### Supervisor Commands
```bash
# Start
sudo supervisorctl start mr_delivery_daphne

# Stop
sudo supervisorctl stop mr_delivery_daphne

# Restart
sudo supervisorctl restart mr_delivery_daphne

# Status
sudo supervisorctl status

# View logs
tail -f /var/log/mr_delivery_daphne.log
```

### Nginx Commands
```bash
sudo systemctl start nginx
sudo systemctl stop nginx
sudo systemctl restart nginx
sudo systemctl status nginx
```

### Redis Commands
```bash
sudo systemctl start redis
sudo systemctl stop redis
sudo systemctl status redis
```

---

## 🔄 Deployment Script

Create deployment script:
```bash
nano /home/Mr_Delivery/deploy.sh
```

```bash
#!/bin/bash
set -e

echo "🚀 Starting deployment..."

cd /home/Mr_Delivery

# Activate virtual environment
source venv/bin/activate

# Pull latest changes
echo "📥 Pulling latest changes..."
git pull origin main

# Install/update dependencies
echo "📦 Installing dependencies..."
pip install -r requirements.txt

# Run migrations
echo "🗄️ Running migrations..."
python manage.py migrate

# Collect static files
echo "📁 Collecting static files..."
python manage.py collectstatic --noinput

# Restart application
echo "🔄 Restarting application..."
sudo supervisorctl restart mr_delivery_daphne

echo "✅ Deployment complete!"
```

```bash
chmod +x /home/Mr_Delivery/deploy.sh
```

### Run Deployment
```bash
./deploy.sh
```

---

## 📊 Monitoring

### Check Application Logs
```bash
# Daphne logs
tail -f /var/log/mr_delivery_daphne.log

# Nginx access logs
tail -f /var/log/nginx/access.log

# Nginx error logs
tail -f /var/log/nginx/error.log
```

### Check System Resources
```bash
# CPU & Memory
htop

# Disk usage
df -h

# Active connections
netstat -tlpn
```

---

## 🔥 Firewall Setup

```bash
# Allow SSH
ufw allow 22

# Allow HTTP & HTTPS
ufw allow 80
ufw allow 443

# Enable firewall
ufw enable
ufw status
```

---

## ✅ Post-Deployment Checklist

- [ ] Application running (`supervisorctl status`)
- [ ] Nginx running (`systemctl status nginx`)
- [ ] Redis running (`systemctl status redis`)
- [ ] SSL certificate installed
- [ ] Static files accessible
- [ ] Media uploads working
- [ ] API endpoints responding
- [ ] WebSocket connections working
- [ ] Admin panel accessible
- [ ] Firewall configured
- [ ] Logs being written

---

## 🆘 Troubleshooting

### 502 Bad Gateway
```bash
# Check if Daphne is running
sudo supervisorctl status
# Restart if needed
sudo supervisorctl restart mr_delivery_daphne
```

### WebSocket Not Connecting
```bash
# Check Nginx WebSocket config
# Ensure proxy_http_version 1.1 and Upgrade headers are set
sudo nginx -t
```

### Static Files 404
```bash
# Re-collect static files
python manage.py collectstatic --noinput
# Check Nginx static location
sudo nginx -t
```

### Database Connection Error
```bash
# Check PostgreSQL status
sudo systemctl status postgresql
# Verify database credentials in .env
```
