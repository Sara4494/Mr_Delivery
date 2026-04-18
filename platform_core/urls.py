from django.urls import path, re_path

from shop import fcm_views, views


app_name = 'platform_core'

urlpatterns = [
    re_path(r'^app/status/?$', views.app_status_view, name='app_status'),
    re_path(r'^devices/fcm/register/?$', fcm_views.fcm_register_device_view, name='fcm_register_device'),
    re_path(r'^devices/fcm/refresh/?$', fcm_views.fcm_refresh_device_view, name='fcm_refresh_device'),
    re_path(r'^devices/fcm/unregister/?$', fcm_views.fcm_unregister_device_view, name='fcm_unregister_device'),
    path('chat/order/<int:order_id>/send-media/', views.chat_order_media_upload_view, name='chat_order_media_upload'),
]

