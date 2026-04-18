from django.urls import path

from shop import driver_chat_views, views as shop_views
from user import views as user_views


app_name = 'shop_app'

urlpatterns = [
    path('shop/login/', user_views.ShopOwnerTokenObtainPairView.as_view(), name='shop_login'),
    path('shop/token/refresh/', user_views.ShopOwnerTokenRefreshView.as_view(), name='token_refresh'),
    path('shop/dashboard-ui/', shop_views.shop_dashboard_ui_view, name='shop_dashboard_ui'),
    path('shop/driver-chats/ui/', shop_views.driver_chats_ui_view, name='shop_driver_chats_ui'),
    path('shop/status/', shop_views.shop_status_view, name='shop_status'),
    path('shop/schedule/', shop_views.shop_work_schedule_view, name='shop_work_schedule'),
    path('shop/shop-categories/', shop_views.shop_category_list_view, name='shop_category_list'),
    path('shop/shop-categories/<int:category_id>/', shop_views.shop_category_detail_view, name='shop_category_detail'),
    path('shop/customers/', shop_views.customer_list_view, name='customer_list'),
    path('shop/customers/<int:customer_id>/', shop_views.customer_detail_view, name='customer_detail'),
    path('shop/staff/', shop_views.staff_view, name='staff'),
    path('shop/staff/<str:staff_type>/<int:staff_id>/delete/', shop_views.staff_delete_view, name='staff_delete'),
    path('shop/staff/<str:staff_type>/<int:staff_id>/block/', shop_views.staff_block_view, name='staff_block'),
    path('shop/categories/', shop_views.category_list_view, name='category_list'),
    path('shop/categories/<int:category_id>/', shop_views.category_detail_view, name='category_detail'),
    path('shop/offers/', shop_views.offer_list_view, name='offer_list'),
    path('shop/offers/<int:offer_id>/', shop_views.offer_detail_view, name='offer_detail'),
    path('shop/orders/', shop_views.order_list_view, name='order_list'),
    path('shop/orders/<int:order_id>/', shop_views.order_detail_view, name='order_detail'),
    path('shop/orders/<int:order_id>/rating/', shop_views.order_rating_view, name='order_rating'),
    path('shop/orders/<int:order_id>/track/', shop_views.order_tracking_view, name='order_tracking'),
    path('shop/invoices/', shop_views.invoice_list_view, name='invoice_list'),
    path('shop/invoices/<int:invoice_id>/', shop_views.invoice_detail_view, name='invoice_detail'),
    path('shop/driver-chats/conversations/', driver_chat_views.driver_chat_conversations_view, name='driver_chat_conversations'),
    path('shop/driver-chats/conversations/<str:conversation_id>/messages/', driver_chat_views.driver_chat_messages_view, name='driver_chat_messages'),
    path('shop/driver-chats/conversations/<str:conversation_id>/orders/', driver_chat_views.driver_chat_orders_view, name='driver_chat_orders'),
    path('shop/drivers/available-for-transfer/', driver_chat_views.driver_chat_available_transfer_drivers_view, name='driver_chat_available_transfer_drivers'),
    path('shop/driver-chats/voice/upload-url/', driver_chat_views.driver_chat_voice_upload_url_view, name='driver_chat_voice_upload_url'),
    path('shop/driver-chats/voice/upload/', driver_chat_views.driver_chat_voice_upload_view, name='driver_chat_voice_upload'),
    path('shop/driver-chats/image/upload/', driver_chat_views.driver_chat_image_upload_view, name='driver_chat_image_upload'),
    path('shop/driver-chats/mark-read/', driver_chat_views.driver_chat_mark_read_view, name='driver_chat_mark_read'),
    path('shop/driver-chats/resync/', driver_chat_views.driver_chat_resync_view, name='driver_chat_resync'),
    path('shop/driver-chats/calls/<str:call_id>/', driver_chat_views.driver_chat_call_detail_view, name='driver_chat_call_detail'),
    path('shop/dashboard/statistics/', shop_views.shop_dashboard_statistics_view, name='dashboard_statistics'),
    path('shop/dashboard/summary/', shop_views.shop_dashboard_summary_view, name='dashboard_summary'),
    path('employee/login/', shop_views.employee_login_view, name='employee_login'),
]

