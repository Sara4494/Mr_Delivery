from django.urls import path, re_path

from shop import views


app_name = 'customer_app'

urlpatterns = [
    path('customer/dashboard-ui/', views.customer_dashboard_ui_view, name='customer_dashboard_ui'),
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
    re_path(r'^shops/gallery/(?P<image_id>\d+)/like/?$', views.public_gallery_like_view, name='public_gallery_like'),
    path('customer/register/', views.customer_register_view, name='customer_register'),
    path('customer/login/', views.customer_login_view, name='customer_login'),
    path('customer/profile/', views.customer_profile_view, name='customer_profile'),
    path('customer/profile/phone/send-otp/', views.customer_profile_phone_send_otp_view, name='customer_profile_phone_send_otp'),
    path('customer/profile/phone/verify-otp/', views.customer_profile_phone_verify_otp_view, name='customer_profile_phone_verify_otp'),
    path('customer/select-shop/', views.customer_select_shop_view, name='customer_select_shop'),
    path('customer/orders/', views.customer_orders_list_create_view, name='customer_orders_list_create'),
    path('customer/orders/<int:order_id>/confirm/', views.customer_order_confirm_view, name='customer_order_confirm'),
    path('customer/orders/<int:order_id>/reject/', views.customer_order_reject_view, name='customer_order_reject'),
    path('customer/addresses/', views.customer_address_list_view, name='customer_address_list'),
    path('customer/addresses/<int:address_id>/', views.customer_address_detail_view, name='customer_address_detail'),
    path('customer/payment-methods/', views.payment_method_list_view, name='payment_method_list'),
    path('customer/payment-methods/<int:method_id>/', views.payment_method_delete_view, name='payment_method_delete'),
    path('orders/rate/', views.order_rating_create_view, name='order_rating_create'),
    path('notifications/', views.notification_list_view, name='notification_list'),
    path('notifications/<int:notification_id>/read/', views.notification_mark_read_view, name='notification_mark_read'),
    path('notifications/read-all/', views.notification_mark_all_read_view, name='notification_mark_all_read'),
    path('reports/reasons/', views.abuse_report_reasons_view, name='abuse_report_reasons'),
    path('reports/', views.abuse_reports_view, name='abuse_reports'),
]

