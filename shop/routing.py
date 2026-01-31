from django.urls import re_path
from . import consumers

websocket_urlpatterns = [
    # ==================== Chat WebSocket ====================
    # الشات بين جميع الأطراف (shop_owner, employee, driver, customer)
    # ws://server/ws/chat/order/{order_id}/?token=JWT&chat_type=shop_customer
    re_path(r'ws/chat/order/(?P<order_id>\d+)/$', consumers.ChatConsumer.as_asgi()),
    
    # ==================== Orders WebSocket ====================
    # تحديثات الطلبات للمحل (shop_owner و employee)
    # ws://server/ws/orders/shop/{shop_owner_id}/?token=JWT
    re_path(r'ws/orders/shop/(?P<shop_owner_id>\d+)/$', consumers.OrderConsumer.as_asgi()),
    
    # تحديثات الطلبات للعميل
    # ws://server/ws/orders/customer/{customer_id}/?token=JWT
    re_path(r'ws/orders/customer/(?P<customer_id>\d+)/$', consumers.CustomerOrderConsumer.as_asgi()),
    
    # ==================== Driver WebSocket ====================
    # قناة السائق (طلبات جديدة، رسائل، تحديث الموقع)
    # ws://server/ws/driver/{driver_id}/?token=JWT
    re_path(r'ws/driver/(?P<driver_id>\d+)/$', consumers.DriverConsumer.as_asgi()),
]
