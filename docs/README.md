# ðŸ“š Mr Delivery - Complete Documentation

Welcome to **Mr Delivery** documentation - A comprehensive shop management and delivery system.

---

## ðŸ“‘ Table of Contents

### 1. Getting Started
- [ðŸš€ Installation Guide](./INSTALLATION.md)
- [âš™ï¸ Environment Setup](./ENVIRONMENT.md)

### 2. Authentication & Authorization
- [ðŸ” Authentication System](./AUTHENTICATION.md)
- [ðŸ”’ Permissions & Roles](./PERMISSIONS.md)

### 3. API Reference
- [ðŸ“¡ REST API Guide](./REST_API.md)
- [ðŸ”Œ WebSocket API Guide](./WEBSOCKET_API.md)

### 4. Database
- [ðŸ—„ï¸ Database Models](./DATABASE_MODELS.md)

### 5. Features
- [ðŸ’¬ Chat System](./CHAT_SYSTEM.md)
- [Flutter Shop Chat Guide](./FLUTTER_SHOP_CHAT_GUIDE.md)
- [ðŸ“¦ Orders Management](./ORDERS.md)
- [ðŸš— Driver Tracking](./DRIVER_TRACKING.md)

### 6. Deployment
- [ðŸš€ Server Deployment](./DEPLOYMENT.md)

---

## ðŸ—ï¸ Project Overview

### Tech Stack
| Technology | Purpose |
|------------|---------|
| Django 4.x | Backend Framework |
| Django REST Framework | REST API |
| Django Channels | WebSocket / Real-time |
| PostgreSQL / SQLite | Database |
| JWT | Authentication |
| Redis | Channel Layer & Cache |
| Daphne | ASGI Server |

### User Types
| Role | Description | Token Variable |
|------|-------------|----------------|
| **Shop Owner** | Full shop management | `access_token` |
| **Customer** | Shopping & ordering | `customer_token` |
| **Employee** | Order & customer management | `employee_token` |
| **Driver** | Delivery management | `driver_token` |

---

## ðŸ”— Quick Links

- **Postman Collection**: `Mr_Delivery_API.postman_collection.json`
- **WebSocket Test**: `frontend_test.html`
- **Base URL**: `http://86.48.3.103` (development)

---

**Last Updated**: January 2026  
**Version**: 1.0.0

