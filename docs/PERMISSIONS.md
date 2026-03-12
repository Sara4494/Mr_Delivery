# 🔒 Permissions & Roles

This document explains the permission system and access control in Mr Delivery.

---

## 👥 User Roles Overview

| Role | Code | Description |
|------|------|-------------|
| Shop Owner | `shop_owner` | Full access to shop management |
| Customer | `customer` | Shopping, ordering, profile management |
| Employee | `employee` | Order handling, customer support |
| Driver | `driver` | Delivery management, location updates |

---

## 🛡️ Permission Classes

Located in: `shop/permissions.py`

### IsShopOwner
```python
# Allows only Shop Owners
@permission_classes([IsShopOwner])
```

### IsCustomer
```python
# Allows only Customers
@permission_classes([IsCustomer])
```

### IsEmployee
```python
# Allows only Employees
@permission_classes([IsEmployee])
```

### IsDriver
```python
# Allows only Drivers
@permission_classes([IsDriver])
```

### IsShopOwnerOrEmployee
```python
# Allows Shop Owners OR Employees
@permission_classes([IsShopOwnerOrEmployee])
```

---

## 📋 API Permissions Matrix

### Shop Owner APIs (`IsShopOwner`)
| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/shop/status/` | GET, PUT | Shop status |
| `/api/shop/customers/` | GET, POST | Customer management |
| `/api/shop/customers/{id}/` | GET, PUT, DELETE | Customer details |
| `/api/shop/drivers/` | GET, POST | Driver management |
| `/api/shop/drivers/{id}/` | GET, PUT, DELETE | Driver details |
| `/api/shop/drivers/{id}/approve/` | POST | Approve driver |
| `/api/shop/employees/` | GET, POST | Employee management |
| `/api/shop/employees/{id}/` | GET, PUT, DELETE | Employee details |
| `/api/shop/employees/statistics/` | GET | Employee stats |
| `/api/shop/products/` | GET, POST | Product management |
| `/api/shop/products/{id}/` | GET, PUT, DELETE | Product details |
| `/api/shop/categories/` | GET, POST | Category management |
| `/api/shop/categories/{id}/` | GET, PUT, DELETE | Category details |
| `/api/shop/orders/` | GET, POST | Order management |
| `/api/shop/orders/{id}/` | GET, PUT, DELETE | Order details |
| `/api/shop/orders/{id}/rating/` | GET | View order rating |
| `/api/shop/invoices/` | GET, POST | Invoice management |
| `/api/shop/invoices/{id}/` | GET, PUT | Invoice details |
| `/api/shop/dashboard/statistics/` | GET | Dashboard stats |

### Customer APIs (`IsCustomer`)
| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/customer/profile/` | GET, PUT, PATCH | Customer profile |
| `/api/customer/addresses/` | GET, POST | Address list |
| `/api/customer/addresses/{id}/` | GET, PUT, DELETE | Address details |
| `/api/customer/payment-methods/` | GET, POST | Payment methods |
| `/api/customer/payment-methods/{id}/` | DELETE | Delete payment |
| `/api/cart/{shop_id}/` | GET | View cart |
| `/api/cart/{shop_id}/add/` | POST | Add to cart |
| `/api/cart/{shop_id}/items/{id}/` | PUT, DELETE | Cart item |
| `/api/cart/{shop_id}/clear/` | DELETE | Clear cart |
| `/api/orders/rate/` | POST | Rate order |

### Driver APIs (`IsDriver`)
| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/driver/location/` | PUT | Update location |

### Public APIs (`AllowAny`)
| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/auth/login/` | POST | Unified login |
| `/api/auth/register/` | POST | Customer registration |

### Authenticated APIs (`IsAuthenticated`)
| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/notifications/` | GET | View notifications |
| `/api/notifications/{id}/read/` | POST | Mark as read |
| `/api/notifications/read-all/` | POST | Mark all as read |
| `/api/shop/orders/{id}/track/` | GET | Track order |

---

## 🔄 How Permission Checks Work

```python
# In views.py
from .permissions import IsShopOwner, IsCustomer

@api_view(['GET'])
@permission_classes([IsShopOwner])  # Only shop owners can access
def shop_dashboard_view(request):
    shop_owner = request.user  # Automatically authenticated user
    # ... your logic
```

---

## ⚠️ Permission Error Response

When a user tries to access an endpoint without proper permission:

```json
{
    "detail": "This action is only available for shop owners"
}
```

**HTTP Status**: `403 Forbidden`

---

## 🔧 Custom Permission Example

```python
# shop/permissions.py

from rest_framework.permissions import BasePermission

class IsShopOwner(BasePermission):
    message = 'This action is only available for shop owners'
    
    def has_permission(self, request, view):
        user = request.user
        if not user or not user.is_authenticated:
            return False
        
        # Check user_type attribute
        if hasattr(user, 'user_type') and user.user_type == 'shop_owner':
            return True
        
        # Or check instance type
        from user.models import ShopOwner
        return isinstance(user, ShopOwner)
```

---

## 📁 Related Files

- `shop/permissions.py` - All permission classes
- `user/authentication.py` - JWT authentication with user type detection
- `shop/views.py` - Views with permission decorators
