from django.urls import re_path

from shop import consumers


websocket_urlpatterns = [
    re_path(r'ws/orders/customer/(?P<customer_id>\d+)/$', consumers.CustomerOrderConsumer.as_asgi()),
    re_path(r'ws/customer/app/(?P<customer_id>\d+)/$', consumers.CustomerOrderConsumer.as_asgi()),
]

