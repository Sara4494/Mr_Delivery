from django.urls import re_path

from shop import consumers, support_center_consumers


websocket_urlpatterns = [
    re_path(r'ws/chat/order/(?P<conversation_id>support_[\w-]+)/$', consumers.SupportChatConsumer.as_asgi()),
    re_path(r'ws/chat/support/(?P<conversation_id>[\w-]+)/$', consumers.SupportChatConsumer.as_asgi()),
    re_path(r'ws/support-center/shop/(?P<shop_owner_id>\d+)/$', support_center_consumers.ShopSupportCenterConsumer.as_asgi()),
    re_path(r'ws/support-center/admin/(?P<admin_user_id>\d+)/$', support_center_consumers.AdminSupportCenterConsumer.as_asgi()),
]

