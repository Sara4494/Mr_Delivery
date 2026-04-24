import asyncio
import json

from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncWebsocketConsumer
from django.core.serializers.json import DjangoJSONEncoder
from django.utils import timezone

from user.utils import resolve_base_url

from ..models import Driver
from .service import (
    CALL_TIMEOUT_SECONDS,
    DRIVER_PRESENCE_TIMEOUT_SECONDS,
    broadcast_driver_presence_update,
    driver_accept_order,
    driver_driver_chats_group,
    driver_mark_busy,
    driver_request_transfer,
    driver_send_text,
    driver_send_voice,
    driver_send_image,
    get_call_by_public_id,
    get_conversation_by_public_id,
    get_conversation_messages_page,
    get_driver_snapshot,
    get_order_for_conversation,
    get_shop_snapshot,
    localize_driver_chat_payload,
    mark_conversation_read,
    mark_driver_connected,
    mark_driver_connection_timed_out,
    mark_driver_disconnected,
    relay_typing_event,
    relay_webrtc_event,
    shop_driver_chats_group,
    start_call,
    store_send_text,
    store_send_voice,
    store_send_image,
    touch_driver_presence,
    transfer_order_between_drivers,
    update_call_status,
)
from ..realtime.driver import sync_driver_order_state
from ..realtime.presence import format_utc_iso8601


CALL_TIMEOUT_TASKS = {}


def _json_dumps(payload):
    return json.dumps(payload, cls=DjangoJSONEncoder)


def _query_param(scope, key, default=None):
    query_string = scope.get('query_string', b'').decode('utf-8')
    if f'{key}=' not in query_string:
        return default
    return query_string.split(f'{key}=')[-1].split('&')[0] or default


class BaseDriverChatConsumer(AsyncWebsocketConsumer):
    actor = None

    async def send_payload(self, payload):
        payload = localize_driver_chat_payload(payload, lang=getattr(self, 'lang', None))
        await self.send(text_data=_json_dumps(payload))

    async def send_ack(self, request_id, data=None, success=True, error=None):
        payload = {
            'type': 'driver_chat.ack',
            'request_id': request_id,
            'success': success,
            'data': data or {},
            'sent_at': format_utc_iso8601(timezone.now()),
        }
        if error:
            payload['error'] = error
        await self.send_payload(payload)

    async def send_error(self, code, message, request_id=None):
        payload = {
            'type': 'driver_chat.error',
            'success': False,
            'data': {
                'code': code,
                'message': message,
            },
        }
        if request_id:
            payload['request_id'] = request_id
        payload['sent_at'] = format_utc_iso8601(timezone.now())
        await self.send_payload(payload)
        if request_id:
            await self.send_ack(request_id, success=False, error={'code': code, 'message': message})

    async def driver_chat_event(self, event):
        await self.send_payload(event['payload'])

    async def driver_chat_message(self, event):
        await self.send_payload(event['payload'])

    async def receive(self, text_data):
        await self._touch_presence_if_needed()
        try:
            data = json.loads(text_data)
        except json.JSONDecodeError:
            await self.send_error('INVALID_JSON', 'تنسيق البيانات غير صحيح')
            return

        action = data.get('action') or data.get('type')
        request_id = data.get('request_id')
        if action in {'ping', 'driver_chat.ping'}:
            from ..realtime.presence import format_utc_iso8601
            from django.utils import timezone
            await self.send_payload({
                'type': 'driver_chat.pong',
                'success': True,
                'data': {},
                'request_id': request_id,
                'sent_at': format_utc_iso8601(timezone.now()),
            })
            return

        handler_name = f"handle_{str(action or '').replace('.', '_')}"
        handler = getattr(self, handler_name, None)
        if not handler:
            await self.send_error('INVALID_ACTION', 'الأكشن غير مدعوم', request_id=request_id)
            return

        try:
            await handler(data, request_id=request_id)
        except Exception as exc:
            await self.send_error('UNEXPECTED_ERROR', str(exc), request_id=request_id)

    async def _touch_presence_if_needed(self):
        if getattr(self, 'actor', None) != 'driver' or not getattr(self, 'driver_id', None):
            return
        await self._touch_driver_presence()

    @database_sync_to_async
    def _touch_driver_presence(self):
        return touch_driver_presence(self.channel_name, self.driver_id)

    @database_sync_to_async
    def _get_conversation(self, conversation_id):
        return get_conversation_by_public_id(
            conversation_id,
            shop_owner=getattr(self, 'shop_owner', None),
            driver=getattr(self, 'driver', None),
        )

    @database_sync_to_async
    def _get_order_link(self, conversation, order_id):
        return get_order_for_conversation(conversation, order_id)

    @database_sync_to_async
    def _get_call(self, call_id, conversation=None):
        call = get_call_by_public_id(call_id, conversation=conversation)
        if not call:
            return None
        if getattr(self, 'shop_owner', None) is not None and call.conversation.shop_owner_id != self.shop_owner.id:
            return None
        if getattr(self, 'driver', None) is not None and call.conversation.driver_id != self.driver.id:
            return None
        return call

    async def _require_conversation(self, conversation_id, request_id=None):
        conversation = await self._get_conversation(conversation_id)
        if not conversation:
            await self.send_error('CONVERSATION_NOT_FOUND', 'المحادثة غير موجودة', request_id=request_id)
            return None
        return conversation

    async def _require_order_link(self, conversation, order_id, request_id=None):
        order_link = await self._get_order_link(conversation, order_id)
        if not order_link:
            await self.send_error('ORDER_NOT_FOUND', 'الأوردر غير موجود داخل المحادثة', request_id=request_id)
            return None
        return order_link

    async def handle_driver_chat_subscribe(self, data, request_id=None):
        self.subscribed_conversations.add(str(data.get('conversation_id') or ''))
        await self.send_ack(request_id, data={'conversation_id': data.get('conversation_id')})

    async def handle_driver_chat_fetch_more_messages(self, data, request_id=None):
        conversation = await self._require_conversation(data.get('conversation_id'), request_id=request_id)
        if not conversation:
            return
        page = await self._fetch_messages_page(conversation, data.get('cursor'))
        await self.send_ack(
            request_id,
            data={
                'conversation_id': conversation.public_id,
                'messages': page['messages'],
                'next_cursor': page['next_cursor'],
            },
        )

    @database_sync_to_async
    def _fetch_messages_page(self, conversation, cursor):
        return get_conversation_messages_page(
            conversation,
            cursor=cursor,
            base_url=getattr(self, 'base_url', None),
            scope=getattr(self, 'scope', None),
        )

    async def handle_driver_chat_mark_read(self, data, request_id=None):
        conversation = await self._require_conversation(data.get('conversation_id'), request_id=request_id)
        if not conversation:
            return
        await self._mark_read(conversation)
        await self.send_ack(request_id, data={'conversation_id': conversation.public_id})

    @database_sync_to_async
    def _mark_read(self, conversation):
        return mark_conversation_read(conversation, self.actor)

    async def handle_driver_chat_typing(self, data, request_id=None):
        conversation = await self._require_conversation(data.get('conversation_id'), request_id=request_id)
        if not conversation:
            return
        await self._relay_typing(conversation, data.get('is_typing'))
        await self.send_ack(request_id, data={'conversation_id': conversation.public_id})

    @database_sync_to_async
    def _relay_typing(self, conversation, is_typing):
        return relay_typing_event(conversation=conversation, sender=self.actor, is_typing=is_typing)

    async def handle_driver_chat_webrtc_offer(self, data, request_id=None):
        await self._handle_webrtc_event('driver_chat.webrtc_offer', data, request_id=request_id)

    async def handle_driver_chat_webrtc_answer(self, data, request_id=None):
        await self._handle_webrtc_event('driver_chat.webrtc_answer', data, request_id=request_id)

    async def handle_driver_chat_webrtc_ice_candidate(self, data, request_id=None):
        await self._handle_webrtc_event('driver_chat.webrtc_ice_candidate', data, request_id=request_id)

    async def _handle_webrtc_event(self, event_type, data, request_id=None):
        call = await self._get_call(data.get('call_id'))
        if not call:
            await self.send_error('CALL_NOT_FOUND', 'المكالمة غير موجودة', request_id=request_id)
            return
        await self._relay_webrtc(call.conversation, event_type, {
            'call_id': call.public_id,
            **({k: v for k, v in data.items() if k in {'sdp', 'candidate'}}),
        })
        await self.send_ack(request_id, data={'call_id': call.public_id})

    @database_sync_to_async
    def _relay_webrtc(self, conversation, event_type, payload):
        return relay_webrtc_event(conversation=conversation, event_type=event_type, data=payload)

    @database_sync_to_async
    def _update_call_status(self, call, status_value, reason=None):
        return update_call_status(call, status_value=status_value, reason=reason)

    def _schedule_timeout(self, call_id):
        self._cancel_timeout(call_id)
        CALL_TIMEOUT_TASKS[call_id] = asyncio.create_task(self._timeout_call(call_id))

    def _cancel_timeout(self, call_id):
        task = CALL_TIMEOUT_TASKS.pop(call_id, None)
        if task:
            task.cancel()

    async def _timeout_call(self, call_id):
        try:
            await asyncio.sleep(CALL_TIMEOUT_SECONDS)
            call = await self._get_call(call_id)
            if not call or call.status != 'ringing':
                return
            await self._update_call_status(call, status_value='timeout')
            await self._update_call_status(call, status_value='missed')
        except asyncio.CancelledError:
            return
        finally:
            CALL_TIMEOUT_TASKS.pop(call_id, None)


class DriverChatsShopConsumer(BaseDriverChatConsumer):
    actor = 'store'

    async def driver_chat_event(self, event):
        await super().driver_chat_event(event)

    async def driver_chat_message(self, event):
        await super().driver_chat_message(event)

    async def connect(self):
        self.shop_owner_id = int(self.scope['url_route']['kwargs']['shop_owner_id'])
        self.base_url = resolve_base_url(scope=self.scope)
        self.lang = _query_param(self.scope, 'lang', 'ar')
        self.subscribed_conversations = set()

        user = self.scope.get('user')
        user_type = self.scope.get('user_type')
        if not user or user_type not in {'shop_owner', 'employee'}:
            await self.close(code=4401)
            return

        owner = user if user_type == 'shop_owner' else getattr(user, 'shop_owner', None)
        if not owner or owner.id != self.shop_owner_id:
            await self.close(code=4403)
            return

        self.user = user
        self.shop_owner = owner
        self.room_group_name = shop_driver_chats_group(self.shop_owner_id)
        await self.channel_layer.group_add(self.room_group_name, self.channel_name)
        await self.accept()
        await self.send_payload({
            'type': 'driver_chat.connection',
            'success': True,
            'data': {'shop_owner_id': self.shop_owner_id},
            'sent_at': format_utc_iso8601(timezone.now()),
        })
        await self.send_snapshot()

    async def disconnect(self, close_code):
        if hasattr(self, 'room_group_name'):
            await self.channel_layer.group_discard(self.room_group_name, self.channel_name)

    async def send_snapshot(self):
        snapshot = await self._get_snapshot()
        await self.send_payload({
            'type': 'driver_chats.snapshot',
            'success': True,
            'data': snapshot,
            'sent_at': format_utc_iso8601(timezone.now()),
        })

    @database_sync_to_async
    def _get_snapshot(self):
        return get_shop_snapshot(self.shop_owner, scope=getattr(self, 'scope', None), base_url=getattr(self, 'base_url', None))

    async def handle_driver_chat_send_text(self, data, request_id=None):
        conversation = await self._require_conversation(data.get('conversation_id'), request_id=request_id)
        if not conversation:
            return
        text = str(data.get('text') or '').strip()
        if not text:
            await self.send_error('TEXT_REQUIRED', 'النص مطلوب', request_id=request_id)
            return
        message = await self._store_send_text(conversation, text, data.get('client_message_id'))
        await self.send_ack(request_id, data={'message_id': message.public_id, 'conversation_id': conversation.public_id})

    @database_sync_to_async
    def _store_send_text(self, conversation, text, client_message_id):
        return store_send_text(
            conversation=conversation,
            text=text,
            client_message_id=client_message_id,
            scope=getattr(self, 'scope', None),
            base_url=getattr(self, 'base_url', None),
        )

    async def handle_driver_chat_send_voice(self, data, request_id=None):
        conversation = await self._require_conversation(data.get('conversation_id'), request_id=request_id)
        if not conversation:
            return
        audio_url = str(data.get('audio_url') or '').strip()
        if not audio_url:
            await self.send_error('AUDIO_URL_REQUIRED', 'رابط الصوت مطلوب', request_id=request_id)
            return
        message = await self._store_send_voice(conversation, audio_url, data.get('voice_duration_seconds'), data.get('client_message_id'))
        await self.send_ack(request_id, data={'message_id': message.public_id, 'conversation_id': conversation.public_id})

    async def handle_driver_chat_send_image(self, data, request_id=None):
        conversation = await self._require_conversation(data.get('conversation_id'), request_id=request_id)
        if not conversation:
            return
        image_url = str(data.get('image_url') or '').strip()
        if not image_url:
            await self.send_error('IMAGE_URL_REQUIRED', 'رابط الصورة مطلوب', request_id=request_id)
            return
        message = await self._store_send_image(conversation, image_url, data.get('text'), data.get('client_message_id'))
        await self.send_ack(request_id, data={'message_id': message.public_id, 'conversation_id': conversation.public_id})

    @database_sync_to_async
    def _store_send_voice(self, conversation, audio_url, voice_duration_seconds, client_message_id):
        return store_send_voice(
            conversation=conversation,
            audio_url=audio_url,
            voice_duration_seconds=voice_duration_seconds,
            client_message_id=client_message_id,
            scope=getattr(self, 'scope', None),
            base_url=getattr(self, 'base_url', None),
        )

    @database_sync_to_async
    def _store_send_image(self, conversation, image_url, text, client_message_id):
        return store_send_image(
            conversation=conversation,
            image_url=image_url,
            text=text,
            client_message_id=client_message_id,
            scope=getattr(self, 'scope', None),
            base_url=getattr(self, 'base_url', None),
        )

    async def handle_driver_chat_transfer_to_driver(self, data, request_id=None):
        conversation = await self._require_conversation(data.get('source_conversation_id') or data.get('conversation_id'), request_id=request_id)
        if not conversation:
            return
        order_link = await self._require_order_link(conversation, data.get('order_id'), request_id=request_id)
        if not order_link:
            return
        target_driver_id = data.get('target_driver_id')
        target_driver = await self._get_target_driver(target_driver_id)
        if not target_driver:
            await self.send_error('TARGET_DRIVER_NOT_FOUND', 'السائق المستهدف غير موجود أو غير تابع لنفس المتجر', request_id=request_id)
            return
        await self._transfer_order(order_link.order, conversation.driver, target_driver)
        await self.send_ack(request_id, data={'order_id': f'order_{order_link.order_id}', 'target_driver_id': str(target_driver.id)})

    @database_sync_to_async
    def _get_target_driver(self, target_driver_id):
        numeric_id = int(str(target_driver_id).rsplit('_', 1)[-1]) if str(target_driver_id).rsplit('_', 1)[-1].isdigit() else None
        if not numeric_id:
            return None
        return Driver.objects.filter(driver_shops__shop_owner=self.shop_owner, driver_shops__status='active', id=numeric_id).distinct().first()

    @database_sync_to_async
    def _transfer_order(self, order, source_driver, target_driver):
        previous_status = order.status
        previous_driver_id = order.driver_id
        previous_driver_accepted_at = order.driver_accepted_at
        result = transfer_order_between_drivers(
            order,
            source_driver=source_driver,
            target_driver=target_driver,
            scope=getattr(self, 'scope', None),
            base_url=getattr(self, 'base_url', None),
        )
        sync_driver_order_state(
            order,
            previous_status=previous_status,
            previous_driver_id=previous_driver_id,
            previous_driver_accepted_at=previous_driver_accepted_at,
            scope=getattr(self, 'scope', None),
            base_url=getattr(self, 'base_url', None),
        )
        return result

    async def handle_driver_chat_call_start(self, data, request_id=None):
        conversation = await self._require_conversation(data.get('conversation_id'), request_id=request_id)
        if not conversation:
            return
        call = await self._start_call(conversation)
        self._schedule_timeout(call.public_id)
        await self.send_ack(request_id, data={'call_id': call.public_id, 'conversation_id': conversation.public_id})

    @database_sync_to_async
    def _start_call(self, conversation):
        return start_call(conversation=conversation, initiated_by='store')

    async def handle_driver_chat_call_cancel(self, data, request_id=None):
        await self._finish_call(data.get('call_id'), 'cancelled', request_id=request_id)

    async def handle_driver_chat_call_end(self, data, request_id=None):
        await self._finish_call(data.get('call_id'), 'ended', request_id=request_id)

    async def _finish_call(self, call_id, status_value, request_id=None):
        call = await self._get_call(call_id)
        if not call:
            await self.send_error('CALL_NOT_FOUND', 'المكالمة غير موجودة', request_id=request_id)
            return
        await self._update_call_status(call, status_value=status_value)
        self._cancel_timeout(call.public_id)
        await self.send_ack(request_id, data={'call_id': call.public_id, 'status': status_value})


class DriverChatsDriverConsumer(BaseDriverChatConsumer):
    actor = 'driver'

    async def driver_chat_event(self, event):
        await super().driver_chat_event(event)

    async def driver_chat_message(self, event):
        await super().driver_chat_message(event)

    async def connect(self):
        self.driver_id = int(self.scope['url_route']['kwargs']['driver_id'])
        self.base_url = resolve_base_url(scope=self.scope)
        self.lang = _query_param(self.scope, 'lang', 'ar')
        self.subscribed_conversations = set()

        user = self.scope.get('user')
        user_type = self.scope.get('user_type')
        if not user or user_type != 'driver' or int(user.id) != self.driver_id:
            await self.close(code=4401)
            return

        self.user = user
        self.driver = user
        self.room_group_name = driver_driver_chats_group(self.driver_id)
        self._presence_timeout_task = None
        await self.channel_layer.group_add(self.room_group_name, self.channel_name)
        await self.accept()
        presence_state = await self._mark_driver_connected()
        self._presence_timeout_task = asyncio.create_task(self._watch_presence_timeout())
        if presence_state and presence_state.get('changed'):
            await self._broadcast_driver_presence()
        await self.send_payload({
            'type': 'driver_chat.connection',
            'success': True,
            'data': {'driver_id': str(self.driver_id)},
            'sent_at': format_utc_iso8601(timezone.now()),
        })
        await self.send_snapshot()

    async def disconnect(self, close_code):
        if hasattr(self, 'room_group_name'):
            await self.channel_layer.group_discard(self.room_group_name, self.channel_name)
        self._cancel_presence_timeout_task()
        presence_state = await self._mark_driver_disconnected()
        if presence_state and presence_state.get('changed'):
            await self._broadcast_driver_presence()

    async def send_snapshot(self):
        snapshot = await self._get_snapshot()
        await self.send_payload({
            'type': 'driver_chats.snapshot',
            'success': True,
            'data': snapshot,
            'sent_at': format_utc_iso8601(timezone.now()),
        })

    @database_sync_to_async
    def _get_snapshot(self):
        return get_driver_snapshot(self.driver, scope=getattr(self, 'scope', None), base_url=getattr(self, 'base_url', None))

    @database_sync_to_async
    def _mark_driver_connected(self):
        return mark_driver_connected(self.driver_id, self.channel_name, connection_type='driver_chat_socket')

    @database_sync_to_async
    def _mark_driver_disconnected(self):
        return mark_driver_disconnected(self.channel_name)

    @database_sync_to_async
    def _broadcast_driver_presence(self):
        return broadcast_driver_presence_update(self.driver_id)

    def _cancel_presence_timeout_task(self):
        task = getattr(self, '_presence_timeout_task', None)
        if task:
            task.cancel()
            self._presence_timeout_task = None

    async def _watch_presence_timeout(self):
        try:
            while True:
                await asyncio.sleep(15)
                timed_out_state = await self._mark_driver_timed_out()
                if timed_out_state:
                    if timed_out_state.get('changed'):
                        await self._broadcast_driver_presence()
                    await self.close(code=4001)
                    return
        except asyncio.CancelledError:
            return

    @database_sync_to_async
    def _mark_driver_timed_out(self):
        return mark_driver_connection_timed_out(
            self.channel_name,
            timeout_seconds=DRIVER_PRESENCE_TIMEOUT_SECONDS,
        )

    async def handle_driver_chat_send_text(self, data, request_id=None):
        conversation = await self._require_conversation(data.get('conversation_id'), request_id=request_id)
        if not conversation:
            return
        text = str(data.get('text') or '').strip()
        if not text:
            await self.send_error('TEXT_REQUIRED', 'النص مطلوب', request_id=request_id)
            return
        message = await self._driver_send_text(conversation, text, data.get('client_message_id'))
        await self.send_ack(request_id, data={'message_id': message.public_id, 'conversation_id': conversation.public_id})

    @database_sync_to_async
    def _driver_send_text(self, conversation, text, client_message_id):
        return driver_send_text(
            conversation=conversation,
            text=text,
            client_message_id=client_message_id,
            scope=getattr(self, 'scope', None),
            base_url=getattr(self, 'base_url', None),
        )

    async def handle_driver_chat_send_voice(self, data, request_id=None):
        conversation = await self._require_conversation(data.get('conversation_id'), request_id=request_id)
        if not conversation:
            return
        audio_url = str(data.get('audio_url') or '').strip()
        if not audio_url:
            await self.send_error('AUDIO_URL_REQUIRED', 'رابط الصوت مطلوب', request_id=request_id)
            return
        message = await self._driver_send_voice(conversation, audio_url, data.get('voice_duration_seconds'), data.get('client_message_id'))
        await self.send_ack(request_id, data={'message_id': message.public_id, 'conversation_id': conversation.public_id})

    async def handle_driver_chat_send_image(self, data, request_id=None):
        conversation = await self._require_conversation(data.get('conversation_id'), request_id=request_id)
        if not conversation:
            return
        image_url = str(data.get('image_url') or '').strip()
        if not image_url:
            await self.send_error('IMAGE_URL_REQUIRED', 'رابط الصورة مطلوب', request_id=request_id)
            return
        message = await self._driver_send_image(conversation, image_url, data.get('text'), data.get('client_message_id'))
        await self.send_ack(request_id, data={'message_id': message.public_id, 'conversation_id': conversation.public_id})

    @database_sync_to_async
    def _driver_send_voice(self, conversation, audio_url, voice_duration_seconds, client_message_id):
        return driver_send_voice(
            conversation=conversation,
            audio_url=audio_url,
            voice_duration_seconds=voice_duration_seconds,
            client_message_id=client_message_id,
            scope=getattr(self, 'scope', None),
            base_url=getattr(self, 'base_url', None),
        )

    @database_sync_to_async
    def _driver_send_image(self, conversation, image_url, text, client_message_id):
        return driver_send_image(
            conversation=conversation,
            image_url=image_url,
            text=text,
            client_message_id=client_message_id,
            scope=getattr(self, 'scope', None),
            base_url=getattr(self, 'base_url', None),
        )

    async def handle_driver_chat_accept_order(self, data, request_id=None):
        conversation = await self._require_conversation(data.get('conversation_id'), request_id=request_id)
        if not conversation:
            return
        order_link = await self._require_order_link(conversation, data.get('order_id'), request_id=request_id)
        if not order_link:
            return
        await self._accept_order(conversation, order_link)
        await self.send_ack(request_id, data={'conversation_id': conversation.public_id, 'order_id': f'order_{order_link.order_id}'})

    @database_sync_to_async
    def _accept_order(self, conversation, order_link):
        return driver_accept_order(
            conversation=conversation,
            conversation_order=order_link,
            scope=getattr(self, 'scope', None),
            base_url=getattr(self, 'base_url', None),
        )

    async def handle_driver_chat_mark_busy(self, data, request_id=None):
        conversation = await self._require_conversation(data.get('conversation_id'), request_id=request_id)
        if not conversation:
            return
        order_link = await self._require_order_link(conversation, data.get('order_id'), request_id=request_id)
        if not order_link:
            return
        await self._mark_busy(conversation, order_link)
        await self.send_ack(request_id, data={'conversation_id': conversation.public_id, 'order_id': f'order_{order_link.order_id}'})

    @database_sync_to_async
    def _mark_busy(self, conversation, order_link):
        return driver_mark_busy(
            conversation=conversation,
            conversation_order=order_link,
            scope=getattr(self, 'scope', None),
            base_url=getattr(self, 'base_url', None),
        )

    async def handle_driver_chat_request_transfer(self, data, request_id=None):
        conversation = await self._require_conversation(data.get('conversation_id'), request_id=request_id)
        if not conversation:
            return
        order_link = await self._require_order_link(conversation, data.get('order_id'), request_id=request_id)
        if not order_link:
            return
        reason = str(data.get('reason') or '').strip()
        if not reason:
            await self.send_error('TRANSFER_REASON_REQUIRED', 'سبب التحويل مطلوب', request_id=request_id)
            return
        await self._request_transfer(conversation, order_link, reason)
        await self.send_ack(request_id, data={'conversation_id': conversation.public_id, 'order_id': f'order_{order_link.order_id}', 'reason': reason})

    @database_sync_to_async
    def _request_transfer(self, conversation, order_link, reason):
        return driver_request_transfer(
            conversation=conversation,
            conversation_order=order_link,
            reason=reason,
            scope=getattr(self, 'scope', None),
            base_url=getattr(self, 'base_url', None),
        )

    async def handle_driver_chat_call_accept(self, data, request_id=None):
        await self._respond_to_call(data.get('call_id'), 'accepted', request_id=request_id)

    async def handle_driver_chat_call_reject(self, data, request_id=None):
        await self._respond_to_call(data.get('call_id'), 'rejected', request_id=request_id, reason='busy')

    async def handle_driver_chat_call_end(self, data, request_id=None):
        await self._respond_to_call(data.get('call_id'), 'ended', request_id=request_id)

    async def _respond_to_call(self, call_id, status_value, request_id=None, reason=None):
        call = await self._get_call(call_id)
        if not call:
            await self.send_error('CALL_NOT_FOUND', 'المكالمة غير موجودة', request_id=request_id)
            return
        await self._update_call_status(call, status_value=status_value, reason=reason)
        self._cancel_timeout(call.public_id)
        await self.send_ack(request_id, data={'call_id': call.public_id, 'status': status_value})
