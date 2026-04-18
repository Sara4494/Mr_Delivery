from django.urls import re_path

from shop import consumers, driver_chat_consumers


websocket_urlpatterns = [
    re_path(r'ws/driver/(?P<driver_id>\d+)/$', consumers.DriverConsumer.as_asgi()),
    re_path(r'ws/driver-chats/shop/(?P<shop_owner_id>\d+)/$', driver_chat_consumers.DriverChatsShopConsumer.as_asgi()),
    re_path(r'ws/driver-chats/driver/(?P<driver_id>\d+)/$', driver_chat_consumers.DriverChatsDriverConsumer.as_asgi()),
]

