import json

from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncWebsocketConsumer
from django.core.serializers.json import DjangoJSONEncoder

from shop.websocket_auth import ensure_socket_account_active

from .store_monitoring import get_store_monitoring_snapshot, store_monitor_group_name


def _json_dumps(payload):
    return json.dumps(payload, cls=DjangoJSONEncoder)


class AdminDesktopStoreMonitoringConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        user = self.scope.get("user")
        user_type = self.scope.get("user_type")
        if not user or user_type != "admin_desktop":
            await self.close(code=4403)
            return
        if not await ensure_socket_account_active(self, refresh=True, accept_if_needed=True):
            return
        if not callable(getattr(user, "has_permission", None)) or not user.has_permission("store_management"):
            await self.close(code=4403)
            return
        self.group_name = store_monitor_group_name()
        await self.channel_layer.group_add(self.group_name, self.channel_name)
        await self.accept()

    async def disconnect(self, close_code):
        if hasattr(self, "group_name"):
            await self.channel_layer.group_discard(self.group_name, self.channel_name)

    async def receive(self, text_data):
        if not await ensure_socket_account_active(self, refresh=True):
            return
        try:
            payload = json.loads(text_data)
        except json.JSONDecodeError:
            await self.send_error("INVALID_JSON", "Invalid JSON payload")
            return

        action = payload.get("action") or payload.get("type")
        request_id = payload.get("request_id")
        if action != "store_monitor.sync":
            await self.send_error("INVALID_ACTION", "Unsupported action", request_id=request_id)
            return
        await self.send_snapshot(request_id=request_id)

    async def send_snapshot(self, request_id=None):
        snapshot = await database_sync_to_async(get_store_monitoring_snapshot)()
        payload = {
            "type": "store_monitor.snapshot",
            "data": snapshot,
        }
        if request_id:
            payload["request_id"] = request_id
        await self.send(text_data=_json_dumps(payload))

    async def send_error(self, code, message, request_id=None):
        payload = {
            "type": "store_monitor.error",
            "data": {
                "code": code,
                "message": message,
            },
        }
        if request_id:
            payload["request_id"] = request_id
        await self.send(text_data=_json_dumps(payload))

    async def store_monitor_event(self, event):
        await self.send(text_data=_json_dumps(event["payload"]))
