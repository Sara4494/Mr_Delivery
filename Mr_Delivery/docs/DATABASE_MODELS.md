# 🗄️ Database Models

Complete database schema documentation for Mr Delivery.

---

## 📊 Models Overview

### User App (`user/models.py`)
| Model | Description |
|-------|-------------|
| ShopOwner | Shop owner account |

### Shop App (`shop/models.py`)
| Model | Description |
|-------|-------------|
| ShopStatus | Shop open/close status |
| Customer | Customer profiles |
| CustomerAddress | Customer delivery addresses |
| Employee | Shop employees |
| Driver | Delivery drivers |
| Category | Product categories |
| Product | Shop products |
| Order | Customer orders |
| OrderRating | Order ratings/reviews |
| Invoice | Quick invoices |
| ChatMessage | Chat messages |
| PaymentMethod | Customer payment cards |
| Notification | System notifications |
| Cart | Shopping carts |
| CartItem | Cart items |

### Gallery App (`gallery/models.py`)
| Model | Description |
|-------|-------------|
| GalleryImage | Shop gallery images |
| ImageLike | Image likes |

---

## 🏪 ShopOwner Model

```python
class ShopOwner:
    shop_number      # CharField(unique) - Shop login number
    password         # CharField - Hashed password
    owner_name       # CharField - Owner's name
    shop_name        # CharField - Shop display name
    profile_image    # ImageField - Profile picture
    phone_number     # CharField - Contact number
    is_active        # BooleanField - Account status
    work_days        # CharField - Working days
    work_hours       # CharField - Working hours
    created_at       # DateTimeField
    updated_at       # DateTimeField
```

---

## 👤 Customer Model

```python
class Customer:
    shop_owner       # ForeignKey(ShopOwner, null=True)
    name             # CharField - Customer name
    phone_number     # CharField(unique) - Login phone
    email            # EmailField(null=True)
    password         # CharField - Hashed password
    profile_image    # ImageField(null=True)
    is_verified      # BooleanField - Phone verified
    created_at       # DateTimeField
    
    # Methods
    set_password(raw_password)  # Hash and set password
    check_password(raw_password)  # Verify password
```

---

## 📍 CustomerAddress Model

```python
class CustomerAddress:
    customer         # ForeignKey(Customer)
    title            # CharField - "Home", "Work", etc.
    address_type     # CharField - home/work/other
    full_address     # TextField
    latitude         # DecimalField(null=True)
    longitude        # DecimalField(null=True)
    building_number  # CharField(null=True)
    floor            # CharField(null=True)
    apartment        # CharField(null=True)
    notes            # TextField(null=True)
    is_default       # BooleanField
    created_at       # DateTimeField
```

---

## 👨‍💼 Employee Model

```python
class Employee:
    shop_owner       # ForeignKey(ShopOwner)
    name             # CharField
    phone_number     # CharField(unique)
    password         # CharField
    role             # CharField - cashier/accountant/manager
    is_active        # BooleanField
    created_at       # DateTimeField
    
    ROLE_CHOICES = [
        ('cashier', 'Cashier'),
        ('accountant', 'Accountant'),
        ('manager', 'Manager')
    ]
```

---

## 🚗 Driver Model

```python
class Driver:
    shop_owner       # ForeignKey(ShopOwner)
    name             # CharField
    phone_number     # CharField(unique)
    password         # CharField
    status           # CharField - available/busy/offline/pending
    rating           # DecimalField - Average rating
    total_deliveries # IntegerField
    current_orders_count  # IntegerField
    current_latitude      # DecimalField(null=True)
    current_longitude     # DecimalField(null=True)
    location_updated_at   # DateTimeField(null=True)
    created_at       # DateTimeField
    
    STATUS_CHOICES = [
        ('available', 'Available'),
        ('busy', 'Busy'),
        ('offline', 'Offline'),
        ('pending', 'Pending Approval')
    ]
```

---

## 📦 Category Model

```python
class Category:
    shop_owner       # ForeignKey(ShopOwner)
    name             # CharField - Arabic name
    name_en          # CharField(null=True) - English name
    icon             # CharField(null=True) - Icon name
    image            # ImageField(null=True)
    display_order    # IntegerField - Sort order
    is_active        # BooleanField
    created_at       # DateTimeField
```

---

## 🍔 Product Model

```python
class Product:
    shop_owner       # ForeignKey(ShopOwner)
    category         # ForeignKey(Category, null=True)
    name             # CharField
    description      # TextField(null=True)
    price            # DecimalField
    discount_price   # DecimalField(null=True)
    image            # ImageField(null=True)
    is_available     # BooleanField
    is_featured      # BooleanField
    created_at       # DateTimeField
    
    @property
    def final_price(self):
        return self.discount_price or self.price
```

---

## 📋 Order Model

```python
class Order:
    shop_owner       # ForeignKey(ShopOwner)
    customer         # ForeignKey(Customer)
    employee         # ForeignKey(Employee, null=True)
    driver           # ForeignKey(Driver, null=True)
    delivery_address # ForeignKey(CustomerAddress, null=True)
    order_number     # CharField(unique)
    items            # TextField - Order items
    total_amount     # DecimalField
    delivery_fee     # DecimalField
    address          # TextField - Delivery address text
    notes            # TextField(null=True)
    status           # CharField
    payment_method   # CharField - cash/card/wallet
    is_paid          # BooleanField
    estimated_delivery_time  # IntegerField(null=True) - Minutes
    delivered_at     # DateTimeField(null=True)
    unread_messages_count    # IntegerField
    created_at       # DateTimeField
    updated_at       # DateTimeField
    
    STATUS_CHOICES = [
        ('new', 'New'),
        ('confirmed', 'Confirmed'),
        ('preparing', 'Preparing'),
        ('on_way', 'On the Way'),
        ('delivered', 'Delivered'),
        ('cancelled', 'Cancelled')
    ]
    
    PAYMENT_METHOD_CHOICES = [
        ('cash', 'Cash'),
        ('card', 'Card'),
        ('wallet', 'Wallet')
    ]
```

---

## 💬 ChatMessage Model

```python
class ChatMessage:
    order            # ForeignKey(Order)
    chat_type        # CharField - shop_customer/driver_customer
    sender_type      # CharField - customer/shop_owner/employee/driver
    sender_customer  # ForeignKey(Customer, null=True)
    sender_shop_owner# ForeignKey(ShopOwner, null=True)
    sender_employee  # ForeignKey(Employee, null=True)
    sender_driver    # ForeignKey(Driver, null=True)
    message_type     # CharField - text/audio/image/location
    content          # TextField(null=True)
    audio_file       # FileField(null=True)
    image_file       # ImageField(null=True)
    latitude         # DecimalField(null=True)
    longitude        # DecimalField(null=True)
    is_read          # BooleanField
    created_at       # DateTimeField
    
    CHAT_TYPE_CHOICES = [
        ('shop_customer', 'Shop-Customer Chat'),
        ('driver_customer', 'Driver-Customer Chat')
    ]
    
    SENDER_TYPE_CHOICES = [
        ('customer', 'Customer'),
        ('shop_owner', 'Shop Owner'),
        ('employee', 'Employee'),
        ('driver', 'Driver')
    ]
```

---

## ⭐ OrderRating Model

```python
class OrderRating:
    order            # OneToOneField(Order)
    customer         # ForeignKey(Customer)
    shop_rating      # IntegerField(1-5)
    driver_rating    # IntegerField(1-5, null=True)
    food_rating      # IntegerField(1-5)
    comment          # TextField(null=True)
    created_at       # DateTimeField
```

---

## 💳 PaymentMethod Model

```python
class PaymentMethod:
    customer         # ForeignKey(Customer)
    card_type        # CharField - visa/mastercard/mada
    last_four_digits # CharField(4)
    card_holder_name # CharField
    expiry_month     # CharField(2)
    expiry_year      # CharField(4)
    is_default       # BooleanField
    created_at       # DateTimeField
```

---

## 🔔 Notification Model

```python
class Notification:
    # Polymorphic - can belong to any user type
    customer         # ForeignKey(Customer, null=True)
    shop_owner       # ForeignKey(ShopOwner, null=True)
    employee         # ForeignKey(Employee, null=True)
    driver           # ForeignKey(Driver, null=True)
    notification_type# CharField - order/chat/system/promotion
    title            # CharField
    message          # TextField
    data             # JSONField(null=True) - Extra data
    is_read          # BooleanField
    created_at       # DateTimeField
```

---

## 🛒 Cart & CartItem Models

```python
class Cart:
    customer         # ForeignKey(Customer)
    shop_owner       # ForeignKey(ShopOwner)
    created_at       # DateTimeField
    updated_at       # DateTimeField
    
    @property
    def total_items(self):
        return self.items.aggregate(Sum('quantity'))
    
    @property
    def subtotal(self):
        return sum(item.total_price for item in self.items.all())

class CartItem:
    cart             # ForeignKey(Cart)
    product          # ForeignKey(Product)
    quantity         # IntegerField
    notes            # TextField(null=True)
    unit_price       # DecimalField
    created_at       # DateTimeField
    
    @property
    def total_price(self):
        return self.unit_price * self.quantity
```

---

## 🔗 Model Relationships Diagram

```
ShopOwner
    ├── ShopStatus (1:1)
    ├── Customer (1:N)
    ├── Employee (1:N)
    ├── Driver (1:N)
    ├── Category (1:N)
    ├── Product (1:N)
    ├── Order (1:N)
    ├── Invoice (1:N)
    ├── GalleryImage (1:N)
    └── Notification (1:N)

Customer
    ├── CustomerAddress (1:N)
    ├── Order (1:N)
    ├── OrderRating (1:N)
    ├── PaymentMethod (1:N)
    ├── Cart (1:N per shop)
    ├── ChatMessage (1:N)
    └── Notification (1:N)

Order
    ├── OrderRating (1:1)
    └── ChatMessage (1:N)

Cart
    └── CartItem (1:N)

Category
    └── Product (1:N)
```

---

## 📁 Related Files

- `shop/models.py` - Main models
- `user/models.py` - ShopOwner model
- `gallery/models.py` - Gallery models
- `shop/admin.py` - Admin configuration
