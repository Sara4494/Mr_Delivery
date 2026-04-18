from django.urls import re_path

from shop import consumers


websocket_urlpatterns = [
    re_path(r'ws/chat/order/(?P<order_id>\d+)/$', consumers.ChatConsumer.as_asgi()),
    re_path(r'ws/orders/shop/(?P<shop_owner_id>\d+)/$', consumers.OrderConsumer.as_asgi()),
]

