from django.urls import path, re_path
from . import views

app_name = 'shop'

urlpatterns = [
    path('shop/dashboard-ui/', views.shop_dashboard_ui_view, name='shop_dashboard_ui'),
    path('driver/dashboard-ui/', views.driver_dashboard_ui_view, name='driver_dashboard_ui'),
    path('customer/dashboard-ui/', views.customer_dashboard_ui_view, name='customer_dashboard_ui'),
    # Public shops list (for customers)
    path('shops/', views.public_shops_list_view, name='public_shops_list'),
    path('shops/shop-categories/', views.public_shop_categories_list_view, name='public_shop_categories_list'),
    path('shops/portfolio/', views.public_portfolio_feed_view, name='public_portfolio_feed'),
    path('shops/offers/', views.public_offers_view, name='public_offers'),
    re_path(r'^shops/offers/(?P<offer_id>\d+)/like/?$', views.public_offer_like_view, name='public_offer_like'),
    path('shops/<int:shop_id>/rating/', views.shop_rating_create_view, name='shop_rating_create'),
    path('shops/<int:shop_id>/profile/', views.public_shop_profile_view, name='public_shop_profile'),
    path('shops/<int:shop_id>/posts/', views.public_shop_posts_view, name='public_shop_posts'),
    path('shops/<int:shop_id>/schedule/', views.public_shop_schedule_view, name='public_shop_schedule'),
    path('shops/<int:shop_id>/gallery/', views.public_shop_gallery_view, name='public_shop_gallery'),
    # Support both with/without trailing slash to avoid APPEND_SLASH POST runtime errors.
    re_path(r'^shops/gallery/(?P<image_id>\d+)/like/?$', views.public_gallery_like_view, name='public_gallery_like'),

    # Shop Status
    path('shop/status/', views.shop_status_view, name='shop_status'),
    path('shop/schedule/', views.shop_work_schedule_view, name='shop_work_schedule'),
    path('shop/shop-categories/', views.shop_category_list_view, name='shop_category_list'),
    path('shop/shop-categories/<int:category_id>/', views.shop_category_detail_view, name='shop_category_detail'),
    
    # Customers (للمحل)
    path('shop/customers/', views.customer_list_view, name='customer_list'),
    path('shop/customers/<int:customer_id>/', views.customer_detail_view, name='customer_detail'),
    
    
    # Unified Staff (employees + drivers)
    path('shop/staff/', views.staff_view, name='staff'),
    path('shop/staff/<str:staff_type>/<int:staff_id>/delete/', views.staff_delete_view, name='staff_delete'),
    path('shop/staff/<str:staff_type>/<int:staff_id>/block/', views.staff_block_view, name='staff_block'),
    
    # Categories (تصنيفات المنتجات)
    path('shop/categories/', views.category_list_view, name='category_list'),
    path('shop/categories/<int:category_id>/', views.category_detail_view, name='category_detail'),
    path('shop/offers/', views.offer_list_view, name='offer_list'),
    path('shop/offers/<int:offer_id>/', views.offer_detail_view, name='offer_detail'),
    
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
    path('shop/dashboard/summary/', views.shop_dashboard_summary_view, name='dashboard_summary'),
    
    # ==================== Login APIs ====================
    path('employee/login/', views.employee_login_view, name='employee_login'),
    path('driver/register/', views.driver_register_view, name='driver_register'),
    path('driver/register/send-otp/', views.driver_register_send_otp_view, name='driver_register_send_otp'),
    path('driver/register/verify-otp/', views.driver_register_verify_otp_view, name='driver_register_verify_otp'),
    path('driver/login/', views.driver_login_view, name='driver_login'),
    path('driver/dashboard/', views.driver_dashboard_view, name='driver_dashboard'),
    path('driver/invitations/', views.driver_invitations_view, name='driver_invitations'),
    path('driver/invitations/<int:invitation_id>/respond/', views.driver_invitation_action_view, name='driver_invitation_action'),
    path('driver/orders/', views.driver_orders_view, name='driver_orders'),
    path('driver/orders/transfer-reasons/', views.driver_order_transfer_reasons_view, name='driver_order_transfer_reasons'),
    path('driver/orders/<int:order_id>/', views.driver_order_detail_view, name='driver_order_detail'),
    path('driver/orders/<int:order_id>/transfer/', views.driver_order_transfer_view, name='driver_order_transfer'),
    path('driver/orders/<int:order_id>/chat/', views.driver_order_chat_view, name='driver_order_chat'),
    path('driver/status/', views.driver_status_view, name='driver_status'),
    path('driver/password/send-otp/', views.driver_password_send_otp_view, name='driver_password_send_otp'),
    path('driver/password/reset/', views.driver_password_reset_view, name='driver_password_reset'),
    path('driver/invitation/respond/', views.driver_invitation_respond_view, name='driver_invitation_respond'),
    
    # ==================== Customer Auth ====================
    path('customer/register/', views.customer_register_view, name='customer_register'),
    path('customer/login/', views.customer_login_view, name='customer_login'),
    path('customer/profile/', views.customer_profile_view, name='customer_profile'),
    path('customer/profile/phone/send-otp/', views.customer_profile_phone_send_otp_view, name='customer_profile_phone_send_otp'),
    path('customer/profile/phone/verify-otp/', views.customer_profile_phone_verify_otp_view, name='customer_profile_phone_verify_otp'),
    path('customer/select-shop/', views.customer_select_shop_view, name='customer_select_shop'),
    
    # ==================== Customer Orders (طلب أوردر - البند 1، 2، 3، ...) ====================
    path('customer/orders/', views.customer_orders_list_create_view, name='customer_orders_list_create'),
    path('customer/shops-conversations/', views.customer_shops_conversations_view, name='customer_shops_conversations'),
    path('customer/orders/on-way/', views.customer_on_way_orders_view, name='customer_orders_on_way'),
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
    
    # ==================== Driver Location ====================
    path('driver/location/', views.driver_location_update_view, name='driver_location_update'),
    
    # ==================== Chat ====================
    path('chat/order/<int:order_id>/send-media/', views.chat_order_media_upload_view, name='chat_order_media_upload'),
    # الشات يتم عبر WebSocket فقط:
    # ws://server/ws/chat/order/{order_id}/?token=JWT&chat_type=shop_customer
]
