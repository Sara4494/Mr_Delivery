from django.urls import re_path

from . import consumers
from . import driver_chat_consumers

websocket_urlpatterns = [
    # ==================== Chat WebSocket ====================
    # الشات بين جميع الأطراف (shop_owner, employee, driver, customer)
    # Support chats can also reuse the same "order chat" path with a support_* identifier:
    # ws://server/ws/chat/order/support_12/?token=JWT&chat_type=support_customer
    re_path(r'ws/chat/order/(?P<conversation_id>support_[\w-]+)/$', consumers.SupportChatConsumer.as_asgi()),
    # ws://server/ws/chat/order/{order_id}/?token=JWT&chat_type=shop_customer
    re_path(r'ws/chat/order/(?P<order_id>\d+)/$', consumers.ChatConsumer.as_asgi()),
    # ws://server/ws/chat/support/{conversation_id}/?token=JWT
    re_path(r'ws/chat/support/(?P<conversation_id>[\w-]+)/$', consumers.SupportChatConsumer.as_asgi()),
    
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

    # ==================== Driver Chats ====================
    # ws://server/ws/driver-chats/shop/{shop_owner_id}/?token=JWT&lang=ar
    re_path(r'ws/driver-chats/shop/(?P<shop_owner_id>\d+)/$', driver_chat_consumers.DriverChatsShopConsumer.as_asgi()),
    # ws://server/ws/driver-chats/driver/{driver_id}/?token=JWT&lang=ar
    re_path(r'ws/driver-chats/driver/(?P<driver_id>\d+)/$', driver_chat_consumers.DriverChatsDriverConsumer.as_asgi()),
]
