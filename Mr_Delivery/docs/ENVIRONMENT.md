# ⚙️ Environment Configuration

Environment variables and configuration guide for Mr Delivery.

---

## 📄 Environment File

Create `.env` file in the project root directory.

---

## 🔧 Configuration Variables

### Django Core

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `DEBUG` | Yes | `False` | Enable debug mode (use `True` only in development) |
| `SECRET_KEY` | Yes | - | Django secret key (generate a random 50+ char string) |
| `ALLOWED_HOSTS` | Yes | - | Comma-separated list of allowed hosts |

### Database

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `DATABASE_URL` | No | SQLite | Database connection URL |

**Format:**
```
# PostgreSQL
DATABASE_URL=postgresql://user:password@host:port/database

# SQLite (default)
DATABASE_URL=sqlite:///db.sqlite3
```

### Redis (for WebSocket)

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `REDIS_URL` | Yes* | - | Redis connection URL (*Required for WebSocket) |

**Format:**
```
REDIS_URL=redis://localhost:6379/0
```

### Security

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `CSRF_TRUSTED_ORIGINS` | Prod | - | Trusted origins for CSRF |
| `CORS_ALLOWED_ORIGINS` | Prod | - | Allowed CORS origins |

### JWT

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `JWT_ACCESS_TOKEN_LIFETIME` | No | `1440` | Access token lifetime (minutes) |
| `JWT_REFRESH_TOKEN_LIFETIME` | No | `10080` | Refresh token lifetime (minutes) |

### OTP

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `FIXED_OTP_CODE` | No | `123456` | رمز ثابت من 6 أرقام يُستخدم حتى الاشتراك في خدمة إرسال OTP. إذا معيّن لا يُرسل أي رمز فعلي. لتفعيل الإرسال الفعلي اتركه فارغاً. |

### UltraMsg (WhatsApp OTP)

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `ULTRAMSG_INSTANCE` | No | `instance160549` | UltraMsg instance ID |
| `ULTRAMSG_TOKEN` | No | - | UltraMsg API token |

---

## 📝 Example Configurations

### Development (.env)
```env
DEBUG=True
SECRET_KEY=dev-secret-key-not-for-production-use-only-for-testing
ALLOWED_HOSTS=localhost,127.0.0.1

DATABASE_URL=sqlite:///db.sqlite3
REDIS_URL=redis://localhost:6379/0
```

### Production (.env)
```env
DEBUG=False
SECRET_KEY=your-very-long-and-random-production-secret-key-50-chars-minimum
ALLOWED_HOSTS=your-domain.com,www.your-domain.com,123.45.67.89

DATABASE_URL=postgresql://mrdelivery:secure_password@localhost:5432/mr_delivery
REDIS_URL=redis://localhost:6379/0

CSRF_TRUSTED_ORIGINS=https://your-domain.com,https://www.your-domain.com
CORS_ALLOWED_ORIGINS=https://your-frontend.com
```

---

## 🔐 Generating Secret Key

### Using Python
```python
from django.core.management.utils import get_random_secret_key
print(get_random_secret_key())
```

### Using Command Line
```bash
python -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())"
```

### Using OpenSSL
```bash
openssl rand -base64 50
```

---

## 📊 Django Settings Reference

### settings.py Configuration

```python
import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent.parent

# Core Settings
DEBUG = os.getenv('DEBUG', 'False').lower() == 'true'
SECRET_KEY = os.getenv('SECRET_KEY')
ALLOWED_HOSTS = os.getenv('ALLOWED_HOSTS', '').split(',')

# Database
import dj_database_url
DATABASES = {
    'default': dj_database_url.config(
        default='sqlite:///db.sqlite3'
    )
}

# Redis & Channels
CHANNEL_LAYERS = {
    'default': {
        'BACKEND': 'channels_redis.core.RedisChannelLayer',
        'CONFIG': {
            'hosts': [os.getenv('REDIS_URL', 'redis://localhost:6379/0')],
        },
    },
}

# JWT Settings
from datetime import timedelta
SIMPLE_JWT = {
    'ACCESS_TOKEN_LIFETIME': timedelta(
        minutes=int(os.getenv('JWT_ACCESS_TOKEN_LIFETIME', 1440))
    ),
    'REFRESH_TOKEN_LIFETIME': timedelta(
        minutes=int(os.getenv('JWT_REFRESH_TOKEN_LIFETIME', 10080))
    ),
}

# Security (Production)
if not DEBUG:
    SECURE_BROWSER_XSS_FILTER = True
    SECURE_CONTENT_TYPE_NOSNIFF = True
    X_FRAME_OPTIONS = 'DENY'
    CSRF_TRUSTED_ORIGINS = os.getenv('CSRF_TRUSTED_ORIGINS', '').split(',')
```

---

## 🔍 Verifying Configuration

### Check Environment Variables
```python
# In Django shell
python manage.py shell

import os
print('DEBUG:', os.getenv('DEBUG'))
print('ALLOWED_HOSTS:', os.getenv('ALLOWED_HOSTS'))
print('DATABASE_URL:', os.getenv('DATABASE_URL'))
```

### Check Django Settings
```bash
python manage.py diffsettings
```

### Validate Configuration
```bash
python manage.py check --deploy
```

---

## ⚠️ Security Notes

1. **Never commit `.env` to version control**
   ```gitignore
   # .gitignore
   .env
   .env.local
   .env.production
   ```

2. **Use different keys for development and production**

3. **Restrict database access** - Use strong passwords and limit connections

4. **Redis security** - Consider password protection in production
   ```
   REDIS_URL=redis://:password@localhost:6379/0
   ```

5. **Rotate secrets periodically** - Change SECRET_KEY if compromised

---

## 📁 Related Files

- `.env` - Environment variables (create this)
- `.env.example` - Example configuration (commit this)
- `Mr_Delivery/settings.py` - Django settings
- `.gitignore` - Ensure .env is ignored
