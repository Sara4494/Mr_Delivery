from django.urls import path, re_path

from shop import views


app_name = 'support_center'

urlpatterns = [
    path('shop/support-chats/', views.shop_support_conversations_view, name='shop_support_conversations'),
    path('customer/support-chats/', views.customer_support_conversations_view, name='customer_support_conversations'),
    re_path(r'^chat/order/(?P<conversation_id>support_[\w-]+)/send-media/$', views.support_chat_media_upload_view, name='chat_order_support_media_upload'),
    path('chat/support/<str:conversation_id>/send-media/', views.support_chat_media_upload_view, name='support_chat_media_upload'),
    path('chat/ticket/<str:ticket_id>/send-media/', views.support_ticket_media_upload_view, name='support_ticket_media_upload'),
]
