from django.urls import path
from . import views

app_name = 'shop'

urlpatterns = [
    # Public shops list (for customers)
    path('shops/', views.public_shops_list_view, name='public_shops_list'),
    path('shops/shop-categories/', views.public_shop_categories_list_view, name='public_shop_categories_list'),
    path('shops/products/by-shop-category/', views.public_products_by_shop_category_view, name='public_products_by_shop_category'),
    path('shops/offers/', views.public_offers_view, name='public_offers'),

    # Shop Status
    path('shop/status/', views.shop_status_view, name='shop_status'),
    path('shop/shop-categories/', views.shop_category_list_view, name='shop_category_list'),
    path('shop/shop-categories/<int:category_id>/', views.shop_category_detail_view, name='shop_category_detail'),
    
    # Customers (Ù„Ù„Ù…Ø­Ù„)
    path('shop/customers/', views.customer_list_view, name='customer_list'),
    path('shop/customers/<int:customer_id>/', views.customer_detail_view, name='customer_detail'),
    
    
    # Unified Staff (employees + drivers)
    path('shop/staff/', views.staff_view, name='staff'),
    path('shop/staff/<str:staff_type>/<int:staff_id>/delete/', views.staff_delete_view, name='staff_delete'),
    path('shop/staff/<str:staff_type>/<int:staff_id>/block/', views.staff_block_view, name='staff_block'),
    
    # Categories (ØªØµÙ†ÙŠÙØ§Øª Ø§Ù„Ù…Ù†ØªØ¬Ø§Øª)
    path('shop/categories/', views.category_list_view, name='category_list'),
    path('shop/categories/<int:category_id>/', views.category_detail_view, name='category_detail'),
    
    # Products (Ù‚Ø§Ø¦Ù…Ø© Ø§Ù„Ù…Ù†ØªØ¬Ø§Øª)
    path('shop/products/', views.product_list_view, name='product_list'),
    path('shop/products/<int:product_id>/', views.product_detail_view, name='product_detail'),
    
    # Orders (Ù„Ù„Ù…Ø­Ù„)
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
    path('driver/invitation/respond/', views.driver_invitation_respond_view, name='driver_invitation_respond'),
    
    # ==================== Customer Auth ====================
    path('customer/register/', views.customer_register_view, name='customer_register'),
    path('customer/login/', views.customer_login_view, name='customer_login'),
    path('customer/profile/', views.customer_profile_view, name='customer_profile'),
    path('customer/select-shop/', views.customer_select_shop_view, name='customer_select_shop'),
    
    # ==================== Customer Orders (Ø·Ù„Ø¨ Ø£ÙˆØ±Ø¯Ø± - Ø§Ù„Ø¨Ù†Ø¯ 1ØŒ 2ØŒ 3ØŒ ...) ====================
    path('customer/orders/', views.customer_orders_list_create_view, name='customer_orders_list_create'),
    path('customer/orders/<int:order_id>/confirm/', views.customer_order_confirm_view, name='customer_order_confirm'),
    path('customer/orders/<int:order_id>/reject/', views.customer_order_reject_view, name='customer_order_reject'),
    
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
    # Ø§Ù„Ø´Ø§Øª ÙŠØªÙ… Ø¹Ø¨Ø± WebSocket ÙÙ‚Ø·:
    # ws://server/ws/chat/order/{order_id}/?token=JWT&chat_type=shop_customer
]
