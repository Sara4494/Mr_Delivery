# Mr Delivery - Complete Documentation

Welcome to **Mr Delivery** documentation - a comprehensive shop management and delivery system.

---

## Table of Contents

### 1. Getting Started
- [Installation Guide](./INSTALLATION.md)
- [Environment Setup](./ENVIRONMENT.md)

### 2. Authentication & Authorization
- [Authentication System](./AUTHENTICATION.md)
- [Permissions & Roles](./PERMISSIONS.md)

### 3. API Reference
- [REST API Guide](./REST_API.md)
- [WebSocket API Guide](./WEBSOCKET_API.md)
- [Customer Dashboard Socket](./CUSTOMER_DASHBOARD_SOCKET.md)

### 4. Database
- [Database Models](./DATABASE_MODELS.md)

### 5. Features
- [Chat System](./CHAT_SYSTEM.md)
- [Shop Frontend Support Chat Guide](./SHOP_FRONTEND_SUPPORT_CHAT_GUIDE.md)
- [Flutter Shop Chat Guide](./FLUTTER_SHOP_CHAT_GUIDE.md)
- [Flutter Driver App Chat Guide](./FLUTTER_DRIVER_APP_CHAT_GUIDE.md)
- [Orders Management](./ORDERS.md)
- [Driver Tracking](./DRIVER_TRACKING.md)

### 6. Deployment
- [Server Deployment](./DEPLOYMENT.md)

---

## Project Overview

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

## Quick Links

- **Postman Collection**: `Mr Delivery API.postman_collection.json`
- **WebSocket Test**: `frontend_test.html`
- **Base URL**: `http://86.48.3.103` (development)

---

**Last Updated**: January 2026  
**Version**: 1.0.0
