from django.urls import path
from . import views

app_name = 'shop'

urlpatterns = [
    # Shop Status
    path('shop/status/', views.shop_status_view, name='shop_status'),
    
    # Customers (للمحل)
    path('shop/customers/', views.customer_list_view, name='customer_list'),
    path('shop/customers/<int:customer_id>/', views.customer_detail_view, name='customer_detail'),
    
    # Drivers (للمحل)
    path('shop/drivers/', views.driver_list_view, name='driver_list'),
    path('shop/drivers/<int:driver_id>/', views.driver_detail_view, name='driver_detail'),
    path('shop/drivers/<int:driver_id>/approve/', views.driver_approve_view, name='driver_approve'),
    
    # Employees
    path('shop/employees/', views.employee_list_view, name='employee_list'),
    path('shop/employees/<int:employee_id>/', views.employee_detail_view, name='employee_detail'),
    path('shop/employees/statistics/', views.employee_statistics_view, name='employee_statistics'),
    
    # Categories (تصنيفات المنتجات)
    path('shop/categories/', views.category_list_view, name='category_list'),
    path('shop/categories/<int:category_id>/', views.category_detail_view, name='category_detail'),
    
    # Products (قائمة المنتجات)
    path('shop/products/', views.product_list_view, name='product_list'),
    path('shop/products/<int:product_id>/', views.product_detail_view, name='product_detail'),
    
    # Orders (للمحل)
    path('shop/orders/', views.order_list_view, name='order_list'),
    path('shop/orders/<int:order_id>/', views.order_detail_view, name='order_detail'),
    path('shop/orders/<int:order_id>/rating/', views.order_rating_view, name='order_rating'),
    path('shop/orders/<int:order_id>/track/', views.order_tracking_view, name='order_tracking'),
    
    # Invoices
    path('shop/invoices/', views.invoice_list_view, name='invoice_list'),
    path('shop/invoices/<int:invoice_id>/', views.invoice_detail_view, name='invoice_detail'),
    
    # Dashboard Statistics
    path('shop/dashboard/statistics/', views.shop_dashboard_statistics_view, name='dashboard_statistics'),
    
    # ==================== Login APIs ====================
    path('employee/login/', views.employee_login_view, name='employee_login'),
    path('driver/login/', views.driver_login_view, name='driver_login'),
    
    # ==================== Customer Auth ====================
    path('customer/register/', views.customer_register_view, name='customer_register'),
    path('customer/login/', views.customer_login_view, name='customer_login'),
    path('customer/profile/', views.customer_profile_view, name='customer_profile'),
    
    # ==================== Customer Addresses ====================
    path('customer/addresses/', views.customer_address_list_view, name='customer_address_list'),
    path('customer/addresses/<int:address_id>/', views.customer_address_detail_view, name='customer_address_detail'),
    
    # ==================== Customer Payment Methods ====================
    path('customer/payment-methods/', views.payment_method_list_view, name='payment_method_list'),
    path('customer/payment-methods/<int:method_id>/', views.payment_method_delete_view, name='payment_method_delete'),
    
    # ==================== Order Rating ====================
    path('orders/rate/', views.order_rating_create_view, name='order_rating_create'),
    
    # ==================== Notifications ====================
    path('notifications/', views.notification_list_view, name='notification_list'),
    path('notifications/<int:notification_id>/read/', views.notification_mark_read_view, name='notification_mark_read'),
    path('notifications/read-all/', views.notification_mark_all_read_view, name='notification_mark_all_read'),
    
    # ==================== Cart ====================
    path('cart/<int:shop_id>/', views.cart_view, name='cart_view'),
    path('cart/<int:shop_id>/add/', views.cart_add_item_view, name='cart_add_item'),
    path('cart/<int:shop_id>/items/<int:item_id>/', views.cart_item_view, name='cart_item'),
    path('cart/<int:shop_id>/clear/', views.cart_clear_view, name='cart_clear'),
    
    # ==================== Driver Location ====================
    path('driver/location/', views.driver_location_update_view, name='driver_location_update'),
    
    # ==================== Chat ====================
    # الشات يتم عبر WebSocket فقط:
    # ws://server/ws/chat/order/{order_id}/?token=JWT&chat_type=shop_customer
]
