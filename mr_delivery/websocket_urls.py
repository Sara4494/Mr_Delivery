from customer_app.routing import websocket_urlpatterns as customer_ws_urlpatterns
from driver_app.routing import websocket_urlpatterns as driver_ws_urlpatterns
from shop_app.routing import websocket_urlpatterns as shop_ws_urlpatterns
from support_center.routing import websocket_urlpatterns as support_center_ws_urlpatterns


websocket_urlpatterns = [
    *support_center_ws_urlpatterns,
    *shop_ws_urlpatterns,
    *customer_ws_urlpatterns,
    *driver_ws_urlpatterns,
]
