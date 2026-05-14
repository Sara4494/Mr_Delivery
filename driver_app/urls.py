from django.urls import path, re_path

from shop import driver_chat_views, views


app_name = 'driver_app'

urlpatterns = [
    path('driver/app-version/', views.driver_app_version_view, name='driver_app_version'),
    path('driver/dashboard-ui/', views.driver_dashboard_ui_view, name='driver_dashboard_ui'),
    path('driver/store-chats-ui/', views.driver_store_chats_ui_view, name='driver_store_chats_ui'),
    path('driver/register/', views.driver_register_view, name='driver_register'),
    path('driver/register/send-otp/', views.driver_register_send_otp_view, name='driver_register_send_otp'),
    path('driver/register/verify-otp/', views.driver_register_verify_otp_view, name='driver_register_verify_otp'),
    re_path(r'^driver/login/?$', views.driver_login_view, name='driver_login'),
    path('driver/home/', views.driver_dashboard_view, name='driver_home'),
    path('driver/invitations/', views.driver_invitations_view, name='driver_invitations'),
    path('driver/invitations/<int:invitation_id>/respond/', views.driver_invitation_action_view, name='driver_invitation_action'),
    path('driver/orders/<int:order_id>/accept/', views.driver_order_accept_view, name='driver_order_accept'),
    path('driver/orders/<int:order_id>/reject/', views.driver_order_reject_view, name='driver_order_reject'),
    path('driver/orders/<int:order_id>/deliver/', views.driver_order_deliver_view, name='driver_order_deliver'),
    path('driver/orders/<int:order_id>/', views.driver_order_detail_view, name='driver_order_detail'),
    path('driver/orders/<int:order_id>/transfer/', views.driver_order_transfer_view, name='driver_order_transfer'),
    path('driver/orders/<int:order_id>/chat/', views.driver_order_chat_view, name='driver_order_chat'),
    path('driver/orders/<int:order_id>/chat/open/', views.driver_order_chat_open_view, name='driver_order_chat_open'),
    path('driver/status/', views.driver_status_view, name='driver_status'),
    path('user/profile/', views.driver_profile_view, name='driver_profile'),
    path('user/profile/phone/send-otp/', views.driver_profile_phone_send_otp_view, name='driver_profile_phone_send_otp'),
    path('user/profile/phone/verify-otp/', views.driver_profile_phone_verify_otp_view, name='driver_profile_phone_verify_otp'),
    path('driver/password/change/', views.driver_change_password_view, name='driver_password_change'),
    path('driver/password/send-otp/', views.driver_password_send_otp_view, name='driver_password_send_otp'),
    path('driver/password/reset/', views.driver_password_reset_view, name='driver_password_reset'),
    path('driver/logout/', views.driver_logout_view, name='driver_logout'),
    path('driver/driver-chats/voice/upload/', driver_chat_views.driver_chat_driver_voice_upload_view, name='driver_chat_driver_voice_upload'),
    path('driver/driver-chats/image/upload/', driver_chat_views.driver_chat_driver_image_upload_view, name='driver_chat_driver_image_upload'),
]
