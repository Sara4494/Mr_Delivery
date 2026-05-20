from django.urls import re_path

from .consumers import AdminDesktopStoreMonitoringConsumer


websocket_urlpatterns = [
    re_path(
        r"ws/admin-desktop/store-monitoring/$",
        AdminDesktopStoreMonitoringConsumer.as_asgi(),
    ),
]
