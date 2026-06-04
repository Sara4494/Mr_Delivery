import json

from asgiref.sync import sync_to_async
from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncWebsocketConsumer
from django.core.serializers.json import DjangoJSONEncoder
from django.db import transaction
from django.utils import timezone

from user.authentication import get_socket_session_group_name
from user.utils import resolve_base_url

from .models import Notification, ShopOwner
from .realtime.websocket_utils import (
    broadcast_shop_notifications_counts,
    get_shop_notifications_counts,
    get_shop_notifications_snapshot,
)
from .websocket_auth import ensure_socket_account_active


SHOP_NOTIFICATION_EXCLUDED_TYPES = {'chat_message', 'chat'}


def _json_dumps(payload):
    return json.dumps(payload, cls=DjangoJSONEncoder)


def _query_param(scope, key, default=None):
    query_string = scope.get('query_string', b'').decode('utf-8')
    if f'{key}=' not in query_string:
        return default
    return query_string.split(f'{key}=')[-1].split('&')[0] or default


def _payload_value(payload, key, default=None):
    if key in payload:
        return payload.get(key)
    nested = payload.get('data')
    if isinstance(nested, dict) and key in nested:
        return nested.get(key)
    return default


class ShopNotificationsConsumer(AsyncWebsocketConsumer):
    async def send_payload(self, payload):
        await self.send(text_data=_json_dumps(payload))

    async def connect(self):
        self.lang = _query_param(self.scope, 'lang', 'ar')
        self.base_url = resolve_base_url(scope=self.scope)
        self.joined_groups = set()
        self.shop_owner_id = int(self.scope['url_route']['kwargs']['shop_owner_id'])

        user = self.scope.get('user')
        user_type = self.scope.get('user_type')
        if not user or not user_type:
            await self.close(code=4401)
            return
        if user_type != 'shop_owner':
            await self.close(code=4403)
            return
        if getattr(user, 'id', None) != self.shop_owner_id:
            await self.close(code=4403)
            return

        self.user = user
        self.scope['user_type'] = user_type
        if not await ensure_socket_account_active(self, refresh=True, accept_if_needed=True):
            return

        self.session_group = get_socket_session_group_name(user_type, user.id)
        self.notification_group = f'shop_notifications_{self.shop_owner_id}'
        self.joined_groups.add(self.session_group)
        self.joined_groups.add(self.notification_group)
        await self.channel_layer.group_add(self.session_group, self.channel_name)
        await self.channel_layer.group_add(self.notification_group, self.channel_name)
        await self.accept()
        await self.send_initial_snapshot()

    async def disconnect(self, close_code):
        for group_name in list(getattr(self, 'joined_groups', set())):
            await self.channel_layer.group_discard(group_name, self.channel_name)

    async def receive(self, text_data):
        if not await ensure_socket_account_active(self, refresh=True):
            return
        try:
            payload = json.loads(text_data)
        except json.JSONDecodeError:
            await self.send_error('INVALID_JSON', 'Invalid JSON payload.')
            return

        action = str(payload.get('action') or payload.get('type') or '').strip()
        handler = getattr(self, f'handle_{action.replace(".", "_")}', None)
        if not handler:
            await self.send_error('INVALID_ACTION', 'Unsupported notification action.')
            return

        try:
            await handler(payload)
        except ValueError as exc:
            await self.send_error('INVALID_DATA', str(exc))
        except Exception as exc:
            await self.send_error('UNEXPECTED_ERROR', str(exc))

    async def send_error(self, code, message):
        await self.send_payload(
            {
                'type': 'error',
                'data': {
                    'code': code,
                    'message': message,
                },
            }
        )

    async def send_initial_snapshot(self):
        counts = await self._get_counts()
        await self.send_payload(
            {
                'type': 'notifications.initial',
                'data': {
                    'notifications': [],
                    'unread_count': counts['unread_count'],
                },
            }
        )

    async def handle_notifications_fetch(self, payload):
        page = int(_payload_value(payload, 'page', 1) or 1)
        limit = int(_payload_value(payload, 'limit', 50) or 50)
        snapshot = await self._get_snapshot(page=page, limit=limit)
        await self.send_payload(
            {
                'type': 'notifications.list',
                'data': {
                    'notifications': snapshot['notifications'],
                    'unread_count': snapshot['unread_count'],
                },
            }
        )

    async def handle_notification_mark_read(self, payload):
        notification_id = _payload_value(payload, 'notification_id')
        if notification_id in (None, ''):
            raise ValueError('notification_id is required.')
        result = await self._mark_notification_read(int(notification_id))
        if not result:
            await self.send_error('NOTIFICATION_NOT_FOUND', 'Notification not found.')
            return
        await self.send_payload(
            {
                'type': 'notification.read',
                'data': {
                    'notification_id': result['notification_id'],
                    'is_read': True,
                    'unread_count': result['unread_count'],
                },
            }
        )
        await self._broadcast_counts(result['unread_count'], result['total_count'])

    async def handle_notifications_mark_all_read(self, payload):
        result = await self._mark_all_notifications_read()
        await self.send_payload(
            {
                'type': 'notifications.all_read',
                'data': {
                    'unread_count': result['unread_count'],
                },
            }
        )
        await self._broadcast_counts(result['unread_count'], result['total_count'])

    async def notification_created(self, event):
        notification = await self._get_notification(event.get('notification_id'))
        if not notification:
            return
        payload = await database_sync_to_async(self._serialize_notification)(notification)
        await self.send_payload(
            {
                'type': 'notification.created',
                'data': payload,
                'unread_count': int(event.get('unread_count') or 0),
            }
        )

    async def notifications_counts(self, event):
        await self.send_payload(
            {
                'type': 'notifications.counts',
                'data': {
                    'unread_count': int(event.get('unread_count') or 0),
                    'total_count': int(event.get('total_count') or 0),
                },
            }
        )

    async def auth_session_revoked(self, event):
        current_session_key = str((self.scope or {}).get('auth_session_key') or '').strip()
        active_session_key = str(event.get('session_key') or '').strip()
        if current_session_key and active_session_key and current_session_key == active_session_key:
            return
        await self.send_payload(
            {
                'type': 'auth.session_revoked',
                'data': {
                    'message': 'Session ended because this account signed in on another device.',
                },
            }
        )
        await self.close(code=4401)

    async def _get_snapshot(self, *, page=1, limit=50):
        return await database_sync_to_async(get_shop_notifications_snapshot)(
            self.user,
            page=page,
            limit=limit,
            lang=self.lang,
        )

    async def _get_counts(self):
        return await database_sync_to_async(get_shop_notifications_counts)(self.user)

    async def _get_notification(self, notification_id):
        if notification_id in (None, ''):
            return None
        return await database_sync_to_async(self._get_notification_sync)(int(notification_id))

    def _get_notification_sync(self, notification_id):
        return (
            Notification.objects.filter(
                id=notification_id,
                shop_owner=self.user,
            )
            .exclude(notification_type__in=SHOP_NOTIFICATION_EXCLUDED_TYPES)
            .first()
        )

    def _serialize_notification(self, notification):
        from .realtime.websocket_utils import serialize_shop_notification

        return serialize_shop_notification(notification, lang=self.lang)

    async def _mark_notification_read(self, notification_id):
        return await database_sync_to_async(self._mark_notification_read_sync)(notification_id)

    def _mark_notification_read_sync(self, notification_id):
        with transaction.atomic():
            notification = (
                Notification.objects.select_for_update()
                .filter(
                    id=notification_id,
                    shop_owner=self.user,
                )
                .exclude(notification_type__in=SHOP_NOTIFICATION_EXCLUDED_TYPES)
                .first()
            )
            if not notification:
                return None
            if not notification.is_read:
                notification.is_read = True
                notification.save(update_fields=['is_read'])
            counts = get_shop_notifications_counts(self.user)
            return {
                'notification_id': int(notification.id),
                'unread_count': counts['unread_count'],
                'total_count': counts['total_count'],
            }

    async def _mark_all_notifications_read(self):
        return await database_sync_to_async(self._mark_all_notifications_read_sync)()

    def _mark_all_notifications_read_sync(self):
        with transaction.atomic():
            Notification.objects.filter(
                shop_owner=self.user,
                is_read=False,
            ).exclude(notification_type__in=SHOP_NOTIFICATION_EXCLUDED_TYPES).update(is_read=True)
            counts = get_shop_notifications_counts(self.user)
            return {
                'unread_count': counts['unread_count'],
                'total_count': counts['total_count'],
            }

    async def _broadcast_counts(self, unread_count, total_count):
        await sync_to_async(broadcast_shop_notifications_counts)(
            self.user,
            unread_count=unread_count,
            total_count=total_count,
        )
