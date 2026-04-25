import json

from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncWebsocketConsumer
from django.core.serializers.json import DjangoJSONEncoder
from django.utils import timezone

from user.utils import resolve_base_url

from ..models import ShopSupportTicket
from ..realtime.presence import format_utc_iso8601
from ..websocket_auth import ensure_socket_account_active
from .service import (
    assign_ticket_admin,
    broadcast_ticket_created,
    broadcast_ticket_message,
    broadcast_ticket_typing,
    broadcast_ticket_updated,
    create_shop_support_ticket,
    get_admin_support_snapshot,
    get_shop_support_snapshot,
    get_ticket_by_public_id,
    mark_ticket_read,
    send_ticket_message,
    serialize_ticket_thread,
    support_center_admin_group,
    support_center_shop_group,
    support_center_ticket_group,
    update_ticket_status,
)


def _json_dumps(payload):
    return json.dumps(payload, cls=DjangoJSONEncoder)


def _query_param(scope, key, default=None):
    query_string = scope.get('query_string', b'').decode('utf-8')
    if f'{key}=' not in query_string:
        return default
    return query_string.split(f'{key}=')[-1].split('&')[0] or default


class BaseSupportCenterConsumer(AsyncWebsocketConsumer):
    actor_type = None

    async def send_payload(self, payload):
        await self.send(text_data=_json_dumps(payload))

    async def send_ack(self, request_id, action, data=None):
        await self.send_payload(
            {
                'type': 'support.ack',
                'request_id': request_id,
                'action': action,
                'success': True,
                'data': data or {},
                'sent_at': format_utc_iso8601(timezone.now()),
            }
        )

    async def send_error(self, code, message, request_id=None):
        payload = {
            'type': 'support.error',
            'success': False,
            'data': {
                'code': code,
                'message': message,
            },
            'sent_at': format_utc_iso8601(timezone.now()),
        }
        if request_id:
            payload['request_id'] = request_id
        await self.send_payload(payload)

    async def support_center_event(self, event):
        await self.send_payload(event['payload'])

    async def receive(self, text_data):
        if not await ensure_socket_account_active(self, refresh=True):
            return
        try:
            payload = json.loads(text_data)
        except json.JSONDecodeError:
            await self.send_error('INVALID_JSON', 'تنسيق البيانات غير صحيح')
            return

        action = payload.get('action') or payload.get('type')
        request_id = payload.get('request_id')
        handler = getattr(self, f"handle_{str(action or '').replace('.', '_')}", None)
        if not handler:
            await self.send_error('INVALID_ACTION', 'الأكشن غير مدعوم', request_id=request_id)
            return

        try:
            await handler(payload, request_id=request_id)
        except ValueError as exc:
            await self.send_error('INVALID_DATA', str(exc), request_id=request_id)
        except Exception as exc:
            await self.send_error('UNEXPECTED_ERROR', str(exc), request_id=request_id)

    async def handle_support_ping(self, data, request_id=None):
        await self.send_payload(
            {
                'type': 'support.pong',
                'request_id': request_id,
                'success': True,
                'data': {},
                'sent_at': format_utc_iso8601(timezone.now()),
            }
        )

    async def handle_support_sync(self, data, request_id=None):
        await self.send_snapshot()
        await self.send_ack(request_id, 'support.sync')

    async def handle_support_ticket_subscribe(self, data, request_id=None):
        ticket = await self._require_ticket(data.get('ticket_id'), request_id=request_id)
        if not ticket:
            return
        await self.channel_layer.group_add(support_center_ticket_group(ticket.public_id), self.channel_name)
        self.ticket_groups.add(ticket.public_id)
        await self.send_payload(
            {
                'type': 'support.ticket.thread',
                'data': await self._serialize_ticket_thread(ticket),
                'sent_at': format_utc_iso8601(timezone.now()),
            }
        )
        await self.send_ack(request_id, 'support.ticket.subscribe', data={'ticket_id': ticket.public_id})

    async def handle_support_ticket_mark_read(self, data, request_id=None):
        ticket = await self._require_ticket(data.get('ticket_id'), request_id=request_id)
        if not ticket:
            return
        count = await self._mark_ticket_read(ticket)
        refreshed = await self._require_ticket(ticket.public_id, request_id=request_id)
        if refreshed:
            await self._broadcast_ticket_updated(refreshed)
        await self.send_ack(
            request_id,
            'support.ticket.mark_read',
            data={'ticket_id': ticket.public_id, 'count': count},
        )

    async def handle_support_ticket_typing(self, data, request_id=None):
        ticket = await self._require_ticket(data.get('ticket_id'), request_id=request_id)
        if not ticket:
            return
        actor_name = await self._actor_name()
        await self._broadcast_ticket_typing(ticket, actor_name, bool(data.get('is_typing')))
        await self.send_ack(request_id, 'support.ticket.typing', data={'ticket_id': ticket.public_id})

    async def handle_support_ticket_send_message(self, data, request_id=None):
        ticket = await self._require_ticket(data.get('ticket_id'), request_id=request_id)
        if not ticket:
            return

        message_type = str(data.get('message_type') or 'text').strip().lower()
        content = str(data.get('content') or '').strip() or None
        image_url = str(data.get('image_url') or '').strip() or None
        audio_url = str(data.get('audio_url') or '').strip() or None

        if message_type not in {'text', 'image', 'audio', 'location'}:
            await self.send_error('INVALID_MESSAGE_TYPE', 'نوع الرسالة غير مدعوم', request_id=request_id)
            return
        if message_type == 'text' and not content:
            await self.send_error('CONTENT_REQUIRED', 'محتوى الرسالة مطلوب', request_id=request_id)
            return
        if message_type == 'image' and not image_url:
            await self.send_error('IMAGE_URL_REQUIRED', 'رابط الصورة مطلوب', request_id=request_id)
            return
        if message_type == 'audio' and not audio_url:
            await self.send_error('AUDIO_URL_REQUIRED', 'رابط الصوت مطلوب', request_id=request_id)
            return
        if message_type == 'location' and (data.get('latitude') is None or data.get('longitude') is None):
            await self.send_error('LOCATION_REQUIRED', 'إحداثيات الموقع مطلوبة', request_id=request_id)
            return

        message = await self._send_ticket_message(
            ticket=ticket,
            message_type=message_type,
            content=content,
            image_url=image_url,
            audio_url=audio_url,
            latitude=data.get('latitude'),
            longitude=data.get('longitude'),
            metadata=data.get('metadata') or {},
        )
        await self._broadcast_ticket_message(message)
        await self.send_ack(
            request_id,
            'support.ticket.send_message',
            data={'ticket_id': ticket.public_id, 'message_id': message.id},
        )

    async def _send_ticket_message(self, **kwargs):
        return await database_sync_to_async(send_ticket_message)(
            actor_type=self.actor_type,
            actor=self.scope.get('user'),
            request=None,
            scope=self.scope,
            base_url=self.base_url,
            lang=self.lang,
            **kwargs,
        )

    async def _mark_ticket_read(self, ticket):
        return await database_sync_to_async(mark_ticket_read)(ticket, self.actor_type)

    async def _serialize_ticket_thread(self, ticket):
        return await database_sync_to_async(serialize_ticket_thread)(
            ticket,
            scope=self.scope,
            base_url=self.base_url,
            lang=self.lang,
        )

    async def _broadcast_ticket_created(self, ticket):
        await database_sync_to_async(broadcast_ticket_created)(
            ticket,
            scope=self.scope,
            base_url=self.base_url,
            lang=self.lang,
        )

    async def _broadcast_ticket_updated(self, ticket):
        await database_sync_to_async(broadcast_ticket_updated)(
            ticket,
            scope=self.scope,
            base_url=self.base_url,
            lang=self.lang,
        )

    async def _broadcast_ticket_message(self, message):
        await database_sync_to_async(broadcast_ticket_message)(
            message,
            scope=self.scope,
            base_url=self.base_url,
            lang=self.lang,
        )

    async def _broadcast_ticket_typing(self, ticket, actor_name, is_typing):
        await database_sync_to_async(broadcast_ticket_typing)(
            ticket,
            actor_type=self.actor_type,
            actor_name=actor_name,
            is_typing=is_typing,
        )

    async def _require_ticket(self, ticket_id, request_id=None):
        ticket = await database_sync_to_async(get_ticket_by_public_id)(ticket_id)
        if not ticket:
            await self.send_error('TICKET_NOT_FOUND', 'التذكرة غير موجودة', request_id=request_id)
            return None
        if not await self._can_access_ticket(ticket):
            await self.send_error('TICKET_ACCESS_DENIED', 'ليس لديك صلاحية لهذه التذكرة', request_id=request_id)
            return None
        return ticket

    async def _actor_name(self):
        return await database_sync_to_async(self._actor_name_sync)()

    def _actor_name_sync(self):
        user = self.scope.get('user')
        if self.actor_type == 'shop_owner':
            return getattr(user, 'owner_name', 'المحل')
        if self.actor_type == 'employee':
            return getattr(user, 'name', 'موظف المحل')
        return getattr(user, 'name', 'الدعم الفني')

    async def disconnect(self, close_code):
        for group_name in list(getattr(self, 'joined_groups', set())):
            await self.channel_layer.group_discard(group_name, self.channel_name)
        for ticket_id in list(getattr(self, 'ticket_groups', set())):
            await self.channel_layer.group_discard(support_center_ticket_group(ticket_id), self.channel_name)


class ShopSupportCenterConsumer(BaseSupportCenterConsumer):
    async def connect(self):
        self.lang = _query_param(self.scope, 'lang', 'ar')
        self.base_url = resolve_base_url(scope=self.scope)
        self.ticket_groups = set()
        self.joined_groups = set()
        self.shop_owner_id = int(self.scope['url_route']['kwargs']['shop_owner_id'])
        user = self.scope.get('user')
        user_type = self.scope.get('user_type')
        if not user or user_type not in {'shop_owner', 'employee'}:
            await self.close(code=4403)
            return
        self.scope['user_type'] = user_type
        if not await ensure_socket_account_active(self, refresh=True, accept_if_needed=True):
            return
        if user_type == 'shop_owner' and user.id != self.shop_owner_id:
            await self.close(code=4403)
            return
        if user_type == 'employee' and getattr(user, 'shop_owner_id', None) != self.shop_owner_id:
            await self.close(code=4403)
            return

        self.user = user
        self.actor_type = user_type
        self.overview_group = support_center_shop_group(self.shop_owner_id)
        self.joined_groups.add(self.overview_group)
        await self.channel_layer.group_add(self.overview_group, self.channel_name)
        await self.accept()
        await self.send_payload(
            {
                'type': 'support.connection',
                'data': {
                    'actor_type': self.actor_type,
                    'shop_owner_id': self.shop_owner_id,
                    'chat_type': 'shop_admin_support',
                },
                'sent_at': format_utc_iso8601(timezone.now()),
            }
        )
        await self.send_snapshot()

    async def send_snapshot(self):
        snapshot = await database_sync_to_async(get_shop_support_snapshot)(
            self.shop_owner_id,
            scope=self.scope,
            base_url=self.base_url,
            lang=self.lang,
        )
        await self.send_payload(
            {
                'type': 'support.snapshot',
                'data': {
                    'actor_type': self.actor_type,
                    'scope': 'shop',
                    **snapshot,
                },
                'sent_at': format_utc_iso8601(timezone.now()),
            }
        )

    async def handle_support_ticket_create(self, data, request_id=None):
        subject = str(data.get('subject') or '').strip()
        priority = str(data.get('priority') or 'medium').strip().lower()
        initial_message = str(data.get('initial_message') or '').strip()
        if not subject:
            await self.send_error('SUBJECT_REQUIRED', 'عنوان المشكلة مطلوب', request_id=request_id)
            return
        if priority not in dict(ShopSupportTicket.PRIORITY_CHOICES):
            await self.send_error('INVALID_PRIORITY', 'الأولوية غير صحيحة', request_id=request_id)
            return

        ticket, message = await database_sync_to_async(create_shop_support_ticket)(
            shop_owner=self.scope.get('user') if self.actor_type == 'shop_owner' else self.scope['user'].shop_owner_id,
            created_by_employee=self.scope.get('user') if self.actor_type == 'employee' else None,
            subject=subject,
            priority=priority,
            initial_message=initial_message or None,
            scope=self.scope,
            base_url=self.base_url,
            lang=self.lang,
        )
        await self._broadcast_ticket_created(ticket)
        if message:
            await self._broadcast_ticket_message(message)
        await self.channel_layer.group_add(support_center_ticket_group(ticket.public_id), self.channel_name)
        self.ticket_groups.add(ticket.public_id)
        await self.send_payload(
            {
                'type': 'support.ticket.thread',
                'data': await self._serialize_ticket_thread(ticket),
                'sent_at': format_utc_iso8601(timezone.now()),
            }
        )
        await self.send_ack(
            request_id,
            'support.ticket.create',
            data={'ticket_id': ticket.public_id},
        )

    async def _can_access_ticket(self, ticket):
        return ticket.shop_owner_id == self.shop_owner_id


class AdminSupportCenterConsumer(BaseSupportCenterConsumer):
    async def connect(self):
        self.lang = _query_param(self.scope, 'lang', 'ar')
        self.base_url = resolve_base_url(scope=self.scope)
        self.ticket_groups = set()
        self.joined_groups = set()
        self.admin_user_id = int(self.scope['url_route']['kwargs']['admin_user_id'])
        user = self.scope.get('user')
        user_type = self.scope.get('user_type')
        if not user or user_type != 'admin_desktop':
            await self.close(code=4403)
            return
        self.scope['user_type'] = user_type
        if not await ensure_socket_account_active(self, refresh=True, accept_if_needed=True):
            return
        if user.id != self.admin_user_id or not user.has_permission('support_center'):
            await self.close(code=4403)
            return

        self.user = user
        self.actor_type = 'admin_desktop'
        self.overview_group = support_center_admin_group()
        self.joined_groups.add(self.overview_group)
        await self.channel_layer.group_add(self.overview_group, self.channel_name)
        await self.accept()
        await self.send_payload(
            {
                'type': 'support.connection',
                'data': {
                    'actor_type': self.actor_type,
                    'admin_user_id': self.admin_user_id,
                    'chat_type': 'shop_admin_support',
                },
                'sent_at': format_utc_iso8601(timezone.now()),
            }
        )
        await self.send_snapshot()

    async def send_snapshot(self):
        snapshot = await database_sync_to_async(get_admin_support_snapshot)(
            scope=self.scope,
            base_url=self.base_url,
            lang=self.lang,
        )
        await self.send_payload(
            {
                'type': 'support.snapshot',
                'data': {
                    'actor_type': self.actor_type,
                    'scope': 'admin',
                    **snapshot,
                },
                'sent_at': format_utc_iso8601(timezone.now()),
            }
        )

    async def handle_support_ticket_update_status(self, data, request_id=None):
        ticket = await self._require_ticket(data.get('ticket_id'), request_id=request_id)
        if not ticket:
            return
        status_value = str(data.get('status') or '').strip()
        updated = await database_sync_to_async(update_ticket_status)(
            ticket,
            status_value=status_value,
            admin_user=self.scope.get('user'),
        )
        await self._broadcast_ticket_updated(updated)
        await self.send_ack(
            request_id,
            'support.ticket.update_status',
            data={'ticket_id': updated.public_id, 'status': updated.status},
        )

    async def handle_support_ticket_assign_to_me(self, data, request_id=None):
        ticket = await self._require_ticket(data.get('ticket_id'), request_id=request_id)
        if not ticket:
            return
        updated = await database_sync_to_async(assign_ticket_admin)(ticket, self.scope.get('user'))
        await self._broadcast_ticket_updated(updated)
        await self.send_ack(
            request_id,
            'support.ticket.assign_to_me',
            data={'ticket_id': updated.public_id, 'assigned_admin_id': self.scope['user'].id},
        )

    async def _can_access_ticket(self, ticket):
        return True
