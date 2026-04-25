import asyncio
import json
import uuid
import logging
from asgiref.sync import sync_to_async
from channels.generic.websocket import AsyncWebsocketConsumer
from channels.db import database_sync_to_async
from django.core.serializers.json import DjangoJSONEncoder
from django.utils import timezone
from .models import (
    Order,
    ChatMessage,
    Customer,
    Employee,
    Driver,
    CustomerSupportConversation,
    CustomerSupportMessage,
)
from .presence import (
    build_customer_presence_broadcast_batches,
    format_utc_iso8601,
    get_order_customer_presence_snapshot,
    mark_customer_websocket_connected,
    mark_customer_websocket_disconnected,
)
from user.models import ShopOwner
from .serializers import (
    ChatMessageSerializer,
    OrderSerializer,
    CustomerSupportConversationSerializer,
    CustomerSupportMessageSerializer,
)
from .driver_chat_service import (
    DRIVER_PRESENCE_TIMEOUT_SECONDS,
    broadcast_driver_presence_update,
    get_driver_presence_snapshot,
    mark_driver_connected,
    mark_driver_connection_timed_out,
    mark_driver_disconnected,
    touch_driver_presence,
)
from .customer_app_realtime import (
    CUSTOMER_APP_REALTIME_SCOPE,
    build_all_snapshots,
    build_order_delta_events,
    build_support_delta_events,
)
from .driver_realtime import build_driver_snapshot_events, has_driver_accepted
from .fcm_service import send_order_chat_push_fallback, send_ring_push_fallback
from user.utils import build_absolute_file_url, build_message_fields, resolve_base_url
from gallery.serializers import GalleryImageSerializer, ShopProfileSerializer, WorkScheduleSerializer
from .websocket_auth import ensure_socket_account_active
from gallery.views import (
    _augment_gallery_image_payloads,
    _latest_approval_request_map,
    build_shop_portfolio_snapshot,
    _build_viewer_profile_payload,
)
from gallery.models import GalleryImage, WorkSchedule


logger = logging.getLogger(__name__)


def _with_localized_message(payload, message, lang=None):
    return {
        **payload,
        **build_message_fields(message, lang=lang),
    }


def _json_dumps(payload):
    return json.dumps(payload, cls=DjangoJSONEncoder)


def _serializer_context(lang=None, scope=None, base_url=None):
    context = {}
    if lang is not None:
        context['lang'] = lang
    if scope is not None:
        context['scope'] = scope
    if base_url:
        context['base_url'] = base_url
    return context


def _normalize_ring_targets(raw_targets):
    if isinstance(raw_targets, str):
        candidates = [raw_targets]
    elif isinstance(raw_targets, (list, tuple, set)):
        candidates = list(raw_targets)
    else:
        candidates = []

    alias_map = {
        'shop': 'shop',
        'store': 'shop',
        'merchant': 'shop',
        'shop_owner': 'shop',
        'employee': 'shop',
        'customer': 'customer',
        'client': 'customer',
        'driver': 'driver',
        'delivery': 'driver',
        'delivery_driver': 'driver',
    }

    normalized = []
    for item in candidates:
        key = alias_map.get(str(item).strip().lower())
        if key and key not in normalized:
            normalized.append(key)
    return normalized


def _user_has_order_access(order, user, user_type):
    if not user:
        return False
    if user_type == 'shop_owner':
        return order.shop_owner_id == user.id
    if user_type == 'employee':
        return order.shop_owner_id == getattr(user, 'shop_owner_id', None)
    if user_type == 'driver':
        return order.driver_id == user.id
    if user_type == 'customer':
        return order.customer_id == user.id
    return False


def _get_user_display_name(user, user_type):
    if user_type == 'customer':
        return getattr(user, 'name', 'عميل')
    if user_type == 'shop_owner':
        return getattr(user, 'owner_name', 'المحل')
    if user_type == 'employee':
        return getattr(user, 'name', 'موظف المحل')
    if user_type == 'driver':
        return getattr(user, 'name', 'المندوب')
    return 'غير معروف'


def _build_ring_shop_payload(order, scope=None, base_url=None):
    shop_owner = getattr(order, 'shop_owner', None)
    return {
        'id': getattr(shop_owner, 'id', None),
        'name': getattr(shop_owner, 'shop_name', None),
        'profile_image_url': build_absolute_file_url(
            getattr(shop_owner, 'profile_image', None),
            scope=scope,
            base_url=base_url,
        ),
    }


def _build_flat_ring_shop_fields(shop_payload):
    return {
        'shop_id': shop_payload.get('id'),
        'shop_name': shop_payload.get('name'),
        'shop_profile_image_url': shop_payload.get('profile_image_url'),
    }


def _build_ring_driver_fields(user, user_type, scope=None, base_url=None):
    if user_type != 'driver':
        return {
            'driver_image_url': None,
        }

    return {
        'driver_image_url': build_absolute_file_url(
            getattr(user, 'profile_image', None),
            scope=scope,
            base_url=base_url,
        ),
    }


@database_sync_to_async
def _build_ring_dispatch_context(user, user_type, order_id, raw_targets, chat_type=None, scope=None, base_url=None):
    try:
        order = Order.objects.select_related('shop_owner', 'customer', 'driver').get(id=order_id)
    except Order.DoesNotExist:
        return {
            'error': {
                'code': 'ORDER_NOT_FOUND',
                'message': 'الطلب غير موجود',
            }
        }

    if not _user_has_order_access(order, user, user_type):
        return {
            'error': {
                'code': 'ORDER_ACCESS_DENIED',
                'message': 'غير مسموح لك بإرسال رنة لهذا الطلب',
            }
        }

    targets = _normalize_ring_targets(raw_targets)
    if not targets:
        return {
            'error': {
                'code': 'RING_TARGET_REQUIRED',
                'message': 'يجب تحديد الطرف المطلوب إرسال الرنة له',
            }
        }

    allowed_targets = {
        'customer': {'shop', 'driver'},
        'shop_owner': {'customer', 'driver'},
        'employee': {'customer', 'driver'},
        'driver': {'customer', 'shop'},
    }

    invalid_targets = [target for target in targets if target not in allowed_targets.get(user_type, set())]
    if invalid_targets:
        return {
            'error': {
                'code': 'RING_TARGET_NOT_ALLOWED',
                'message': 'الطرف المطلوب غير مسموح لهذا المستخدم',
                'details': {
                    'targets': invalid_targets,
                },
            }
        }

    group_names = set()
    delivered_targets = []
    unavailable_targets = []

    if 'shop' in targets:
        if order.shop_owner_id:
            group_names.add(f'shop_orders_{order.shop_owner_id}')
            delivered_targets.append('shop')
        else:
            unavailable_targets.append('shop')

    if 'customer' in targets:
        if order.customer_id:
            group_names.add(f'customer_orders_{order.customer_id}')
            delivered_targets.append('customer')
        else:
            unavailable_targets.append('customer')

    if 'driver' in targets:
        if order.driver_id:
            group_names.add(f'driver_{order.driver_id}')
            delivered_targets.append('driver')
        else:
            unavailable_targets.append('driver')

    if not delivered_targets:
        return {
            'error': {
                'code': 'RING_TARGET_UNAVAILABLE',
                'message': 'الطرف المطلوب غير متاح حاليا',
                'details': {
                    'targets': unavailable_targets or targets,
                },
            }
        }

    shop_payload = _build_ring_shop_payload(order, scope=scope, base_url=base_url)

    payload = {
        'ring_id': str(uuid.uuid4()),
        'order_id': order.id,
        'order_number': order.order_number,
        'shop': shop_payload,
        'sender_type': user_type,
        'sender_name': _get_user_display_name(user, user_type),
        'sender_id': getattr(user, 'id', None),
        'targets': delivered_targets,
        'created_at': timezone.now().isoformat(),
        'chat_type': chat_type if chat_type in ['shop_customer', 'driver_customer'] else None,
        'notification_kind': 'ring',
        'play_sound_on_frontend': True,
        **_build_flat_ring_shop_fields(shop_payload),
        **_build_ring_driver_fields(user, user_type, scope=scope, base_url=base_url),
    }

    if len(delivered_targets) == 1:
        payload['target'] = delivered_targets[0]

    return {
        'payload': payload,
        'group_names': list(group_names),
        'unavailable_targets': unavailable_targets,
    }


async def _send_ack(consumer, action, request_id=None, data=None, message='تم تنفيذ الطلب بنجاح'):
    payload = {
        'type': 'ack',
        'action': action,
        'success': True,
        'data': data or {},
    }
    if request_id is not None:
        payload['request_id'] = request_id
    await consumer.send(
        text_data=_json_dumps(
            _with_localized_message(payload, message, lang=getattr(consumer, 'lang', None))
        )
    )


async def _send_error_event(consumer, code, message, request_id=None, details=None):
    payload = {
        'type': 'error',
        'success': False,
        'code': code,
    }
    if request_id is not None:
        payload['request_id'] = request_id
    if details:
        payload['details'] = details
    await consumer.send(
        text_data=_json_dumps(
            _with_localized_message(payload, message, lang=getattr(consumer, 'lang', None))
        )
    )


async def _handle_ring_request(consumer, data, request_id=None, chat_type=None):
    order_id = data.get('order_id') or getattr(consumer, 'order_id', None)
    if not order_id:
        await _send_error_event(
            consumer,
            code='ORDER_ID_REQUIRED',
            message='معرف الطلب مطلوب لإرسال الرنة',
            request_id=request_id,
        )
        return

    ring_context = await _build_ring_dispatch_context(
        consumer.user,
        consumer.user_type,
        int(order_id),
        data.get('targets', data.get('target')),
        chat_type=chat_type,
        scope=getattr(consumer, 'scope', None),
        base_url=getattr(consumer, 'base_url', None),
    )

    error = ring_context.get('error')
    if error:
        await _send_error_event(
            consumer,
            code=error.get('code', 'RING_FAILED'),
            message=error.get('message', 'تعذر إرسال الرنة'),
            request_id=request_id,
            details=error.get('details'),
        )
        return

    for group_name in ring_context['group_names']:
        await consumer.channel_layer.group_send(
            group_name,
            {
                'type': 'ring',
                'data': ring_context['payload'],
            }
        )

    try:
        await sync_to_async(send_ring_push_fallback, thread_sensitive=False)(
            int(order_id),
            ring_context['payload'],
            scope=getattr(consumer, 'scope', None),
            base_url=getattr(consumer, 'base_url', None),
        )
    except Exception:
        logger.exception('fcm ring fallback failed for order_id=%s', order_id)

    await _send_ack(
        consumer,
        action='ring',
        request_id=request_id,
        data={
            'order_id': int(order_id),
            'shop': ring_context['payload'].get('shop'),
            'shop_id': ring_context['payload'].get('shop_id'),
            'shop_name': ring_context['payload'].get('shop_name'),
            'shop_profile_image_url': ring_context['payload'].get('shop_profile_image_url'),
            'targets': ring_context['payload']['targets'],
            'unavailable_targets': ring_context.get('unavailable_targets', []),
            'ring_id': ring_context['payload']['ring_id'],
        },
        message='تم إرسال الرنة بنجاح',
    )







class ChatConsumer(AsyncWebsocketConsumer):
    """
    Chat WebSocket consumer for:
    - shop_owner <-> customer (shop_customer chat)
    - employee <-> customer (shop_customer chat)
    - driver <-> customer (driver_customer chat)
    
    URL: ws://server/ws/chat/order/{order_id}/?token=JWT_TOKEN&chat_type=shop_customer
    """
    
    async def connect(self):
        """Connect to the WebSocket."""
        try:
            self.order_id = self.scope['url_route']['kwargs']['order_id']
            
            # Parse chat type from the query string.
            query_string = self.scope.get('query_string', b'').decode('utf-8')
            self.chat_type = 'shop_customer'  # default
            if 'chat_type=' in query_string:
                chat_type_param = query_string.split('chat_type=')[-1].split('&')[0]
                if chat_type_param in ['shop_customer', 'driver_customer']:
                    self.chat_type = chat_type_param

            # Parse language from the query string.
            self.lang = 'ar'
            if 'lang=' in query_string:
                self.lang = query_string.split('lang=')[-1].split('&')[0]
            
            self.room_group_name = f'chat_order_{self.order_id}_{self.chat_type}'
            self.base_url = resolve_base_url(scope=self.scope)
            
            # Validate the authenticated user.
            user = self.scope.get('user')
            user_type = self.scope.get('user_type')
            
            if not user or not user_type:
                await self.close(code=4401)  # unauthorized
                return
            self.user = user
            self.user_type = user_type
            if not await ensure_socket_account_active(self, refresh=True, accept_if_needed=True):
                return
            
            # Validate access to the order.
            has_access = await self.check_order_access(user, user_type)
            if not has_access:
                await self.close(code=4403)  # forbidden
                return
            
            # Validate access to the requested chat type.
            if self.chat_type == 'driver_customer' and user_type not in ['driver', 'customer']:
                await self.close(code=4403)
                return
            
            if self.chat_type == 'shop_customer' and user_type not in ['shop_owner', 'employee', 'customer']:
                await self.close(code=4403)
                return
            
            self.customer_presence_registered = False
            self.driver_presence_registered = False
            self.driver_presence_timeout_task = None
            
            # Join the chat group.
            await self.channel_layer.group_add(self.room_group_name, self.channel_name)
            await self.accept()

            presence_state = None
            if self.user_type == 'customer':
                presence_state = await self.register_customer_presence('chat')
                self.customer_presence_registered = bool(presence_state)
            elif self.user_type == 'driver':
                presence_state = await self.register_driver_presence('order_chat')
                self.driver_presence_registered = bool(presence_state)
                self.driver_presence_timeout_task = asyncio.create_task(self.watch_driver_presence_timeout())
            
            # Send connection confirmation.
            await self.send(text_data=_json_dumps(_with_localized_message(
                {
                    'type': 'connection',
                    'order_id': self.order_id,
                    'chat_type': self.chat_type,
                    'user_type': self.user_type
                },
                'تم الاتصال بنجاح',
                lang=self.lang
            )))

            presence_snapshot = await self.get_presence_snapshot()
            if presence_snapshot:
                await self.send(text_data=_json_dumps({
                    'type': 'presence_snapshot',
                    'data': presence_snapshot,
                }))

            if presence_state and presence_state.get('changed'):
                await self.broadcast_presence_updates(presence_state)
            
            # Send previous messages.
            previous_messages = await self.get_previous_messages()
            await self.send(text_data=_json_dumps({
                'type': 'previous_messages',
                'messages': previous_messages
            }))
                
        except Exception as e:
            print(f"[ChatConsumer.connect] error: {e}")
            await self.close(code=1011)
            await self.channel_layer.group_discard(self.room_group_name, self.channel_name)

    async def disconnect(self, close_code):
        if hasattr(self, 'room_group_name'):
            await self.channel_layer.group_discard(self.room_group_name, self.channel_name)

        if getattr(self, 'customer_presence_registered', False):
            presence_state = await self.unregister_customer_presence()
            if presence_state and presence_state.get('changed'):
                await self.broadcast_presence_updates(presence_state)
        elif getattr(self, 'driver_presence_registered', False):
            self.cancel_driver_presence_timeout_task()
            presence_state = await self.unregister_driver_presence()
            if presence_state and presence_state.get('changed'):
                await self.broadcast_driver_presence()
    
    async def receive(self, text_data):
        """Receive an inbound WebSocket event."""
        try:
            if not await ensure_socket_account_active(self, refresh=True):
                return
            await self.touch_driver_presence_if_needed()
            data = json.loads(text_data)
            event_type = data.get('type', 'chat_message')
            request_id = data.get('request_id')
            
            if event_type in ['chat_message', 'send_message']:
                if data.get('message_type') == 'location':
                    await self.handle_location(data, request_id=request_id, action=event_type)
                else:
                    await self.handle_chat_message(data, request_id=request_id, action=event_type)
            elif event_type == 'ring':
                await self.handle_ring(data, request_id=request_id)
            elif event_type == 'mark_read':
                await self.handle_mark_read(request_id=request_id)
            elif event_type == 'typing':
                await self.handle_typing(data)
            elif event_type == 'location':
                await self.handle_location(data, request_id=request_id, action=event_type)
            else:
                await self.send_error_event(
                    code='UNKNOWN_EVENT',
                    message='نوع الحدث غير مدعوم',
                    request_id=request_id,
                    details={'type': event_type},
                )
                
        except json.JSONDecodeError:
            await self.send_error_event(
                code='INVALID_JSON',
                message='تنسيق البيانات غير صحيح',
            )
        except Exception as e:
            print(f"[ChatConsumer.receive] error: {e}")
            await self.send_error_event(
                code='UNEXPECTED_ERROR',
                message='حدث خطأ غير متوقع',
                details={'error_detail': str(e)},
            )

    async def touch_driver_presence_if_needed(self):
        if getattr(self, 'user_type', None) != 'driver':
            return
        await self._touch_driver_presence()

    def cancel_driver_presence_timeout_task(self):
        task = getattr(self, 'driver_presence_timeout_task', None)
        if task:
            task.cancel()
            self.driver_presence_timeout_task = None

    async def watch_driver_presence_timeout(self):
        try:
            while True:
                await asyncio.sleep(15)
                timed_out_state = await self.mark_driver_presence_timed_out()
                if timed_out_state:
                    if timed_out_state.get('changed'):
                        await self.broadcast_driver_presence()
                    await self.close(code=4001)
                    return
        except asyncio.CancelledError:
            return
    
    async def handle_chat_message(self, data, request_id=None, action='chat_message'):
        """Handle a chat message event."""
        content = data.get('content', '')
        msg_type = data.get('message_type', 'text')

        if msg_type not in ['text', 'location']:
            await self.send_error_event(
                code='UNSUPPORTED_MESSAGE_TYPE',
                message='هذا النوع من الرسائل غير مدعوم عبر الـ WebSocket',
                request_id=request_id,
                details={'message_type': msg_type},
            )
            return
        
        if msg_type == 'text' and not content:
            await self.send_error_event(
                code='MESSAGE_CONTENT_REQUIRED',
                message='محتوى الرسالة مطلوب',
                request_id=request_id,
            )
            return
        
        # Persist the message first, then broadcast it.
        message = await self.save_message(
            content=content,
            message_type=msg_type,
            latitude=data.get('latitude'),
            longitude=data.get('longitude')
        )
        
        if message:
            serialized = await self.serialize_message(message)
            
            await self.channel_layer.group_send(
                self.room_group_name,
                {
                    'type': 'chat_message',
                    'message': serialized
                }
            )
            await self.broadcast_new_message_notification(serialized)
            await self.send_ack(
                action=action,
                request_id=request_id,
                data={
                    'message_id': message.id,
                    'order_id': int(self.order_id),
                    'chat_type': self.chat_type,
                },
            )
            return

        await self.send_error_event(
            code='MESSAGE_SAVE_FAILED',
            message='تعذر حفظ الرسالة',
            request_id=request_id,
        )
    
    async def handle_location(self, data, request_id=None, action='location'):
        """Handle a location message event."""
        latitude = data.get('latitude')
        longitude = data.get('longitude')
        content = data.get('content', 'موقعي الحالي')
        
        if latitude is None or longitude is None:
            await self.send_error_event(
                code='LOCATION_COORDINATES_REQUIRED',
                message='الإحداثيات مطلوبة',
                request_id=request_id,
            )
            return
        
        message = await self.save_message(
            content=content,
            message_type='location',
            latitude=latitude,
            longitude=longitude
        )
        
        if message:
            serialized = await self.serialize_message(message)
            await self.channel_layer.group_send(
                self.room_group_name,
                {
                    'type': 'chat_message',
                    'message': serialized
                }
            )
            await self.broadcast_new_message_notification(serialized)
            await self.send_ack(
                action=action,
                request_id=request_id,
                data={
                    'message_id': message.id,
                    'order_id': int(self.order_id),
                    'chat_type': self.chat_type,
                },
            )
            return

        await self.send_error_event(
            code='MESSAGE_SAVE_FAILED',
            message='تعذر حفظ رسالة الموقع',
            request_id=request_id,
        )
    
    async def handle_mark_read(self, request_id=None):
        """Mark messages as read for the other participant."""
        marked_count = await self.mark_messages_as_read()
        
        await self.channel_layer.group_send(
            self.room_group_name,
            {
                'type': 'messages_read',
                'order_id': self.order_id,
                'reader_type': self.user_type,
                'count': marked_count,
            }
        )
        await self.broadcast_order_snapshot_update()
        await self.send_ack(
            action='mark_read',
            request_id=request_id,
            data={
                'order_id': int(self.order_id),
                'count': marked_count,
            },
        )
    
    async def handle_typing(self, data):
        """Broadcast the typing indicator."""
        is_typing = data.get('is_typing', False)
        
        await self.channel_layer.group_send(
            self.room_group_name,
            {
                'type': 'typing_indicator',
                'user_type': self.user_type,
                'user_name': await self.get_user_name(),
                'is_typing': is_typing
            }
        )

    async def handle_ring(self, data, request_id=None):
        await _handle_ring_request(
            self,
            data,
            request_id=request_id,
            chat_type=self.chat_type,
        )
    
    # ==================== Event Handlers ====================
    
    async def chat_message(self, event):
        """Send a chat message event to the client."""
        from user.utils import localize_message
        msg_data = dict(event['message'])
        msg_data['content'] = localize_message(None, msg_data.get('content'), lang=getattr(self, 'lang', 'ar'))
        await self.send(text_data=_json_dumps({
            'type': 'chat_message',
            'data': msg_data
        }))
    
    async def messages_read(self, event):
        """Send a read-receipt event to the client."""
        await self.send(text_data=_json_dumps({
            'type': 'messages_read',
            'order_id': event['order_id'],
            'reader_type': event['reader_type'],
            'count': event.get('count', 0),
        }))
    
    async def typing_indicator(self, event):
        """Send a typing event to the client."""
        await self.send(text_data=_json_dumps({
            'type': 'typing',
            'user_type': event['user_type'],
            'user_name': event['user_name'],
            'is_typing': event['is_typing']
        }))

    async def ring(self, event):
        await self.send(text_data=_json_dumps({
            'type': 'ring',
            'data': event['data']
        }))

    async def presence_update(self, event):
        await self.send(text_data=_json_dumps({
            'type': 'presence_update',
            'data': event['data'],
        }))

    async def send_ack(self, action, request_id=None, data=None, message='تم تنفيذ الطلب بنجاح'):
        payload = {
            'type': 'ack',
            'action': action,
            'success': True,
            'data': data or {},
        }
        if request_id is not None:
            payload['request_id'] = request_id
        await self.send(text_data=_json_dumps(_with_localized_message(payload, message, lang=getattr(self, 'lang', None))))

    async def send_error_event(self, code, message, request_id=None, details=None):
        payload = {
            'type': 'error',
            'success': False,
            'code': code,
        }
        if request_id is not None:
            payload['request_id'] = request_id
        if details:
            payload['details'] = details
        await self.send(text_data=_json_dumps(_with_localized_message(payload, message, lang=getattr(self, 'lang', None))))

    async def broadcast_new_message_notification(self, message_payload):
        notification_payload = await self.build_order_message_notification(message_payload)
        if not notification_payload:
            return

        group_names = await self.get_order_channel_targets()
        for group_name in group_names:
            await self.channel_layer.group_send(
                group_name,
                {
                    'type': 'new_message',
                    'data': notification_payload,
                }
            )

        try:
            await sync_to_async(send_order_chat_push_fallback, thread_sensitive=False)(
                int(self.order_id),
                self.chat_type,
                message_payload,
                scope=getattr(self, 'scope', None),
                base_url=getattr(self, 'base_url', None),
            )
        except Exception:
            logger.exception(
                'fcm chat fallback failed for order_id=%s chat_type=%s',
                self.order_id,
                self.chat_type,
            )

    async def broadcast_order_snapshot_update(self):
        order_snapshot = await self.get_order_snapshot()
        if not order_snapshot:
            return

        group_names = await self.get_order_channel_targets()
        for group_name in group_names:
            if group_name.startswith('customer_orders_'):
                continue
            await self.channel_layer.group_send(
                group_name,
                {
                    'type': 'order_update',
                    'data': order_snapshot,
                }
            )

        if self.user_type == 'customer' and self.chat_type == 'shop_customer':
            await self.dispatch_customer_delta_events(
                await self.get_customer_app_order_delta_events(
                    include_order=True,
                    include_shop=True,
                    include_on_way=False,
                    include_history=True,
                )
            )

    async def broadcast_presence_updates(self, presence_state):
        batches = await self.get_customer_presence_broadcast_batches(
            presence_state.get('customer_id'),
            presence_state.get('is_online'),
            presence_state.get('last_seen'),
        )

        for batch in batches:
            for group_name in batch['group_names']:
                await self.channel_layer.group_send(
                    group_name,
                    {
                        'type': 'presence_update',
                        'data': batch['data'],
                    }
                )
    
    # ==================== Database Operations ====================

    @database_sync_to_async
    def get_presence_snapshot(self):
        if self.chat_type == 'driver_customer' and self.user_type == 'customer':
            order = Order.objects.select_related('driver').filter(id=self.order_id).first()
            if not order or not order.driver_id:
                return None
            snapshot = get_driver_presence_snapshot(order.driver_id)
            if snapshot:
                snapshot['order_id'] = order.id
            return snapshot
        return get_order_customer_presence_snapshot(self.order_id)

    @database_sync_to_async
    def register_customer_presence(self, connection_type):
        return mark_customer_websocket_connected(
            customer_id=self.user.id,
            channel_name=self.channel_name,
            connection_type=connection_type,
        )

    @database_sync_to_async
    def unregister_customer_presence(self):
        return mark_customer_websocket_disconnected(self.channel_name)

    @database_sync_to_async
    def register_driver_presence(self, connection_type):
        return mark_driver_connected(
            self.user.id,
            self.channel_name,
            connection_type=connection_type,
        )

    @database_sync_to_async
    def unregister_driver_presence(self):
        return mark_driver_disconnected(self.channel_name)

    @database_sync_to_async
    def mark_driver_presence_timed_out(self):
        return mark_driver_connection_timed_out(
            self.channel_name,
            timeout_seconds=DRIVER_PRESENCE_TIMEOUT_SECONDS,
        )

    @database_sync_to_async
    def _touch_driver_presence(self):
        return touch_driver_presence(self.channel_name, self.user.id)

    @database_sync_to_async
    def broadcast_driver_presence(self):
        return broadcast_driver_presence_update(self.user.id)

    @database_sync_to_async
    def get_customer_presence_broadcast_batches(self, customer_id, is_online, last_seen):
        return build_customer_presence_broadcast_batches(customer_id, is_online, last_seen)
    
    @database_sync_to_async
    def check_order_access(self, user, user_type):
        """Check whether the current user can access the order."""
        try:
            order = Order.objects.get(id=self.order_id)

            if self.chat_type == 'driver_customer':
                if user_type == 'driver':
                    return order.driver_id == user.id and has_driver_accepted(order)
                if user_type == 'customer':
                    return order.customer_id == user.id and has_driver_accepted(order)
                return False
            
            if user_type == 'shop_owner':
                return order.shop_owner_id == user.id
            elif user_type == 'employee':
                return order.shop_owner_id == user.shop_owner_id
            elif user_type == 'driver':
                return order.driver_id == user.id
            elif user_type == 'customer':
                return order.customer_id == user.id
            
            return False
        except Order.DoesNotExist:
            return False
    
    @database_sync_to_async
    def save_message(self, content, message_type='text', latitude=None, longitude=None):
        """Persist a chat message in the database."""
        try:
            order = Order.objects.get(id=self.order_id)
            
            # Determine the concrete sender field based on the user type.
            sender_kwargs = {
                'sender_type': self.user_type,
            }
            
            if self.user_type == 'customer':
                sender_kwargs['sender_customer'] = self.user
            elif self.user_type == 'shop_owner':
                sender_kwargs['sender_shop_owner'] = self.user
            elif self.user_type == 'employee':
                sender_kwargs['sender_employee'] = self.user
            elif self.user_type == 'driver':
                sender_kwargs['sender_driver'] = self.user
            
            message = ChatMessage.objects.create(
                order=order,
                chat_type=self.chat_type,
                message_type=message_type,
                content=content,
                latitude=latitude,
                longitude=longitude,
                **sender_kwargs
            )
            
            # Keep the unread counter in sync for the shop side.
            if self.user_type == 'customer':
                order.unread_messages_count = order.messages.filter(
                    chat_type='shop_customer',
                    is_read=False,
                    sender_type='customer'
                ).count()
                order.save()
            
            return message
            
        except Exception as e:
            print(f"[ChatConsumer.save_message] error: {e}")
            return None
    
    @database_sync_to_async
    def get_previous_messages(self):
        """Return recent chat history for the current room."""
        try:
            messages = list(
                ChatMessage.objects
                .filter(order_id=self.order_id, chat_type=self.chat_type)
                .select_related('sender_customer', 'sender_shop_owner', 'sender_employee', 'sender_driver')
                .order_by('-created_at')[:50]
            )
            messages.reverse()

            context = _serializer_context(
                lang=self.lang,
                scope=getattr(self, 'scope', None),
                base_url=getattr(self, 'base_url', None),
            )
            result = []
            for msg in messages:
                serialized = ChatMessageSerializer(msg, context=context).data
                result.append({
                    'id': serialized.get('id'),
                    'order_id': msg.order_id,
                    'chat_type': serialized.get('chat_type'),
                    'sender_type': serialized.get('sender_type'),
                    'sender_name': serialized.get('sender_name'),
                    'sender_id': self._get_sender_id(msg),
                    'message_type': serialized.get('message_type'),
                    'content': serialized.get('content'),
                    'latitude': serialized.get('latitude'),
                    'longitude': serialized.get('longitude'),
                    'invoice': serialized.get('invoice'),
                    'is_read': serialized.get('is_read'),
                    'created_at': serialized.get('created_at'),
                    'audio_file_url': serialized.get('audio_file_url'),
                    'image_file_url': serialized.get('image_file_url'),
                })
            return result
        except Exception as e:
            print(f"[ChatConsumer.get_previous_messages] error: {e}")
            return []
    
    @database_sync_to_async
    def serialize_message(self, message):
        """Serialize a chat message for WebSocket delivery."""
        serialized = ChatMessageSerializer(
            message,
            context=_serializer_context(lang=self.lang, scope=getattr(self, 'scope', None), base_url=getattr(self, 'base_url', None))
        ).data
        return {
            'id': serialized.get('id'),
            'order_id': message.order_id,
            'chat_type': serialized.get('chat_type'),
            'sender_type': serialized.get('sender_type'),
            'sender_name': serialized.get('sender_name'),
            'sender_id': self._get_sender_id(message),
            'message_type': serialized.get('message_type'),
            'content': serialized.get('content'),
            'latitude': serialized.get('latitude'),
            'longitude': serialized.get('longitude'),
            'invoice': serialized.get('invoice'),
            'is_read': serialized.get('is_read'),
            'created_at': serialized.get('created_at'),
            'audio_file_url': serialized.get('audio_file_url'),
            'image_file_url': serialized.get('image_file_url'),
        }
    
    @database_sync_to_async
    def mark_messages_as_read(self):
        """Mark unread room messages as read."""
        try:
            order = Order.objects.get(id=self.order_id)
            
            # Mark only messages sent by the other participant.
            marked_count = ChatMessage.objects.filter(
                order=order,
                chat_type=self.chat_type,
                is_read=False
            ).exclude(sender_type=self.user_type).update(is_read=True)
            
            # Recalculate the unread counter for the shop side.
            if self.user_type in ['shop_owner', 'employee']:
                order.unread_messages_count = order.messages.filter(
                    chat_type='shop_customer',
                    is_read=False,
                    sender_type='customer'
                ).count()
                order.save()

            return marked_count
                
        except Exception as e:
            print(f"[ChatConsumer.mark_messages_as_read] error: {e}")
            return 0
    
    @database_sync_to_async
    def get_user_name(self):
        """Return the display name for the connected user."""
        if self.user_type == 'customer':
            return self.user.name
        elif self.user_type == 'shop_owner':
            return self.user.owner_name
        elif self.user_type == 'employee':
            return self.user.name
        elif self.user_type == 'driver':
            return self.user.name
        return 'غير معروف'

    @database_sync_to_async
    def get_order_channel_targets(self):
        try:
            order = Order.objects.get(id=self.order_id)
        except Order.DoesNotExist:
            return []

        group_names = set()
        if self.chat_type == 'shop_customer':
            if order.shop_owner_id:
                group_names.add(f'shop_orders_{order.shop_owner_id}')
            if order.customer_id:
                group_names.add(f'customer_orders_{order.customer_id}')
        elif self.chat_type == 'driver_customer':
            if order.customer_id:
                group_names.add(f'customer_orders_{order.customer_id}')
            if order.driver_id:
                group_names.add(f'driver_{order.driver_id}')

        return list(group_names)

    @database_sync_to_async
    def build_order_message_notification(self, message_payload):
        try:
            order = Order.objects.select_related('customer', 'employee', 'driver').get(id=self.order_id)
        except Order.DoesNotExist:
            return None

        return {
            'order_id': order.id,
            'order_number': order.order_number,
            'chat_type': self.chat_type,
            'message': message_payload,
            'order': OrderSerializer(
                order,
                context=_serializer_context(scope=getattr(self, 'scope', None), base_url=getattr(self, 'base_url', None))
            ).data,
        }

    @database_sync_to_async
    def get_order_snapshot(self):
        try:
            order = Order.objects.select_related('customer', 'employee', 'driver').get(id=self.order_id)
        except Order.DoesNotExist:
            return None
        return OrderSerializer(
            order,
            context=_serializer_context(scope=getattr(self, 'scope', None), base_url=getattr(self, 'base_url', None))
        ).data

    @database_sync_to_async
    def get_customer_app_order_delta_events(self, include_order, include_shop, include_on_way, include_history):
        customer_id = self.user.id if self.user_type == 'customer' else None
        if customer_id is None:
            order = Order.objects.only('customer_id').filter(id=self.order_id).first()
            customer_id = getattr(order, 'customer_id', None)
        if not customer_id:
            return []
        return build_order_delta_events(
            customer_id,
            int(self.order_id),
            include_order=include_order,
            include_shop=include_shop,
            include_on_way=include_on_way,
            include_history=include_history,
            lang=getattr(self, 'lang', None),
            scope=getattr(self, 'scope', None),
            base_url=getattr(self, 'base_url', None),
        )

    async def dispatch_customer_delta_events(self, events):
        customer_group = None
        for group_name in await self.get_order_channel_targets():
            if group_name.startswith('customer_orders_'):
                customer_group = group_name
                break

        if not customer_group:
            return

        for event in events or []:
            await self.channel_layer.group_send(
                customer_group,
                {
                    'type': event['type'],
                    'data': event['data'],
                }
            )

    def _get_sender_id(self, message):
        if message.sender_type == 'customer' and message.sender_customer_id:
            return message.sender_customer_id
        if message.sender_type == 'shop_owner' and message.sender_shop_owner_id:
            return message.sender_shop_owner_id
        if message.sender_type == 'employee' and message.sender_employee_id:
            return message.sender_employee_id
        if message.sender_type == 'driver' and message.sender_driver_id:
            return message.sender_driver_id
        return None


class SupportChatConsumer(AsyncWebsocketConsumer):
    """
    Standalone support chat between customer and shop without an order.

    Allowed users:
    - customer <-> shop_owner
    - customer <-> employee

    URL: ws://server/ws/chat/support/{conversation_id}/?token=JWT_TOKEN
    """

    async def connect(self):
        try:
            self.conversation_id = self.scope['url_route']['kwargs']['conversation_id']
            query_string = self.scope.get('query_string', b'').decode('utf-8')
            self.lang = 'ar'
            if 'lang=' in query_string:
                self.lang = query_string.split('lang=')[-1].split('&')[0]

            self.chat_type = 'support_customer'
            self.room_group_name = f'support_chat_{self.conversation_id}'
            self.base_url = resolve_base_url(scope=self.scope)

            user = self.scope.get('user')
            user_type = self.scope.get('user_type')
            if not user or not user_type:
                await self.close(code=4401)
                return
            self.user = user
            self.user_type = user_type
            if not await ensure_socket_account_active(self, refresh=True, accept_if_needed=True):
                return

            has_access = await self.check_conversation_access(user, user_type)
            if not has_access:
                await self.close(code=4403)
                return

            if user_type not in ['customer', 'shop_owner', 'employee']:
                await self.close(code=4403)
                return

            self.customer_presence_registered = False

            await self.channel_layer.group_add(self.room_group_name, self.channel_name)
            await self.accept()

            if self.user_type == 'customer':
                presence_state = await self.register_customer_presence('support_chat')
                self.customer_presence_registered = bool(presence_state)

            conversation = await self.get_conversation()
            await self.send(text_data=_json_dumps(_with_localized_message(
                {
                    'type': 'connection',
                    'thread_id': self.conversation_id,
                    'support_conversation_id': self.conversation_id,
                    'chat_type': self.chat_type,
                    'conversation_type': conversation.conversation_type if conversation else None,
                    'user_type': self.user_type,
                },
                'تم الاتصال بنجاح',
                lang=self.lang,
            )))

            previous_messages = await self.get_previous_messages()
            await self.send(text_data=_json_dumps({
                'type': 'previous_messages',
                'messages': previous_messages,
            }))

        except Exception as e:
            print(f"[SupportChatConsumer.connect] error: {e}")
            await self.close(code=1011)
            if hasattr(self, 'room_group_name'):
                await self.channel_layer.group_discard(self.room_group_name, self.channel_name)

    async def disconnect(self, close_code):
        if hasattr(self, 'room_group_name'):
            await self.channel_layer.group_discard(self.room_group_name, self.channel_name)

        if getattr(self, 'customer_presence_registered', False):
            await self.unregister_customer_presence()

    async def receive(self, text_data):
        try:
            if not await ensure_socket_account_active(self, refresh=True):
                return
            data = json.loads(text_data)
            event_type = data.get('type', 'chat_message')
            request_id = data.get('request_id')

            if event_type in ['chat_message', 'send_message']:
                if data.get('message_type') == 'location':
                    await self.handle_location(data, request_id=request_id, action=event_type)
                else:
                    await self.handle_chat_message(data, request_id=request_id, action=event_type)
            elif event_type == 'mark_read':
                await self.handle_mark_read(request_id=request_id)
            elif event_type == 'typing':
                await self.handle_typing(data)
            elif event_type == 'location':
                await self.handle_location(data, request_id=request_id, action=event_type)
            elif event_type in {'ping', 'presence_ping'}:
                await self.send(text_data=_json_dumps({
                    'type': 'pong',
                    'request_id': request_id,
                    'sent_at': format_utc_iso8601(timezone.now()),
                }))
            else:
                await self.send_error_event(
                    code='UNKNOWN_EVENT',
                    message='نوع الحدث غير مدعوم',
                    request_id=request_id,
                    details={'type': event_type},
                )
        except json.JSONDecodeError:
            await self.send_error_event(
                code='INVALID_JSON',
                message='تنسيق البيانات غير صحيح',
            )
        except Exception as e:
            print(f"[SupportChatConsumer.receive] error: {e}")
            await self.send_error_event(
                code='UNEXPECTED_ERROR',
                message='حدث خطأ غير متوقع',
                details={'error_detail': str(e)},
            )

    async def handle_chat_message(self, data, request_id=None, action='chat_message'):
        content = data.get('content', '')
        msg_type = data.get('message_type', 'text')

        if msg_type not in ['text', 'location']:
            await self.send_error_event(
                code='UNSUPPORTED_MESSAGE_TYPE',
                message='هذا النوع من الرسائل غير مدعوم عبر الـ WebSocket',
                request_id=request_id,
                details={'message_type': msg_type},
            )
            return

        if msg_type == 'text' and not content:
            await self.send_error_event(
                code='MESSAGE_CONTENT_REQUIRED',
                message='محتوى الرسالة مطلوب',
                request_id=request_id,
            )
            return

        message = await self.save_message(
            content=content,
            message_type=msg_type,
            latitude=data.get('latitude'),
            longitude=data.get('longitude'),
        )
        if not message:
            await self.send_error_event(
                code='MESSAGE_SAVE_FAILED',
                message='تعذر حفظ الرسالة',
                request_id=request_id,
            )
            return

        serialized = await self.serialize_message(message)
        await self.channel_layer.group_send(
            self.room_group_name,
            {
                'type': 'chat_message',
                'message': serialized,
            }
        )
        await self.broadcast_support_message_notification(serialized)
        await self.send_ack(
            action=action,
            request_id=request_id,
            data={
                'message_id': message.id,
                'thread_id': self.conversation_id,
                'support_conversation_id': self.conversation_id,
                'chat_type': self.chat_type,
            },
        )

    async def handle_location(self, data, request_id=None, action='location'):
        latitude = data.get('latitude')
        longitude = data.get('longitude')
        content = data.get('content', 'موقعي الحالي')

        if latitude is None or longitude is None:
            await self.send_error_event(
                code='LOCATION_COORDINATES_REQUIRED',
                message='الإحداثيات مطلوبة',
                request_id=request_id,
            )
            return

        message = await self.save_message(
            content=content,
            message_type='location',
            latitude=latitude,
            longitude=longitude,
        )
        if not message:
            await self.send_error_event(
                code='MESSAGE_SAVE_FAILED',
                message='تعذر حفظ رسالة الموقع',
                request_id=request_id,
            )
            return

        serialized = await self.serialize_message(message)
        await self.channel_layer.group_send(
            self.room_group_name,
            {
                'type': 'chat_message',
                'message': serialized,
            }
        )
        await self.broadcast_support_message_notification(serialized)
        await self.send_ack(
            action=action,
            request_id=request_id,
            data={
                'message_id': message.id,
                'thread_id': self.conversation_id,
                'support_conversation_id': self.conversation_id,
                'chat_type': self.chat_type,
            },
        )

    async def handle_mark_read(self, request_id=None):
        marked_count = await self.mark_messages_as_read()
        await self.channel_layer.group_send(
            self.room_group_name,
            {
                'type': 'messages_read',
                'support_conversation_id': self.conversation_id,
                'reader_type': self.user_type,
                'count': marked_count,
            }
        )
        await self.broadcast_conversation_update()
        await self.send_ack(
            action='mark_read',
            request_id=request_id,
            data={
                'thread_id': self.conversation_id,
                'support_conversation_id': self.conversation_id,
                'count': marked_count,
            },
        )

    async def handle_typing(self, data):
        is_typing = data.get('is_typing', False)
        await self.channel_layer.group_send(
            self.room_group_name,
            {
                'type': 'typing_indicator',
                'user_type': self.user_type,
                'user_name': await self.get_user_name(),
                'is_typing': is_typing,
            }
        )

    async def chat_message(self, event):
        from user.utils import localize_message
        msg_data = dict(event['message'])
        msg_data['content'] = localize_message(None, msg_data.get('content'), lang=getattr(self, 'lang', 'ar'))
        await self.send(text_data=_json_dumps({
            'type': 'chat_message',
            'data': msg_data,
        }))

    async def messages_read(self, event):
        await self.send(text_data=_json_dumps({
            'type': 'messages_read',
            'thread_id': event['support_conversation_id'],
            'support_conversation_id': event['support_conversation_id'],
            'reader_type': event['reader_type'],
            'count': event.get('count', 0),
        }))

    async def typing_indicator(self, event):
        await self.send(text_data=_json_dumps({
            'type': 'typing',
            'user_type': event['user_type'],
            'user_name': event['user_name'],
            'is_typing': event['is_typing'],
        }))

    async def send_ack(self, action, request_id=None, data=None, message='تم تنفيذ الطلب بنجاح'):
        payload = {
            'type': 'ack',
            'action': action,
            'success': True,
            'data': data or {},
        }
        if request_id is not None:
            payload['request_id'] = request_id
        await self.send(text_data=_json_dumps(_with_localized_message(payload, message, lang=getattr(self, 'lang', None))))

    async def send_error_event(self, code, message, request_id=None, details=None):
        payload = {
            'type': 'error',
            'success': False,
            'code': code,
        }
        if request_id is not None:
            payload['request_id'] = request_id
        if details:
            payload['details'] = details
        await self.send(text_data=_json_dumps(_with_localized_message(payload, message, lang=getattr(self, 'lang', None))))

    async def broadcast_support_message_notification(self, message_payload):
        notification_payload = await self.build_support_message_notification(message_payload)
        if not notification_payload:
            return

        shop_owner_id, customer_id = await self.get_support_notification_targets()
        if shop_owner_id:
            await self.channel_layer.group_send(
                f'shop_orders_{shop_owner_id}',
                {
                    'type': 'support_message',
                    'data': notification_payload,
                }
            )

        if customer_id:
            await self.dispatch_customer_support_delta_events(
                await self.get_customer_support_delta_events(
                    include_shop=True,
                    include_history=True,
                )
            )

    async def broadcast_conversation_update(self):
        conversation_payload = await self.serialize_conversation()
        if not conversation_payload:
            return

        shop_owner_id, customer_id = await self.get_support_notification_targets()
        if shop_owner_id:
            await self.channel_layer.group_send(
                f'shop_orders_{shop_owner_id}',
                {
                    'type': 'support_conversation_update',
                    'data': conversation_payload,
                }
            )

        if customer_id and self.user_type == 'customer':
            await self.dispatch_customer_support_delta_events(
                await self.get_customer_support_delta_events(
                    include_shop=True,
                    include_history=True,
                )
            )

    @database_sync_to_async
    def get_conversation(self):
        return (
            CustomerSupportConversation.objects
            .select_related('shop_owner', 'customer')
            .filter(public_id=self.conversation_id)
            .first()
        )

    @database_sync_to_async
    def register_customer_presence(self, connection_type):
        return mark_customer_websocket_connected(
            customer_id=self.user.id,
            channel_name=self.channel_name,
            connection_type=connection_type,
        )

    @database_sync_to_async
    def unregister_customer_presence(self):
        return mark_customer_websocket_disconnected(self.channel_name)

    @database_sync_to_async
    def check_conversation_access(self, user, user_type):
        conversation = (
            CustomerSupportConversation.objects
            .select_related('shop_owner', 'customer')
            .filter(public_id=self.conversation_id)
            .first()
        )
        if not conversation:
            return False
        if user_type == 'shop_owner':
            return conversation.shop_owner_id == user.id
        if user_type == 'employee':
            return conversation.shop_owner_id == getattr(user, 'shop_owner_id', None)
        if user_type == 'customer':
            return conversation.customer_id == user.id
        return False

    @database_sync_to_async
    def save_message(self, content, message_type='text', latitude=None, longitude=None):
        try:
            conversation = CustomerSupportConversation.objects.get(public_id=self.conversation_id)
            sender_kwargs = {'sender_type': self.user_type}
            if self.user_type == 'customer':
                sender_kwargs['sender_customer'] = self.user
            elif self.user_type == 'shop_owner':
                sender_kwargs['sender_shop_owner'] = self.user
            elif self.user_type == 'employee':
                sender_kwargs['sender_employee'] = self.user
            else:
                return None

            message = CustomerSupportMessage.objects.create(
                conversation=conversation,
                message_type=message_type,
                content=content,
                latitude=latitude,
                longitude=longitude,
                **sender_kwargs,
            )

            preview = content
            if not preview:
                if message_type == 'audio':
                    preview = 'رسالة صوتية'
                elif message_type == 'image':
                    preview = 'صورة'
                elif message_type == 'location':
                    preview = 'موقع'

            conversation.last_message_preview = preview
            conversation.last_message_at = message.created_at
            conversation.unread_for_shop_count = conversation.messages.filter(
                is_read=False,
                sender_type='customer',
            ).count()
            conversation.unread_for_customer_count = conversation.messages.filter(
                is_read=False,
            ).exclude(sender_type='customer').count()
            conversation.save(update_fields=[
                'last_message_preview',
                'last_message_at',
                'unread_for_shop_count',
                'unread_for_customer_count',
                'updated_at',
            ])
            return message
        except Exception as e:
            print(f"[SupportChatConsumer.save_message] error: {e}")
            return None

    @database_sync_to_async
    def get_previous_messages(self):
        try:
            messages = CustomerSupportMessage.objects.filter(
                conversation__public_id=self.conversation_id,
            ).order_by('created_at')[:50]

            result = []
            for msg in messages:
                serialized = CustomerSupportMessageSerializer(
                    msg,
                    context=_serializer_context(lang=self.lang, scope=getattr(self, 'scope', None), base_url=getattr(self, 'base_url', None))
                ).data
                result.append({
                    'id': serialized.get('id'),
                    'thread_id': serialized.get('thread_id'),
                    'support_conversation_id': serialized.get('support_conversation_id'),
                    'chat_type': serialized.get('chat_type'),
                    'conversation_type': serialized.get('conversation_type'),
                    'conversation_type_display': serialized.get('conversation_type_display'),
                    'sender_type': serialized.get('sender_type'),
                    'sender_name': serialized.get('sender_name'),
                    'sender_id': serialized.get('sender_id'),
                    'message_type': serialized.get('message_type'),
                    'content': serialized.get('content'),
                    'latitude': serialized.get('latitude'),
                    'longitude': serialized.get('longitude'),
                    'is_read': serialized.get('is_read'),
                    'created_at': serialized.get('created_at'),
                    'audio_file_url': serialized.get('audio_file_url'),
                    'image_file_url': serialized.get('image_file_url'),
                })
            return result
        except Exception as e:
            print(f"[SupportChatConsumer.get_previous_messages] error: {e}")
            return []

    @database_sync_to_async
    def serialize_message(self, message):
        serialized = CustomerSupportMessageSerializer(
            message,
            context=_serializer_context(lang=self.lang, scope=getattr(self, 'scope', None), base_url=getattr(self, 'base_url', None))
        ).data
        return {
            'id': serialized.get('id'),
            'thread_id': serialized.get('thread_id'),
            'support_conversation_id': serialized.get('support_conversation_id'),
            'chat_type': serialized.get('chat_type'),
            'conversation_type': serialized.get('conversation_type'),
            'conversation_type_display': serialized.get('conversation_type_display'),
            'sender_type': serialized.get('sender_type'),
            'sender_name': serialized.get('sender_name'),
            'sender_id': serialized.get('sender_id'),
            'message_type': serialized.get('message_type'),
            'content': serialized.get('content'),
            'latitude': serialized.get('latitude'),
            'longitude': serialized.get('longitude'),
            'is_read': serialized.get('is_read'),
            'created_at': serialized.get('created_at'),
            'audio_file_url': serialized.get('audio_file_url'),
            'image_file_url': serialized.get('image_file_url'),
        }

    @database_sync_to_async
    def mark_messages_as_read(self):
        try:
            conversation = CustomerSupportConversation.objects.get(public_id=self.conversation_id)
            marked_count = CustomerSupportMessage.objects.filter(
                conversation=conversation,
                is_read=False,
            ).exclude(sender_type=self.user_type).update(is_read=True)

            conversation.unread_for_shop_count = conversation.messages.filter(
                is_read=False,
                sender_type='customer',
            ).count()
            conversation.unread_for_customer_count = conversation.messages.filter(
                is_read=False,
            ).exclude(sender_type='customer').count()
            conversation.save(update_fields=[
                'unread_for_shop_count',
                'unread_for_customer_count',
                'updated_at',
            ])
            return marked_count
        except Exception as e:
            print(f"[SupportChatConsumer.mark_messages_as_read] error: {e}")
            return 0

    @database_sync_to_async
    def get_user_name(self):
        if self.user_type == 'customer':
            return self.user.name
        if self.user_type == 'shop_owner':
            return self.user.owner_name
        if self.user_type == 'employee':
            return self.user.name
        return 'غير معروف'

    @database_sync_to_async
    def get_support_notification_targets(self):
        conversation = (
            CustomerSupportConversation.objects
            .filter(public_id=self.conversation_id)
            .only('shop_owner_id', 'customer_id')
            .first()
        )
        if not conversation:
            return None, None
        return conversation.shop_owner_id, conversation.customer_id

    @database_sync_to_async
    def build_support_message_notification(self, message_payload):
        conversation = (
            CustomerSupportConversation.objects
            .select_related('shop_owner', 'customer')
            .filter(public_id=self.conversation_id)
            .first()
        )
        if not conversation:
            return None

        conversation_payload = CustomerSupportConversationSerializer(
            conversation,
            context=_serializer_context(scope=getattr(self, 'scope', None), base_url=getattr(self, 'base_url', None))
        ).data
        return {
            'thread_id': conversation.public_id,
            'support_conversation_id': conversation.public_id,
            'chat_type': self.chat_type,
            'conversation_type': conversation.conversation_type,
            'message': message_payload,
            'conversation': conversation_payload,
            'shop_id': conversation.shop_owner_id,
            'shop_name': conversation.shop_owner.shop_name,
            'customer_id': conversation.customer_id,
            'customer_name': conversation.customer.name,
            'customer_profile_image_url': conversation_payload.get('customer_profile_image_url'),
            'customer': conversation_payload.get('customer'),
        }

    @database_sync_to_async
    def serialize_conversation(self):
        conversation = (
            CustomerSupportConversation.objects
            .select_related('shop_owner', 'customer')
            .filter(public_id=self.conversation_id)
            .first()
        )
        if not conversation:
            return None
        return CustomerSupportConversationSerializer(
            conversation,
            context=_serializer_context(scope=getattr(self, 'scope', None), base_url=getattr(self, 'base_url', None))
        ).data

    @database_sync_to_async
    def get_customer_support_delta_events(self, include_shop, include_history):
        customer_id = self.user.id if self.user_type == 'customer' else None
        if customer_id is None:
            conversation = (
                CustomerSupportConversation.objects
                .only('customer_id')
                .filter(public_id=self.conversation_id)
                .first()
            )
            customer_id = getattr(conversation, 'customer_id', None)
        if not customer_id:
            return []
        return build_support_delta_events(
            customer_id,
            self.conversation_id,
            include_shop=include_shop,
            include_history=include_history,
            lang=getattr(self, 'lang', None),
            scope=getattr(self, 'scope', None),
            base_url=getattr(self, 'base_url', None),
        )

    async def dispatch_customer_support_delta_events(self, events):
        shop_owner_id, customer_id = await self.get_support_notification_targets()
        if not customer_id:
            return

        customer_group = f'customer_orders_{customer_id}'
        for event in events or []:
            await self.channel_layer.group_send(
                customer_group,
                {
                    'type': event['type'],
                    'data': event['data'],
                }
            )


class OrderConsumer(AsyncWebsocketConsumer):
    """
    WebSocket consumer for shop order updates.
    """

    async def connect(self):
        self.shop_owner_id = self.scope['url_route']['kwargs'].get('shop_owner_id')
        self.room_group_name = f'shop_orders_{self.shop_owner_id}'
        self.base_url = resolve_base_url(scope=self.scope)

        query_string = self.scope.get('query_string', b'').decode('utf-8')
        self.lang = 'ar'
        if 'lang=' in query_string:
            self.lang = query_string.split('lang=')[-1].split('&')[0]

        user = self.scope.get('user')
        user_type = self.scope.get('user_type')

        if not user:
            await self.close(code=4401)
            return
        self.user = user
        self.user_type = user_type
        if not await ensure_socket_account_active(self, refresh=True, accept_if_needed=True):
            return

        if user_type == 'shop_owner' and user.id != int(self.shop_owner_id):
            await self.close(code=4403)
            return

        if user_type == 'employee' and user.shop_owner_id != int(self.shop_owner_id):
            await self.close(code=4403)
            return

        if user_type not in ['shop_owner', 'employee']:
            await self.close(code=4403)
            return

        await self.channel_layer.group_add(self.room_group_name, self.channel_name)
        await self.accept()

        await self.send(text_data=_json_dumps(_with_localized_message(
            {
                'type': 'connection',
                'shop_owner_id': self.shop_owner_id,
            },
            'تم الاتصال بنجاح',
            lang=self.lang,
        )))

        await self.send_shop_dashboard_snapshots()

    async def disconnect(self, close_code):
        if hasattr(self, 'room_group_name'):
            await self.channel_layer.group_discard(self.room_group_name, self.channel_name)

    async def receive(self, text_data):
        try:
            if not await ensure_socket_account_active(self, refresh=True):
                return
            data = json.loads(text_data)
            event_type = data.get('type')
            request_id = data.get('request_id')

            if event_type == 'ring':
                await _handle_ring_request(self, data, request_id=request_id)
            elif event_type in {'sync_dashboard', 'refresh_dashboard'}:
                await self.send_shop_dashboard_snapshots()
                await _send_ack(
                    self,
                    'sync_dashboard',
                    request_id=request_id,
                    message='تمت مزامنة بيانات المحل بنجاح',
                )
            elif event_type in {'sync_portfolio', 'refresh_portfolio'}:
                await self.send_shop_portfolio_snapshot()
                await _send_ack(
                    self,
                    'sync_portfolio',
                    request_id=request_id,
                    message='تمت مزامنة معرض الأعمال بنجاح',
                )
            else:
                await _send_error_event(
                    self,
                    code='UNKNOWN_EVENT',
                    message='نوع الحدث غير مدعوم',
                    request_id=request_id,
                    details={'type': event_type},
                )
        except json.JSONDecodeError:
            await _send_error_event(
                self,
                code='INVALID_JSON',
                message='تنسيق البيانات غير صحيح',
            )
        except Exception as e:
            print(f"[OrderConsumer.receive] error: {e}")
            await _send_error_event(
                self,
                code='UNEXPECTED_ERROR',
                message='حدث خطأ غير متوقع',
                details={'error_detail': str(e)},
            )

    async def order_update(self, event):
        await self.send(text_data=_json_dumps({
            'type': 'order_update',
            'data': event['data'],
        }))

    async def new_order(self, event):
        await self.send(text_data=_json_dumps({
            'type': 'new_order',
            'data': event['data'],
        }))

    async def new_message(self, event):
        from user.utils import localize_message
        notif_data = dict(event['data'])
        if 'message' in notif_data and isinstance(notif_data['message'], dict):
            notif_data['message'] = dict(notif_data['message'])
            notif_data['message']['content'] = localize_message(
                None, notif_data['message'].get('content'), lang=getattr(self, 'lang', 'ar')
            )
        await self.send(text_data=_json_dumps({
            'type': 'new_message',
            'data': notif_data,
        }))

    async def support_conversation_update(self, event):
        await self.send(text_data=_json_dumps({
            'type': 'support_conversation_update',
            'data': event['data'],
        }))

    async def support_message(self, event):
        from user.utils import localize_message
        notif_data = dict(event['data'])
        if 'message' in notif_data and isinstance(notif_data['message'], dict):
            notif_data['message'] = dict(notif_data['message'])
            notif_data['message']['content'] = localize_message(
                None, notif_data['message'].get('content'), lang=getattr(self, 'lang', 'ar')
            )
        await self.send(text_data=_json_dumps({
            'type': 'support_message',
            'data': notif_data,
        }))

    async def store_status_updated(self, event):
        await self.send(text_data=_json_dumps({
            'type': 'store_status_updated',
            'data': event['data'],
        }))

    async def driver_status_updated(self, event):
        await self.send(text_data=_json_dumps({
            'type': 'driver_status_updated',
            'data': event['data'],
        }))

    async def ring(self, event):
        await self.send(text_data=_json_dumps({
            'type': 'ring',
            'data': event['data'],
        }))

    async def presence_update(self, event):
        await self.send(text_data=_json_dumps({
            'type': 'presence_update',
            'data': event['data'],
        }))

    async def shop_portfolio_snapshot(self, event):
        await self.send(text_data=_json_dumps({
            'type': 'shop_portfolio_snapshot',
            'data': event['data'],
        }))

    async def send_shop_dashboard_snapshots(self):
        orders_snapshot = await self.get_orders_snapshot()
        await self.send(text_data=_json_dumps(_with_localized_message(
            {
                'type': 'orders_snapshot',
                'data': {
                    'orders': orders_snapshot,
                },
            },
            'تمت مزامنة قائمة الطلبات بنجاح',
            lang=self.lang,
        )))

        support_conversations = await self.get_support_conversations_snapshot()
        for conversation in support_conversations:
            await self.send(text_data=_json_dumps({
                'type': 'support_conversation_update',
                'data': conversation,
            }))

        await self.send_shop_portfolio_snapshot()

    async def send_shop_portfolio_snapshot(self):
        portfolio_snapshot = await self.get_shop_portfolio_snapshot()
        await self.send(text_data=_json_dumps(_with_localized_message(
            {
                'type': 'shop_portfolio_snapshot',
                'data': portfolio_snapshot,
            },
            'تمت مزامنة معرض الأعمال بنجاح',
            lang=self.lang,
        )))

    @database_sync_to_async
    def get_orders_snapshot(self):
        orders = (
            Order.objects
            .filter(shop_owner_id=self.shop_owner_id)
            .select_related('customer', 'employee', 'driver')
            .order_by('-updated_at')[:50]
        )
        return OrderSerializer(
            orders,
            many=True,
            context=_serializer_context(scope=getattr(self, 'scope', None), base_url=getattr(self, 'base_url', None))
        ).data

    @database_sync_to_async
    def get_support_conversations_snapshot(self):
        conversations = (
            CustomerSupportConversation.objects
            .filter(shop_owner_id=self.shop_owner_id)
            .select_related('shop_owner', 'customer')
            .order_by('-updated_at', '-created_at')
        )
        return CustomerSupportConversationSerializer(
            conversations,
            many=True,
            context=_serializer_context(
                lang=getattr(self, 'lang', None),
                scope=getattr(self, 'scope', None),
                base_url=getattr(self, 'base_url', None),
            ),
        ).data

    @database_sync_to_async
    def get_shop_portfolio_snapshot(self):
        shop_owner = ShopOwner.objects.filter(id=self.shop_owner_id).first()
        if not shop_owner:
            return {}
        return build_shop_portfolio_snapshot(
            shop_owner,
            viewer_user=getattr(self, 'user', None),
        )


class CustomerOrderConsumer(AsyncWebsocketConsumer):
    """
    WebSocket consumer for customer order updates.
    """

    async def connect(self):
        self.customer_id = int(self.scope['url_route']['kwargs'].get('customer_id'))
        self.room_group_name = f'customer_orders_{self.customer_id}'
        self.base_url = resolve_base_url(scope=self.scope)

        query_string = self.scope.get('query_string', b'').decode('utf-8')
        self.lang = 'ar'
        if 'lang=' in query_string:
            self.lang = query_string.split('lang=')[-1].split('&')[0]

        user = self.scope.get('user')
        user_type = self.scope.get('user_type')

        if not user or user_type != 'customer':
            await self.reject_connection(
                close_code=4401,
                error_code='AUTHENTICATION_FAILED',
                message='Authentication failed for customer realtime channel.',
            )
            return
        self.user = user
        self.user_type = user_type
        if not await ensure_socket_account_active(self, refresh=True, accept_if_needed=True):
            return

        if user.id != self.customer_id:
            await self.reject_connection(
                close_code=4403,
                error_code='CUSTOMER_MISMATCH',
                message='The authenticated customer does not match the requested customer_id.',
            )
            return

        self.customer_presence_registered = False

        await self.channel_layer.group_add(self.room_group_name, self.channel_name)
        await self.accept()

        presence_state = await self.register_customer_presence('orders')
        self.customer_presence_registered = bool(presence_state)

        await self.send(text_data=_json_dumps({
            'type': 'connection',
            'scope': CUSTOMER_APP_REALTIME_SCOPE,
            'customer_id': self.customer_id,
            'message': 'connected',
        }))

        if presence_state and presence_state.get('changed'):
            await self.broadcast_presence_updates(presence_state)

        await self.send_initial_snapshots()

    async def disconnect(self, close_code):
        if hasattr(self, 'room_group_name'):
            await self.channel_layer.group_discard(self.room_group_name, self.channel_name)

        if getattr(self, 'customer_presence_registered', False):
            presence_state = await self.unregister_customer_presence()
            if presence_state and presence_state.get('changed'):
                await self.broadcast_presence_updates(presence_state)

    async def receive(self, text_data):
        try:
            if not await ensure_socket_account_active(self, refresh=True):
                return
            data = json.loads(text_data)
            event_type = data.get('type')
            request_id = data.get('request_id')

            if event_type == 'ring':
                await _handle_ring_request(self, data, request_id=request_id)
            elif event_type in {'sync_dashboard', 'refresh_dashboard', 'refresh_all'}:
                await self.send_initial_snapshots(request_id=request_id)
                if event_type in {'sync_dashboard', 'refresh_dashboard'}:
                    await _send_ack(
                        self,
                        'sync_dashboard',
                        request_id=request_id,
                        message='Customer realtime snapshots refreshed.',
                    )
            elif event_type == 'refresh_orders':
                await self.send_orders_snapshot(request_id=request_id)
            elif event_type == 'refresh_shops':
                await self.send_shops_snapshot(request_id=request_id)
            elif event_type == 'refresh_on_way':
                await self.send_on_way_snapshot(request_id=request_id)
            elif event_type == 'refresh_order_history':
                await self.send_order_history_snapshot(request_id=request_id)
            else:
                await _send_error_event(
                    self,
                    code='UNKNOWN_EVENT',
                    message='Unsupported customer realtime event type.',
                    request_id=request_id,
                    details={'type': event_type},
                )
        except json.JSONDecodeError:
            await _send_error_event(
                self,
                code='INVALID_JSON',
                message='Invalid JSON payload.',
            )
        except Exception as e:
            print(f"[CustomerOrderConsumer.receive] error: {e}")
            await _send_error_event(
                self,
                code='UNEXPECTED_ERROR',
                message='Unexpected customer realtime error.',
                details={'error_detail': str(e)},
            )

    async def order_update(self, event):
        order_id = self._extract_order_id(event.get('data'))
        if not order_id:
            return
        await self.emit_delta_events(
            await self.get_order_delta_events(
                order_id,
                include_order=True,
                include_shop=True,
                include_on_way=True,
                include_history=True,
            )
        )

    async def driver_location(self, event):
        await self.send(text_data=_json_dumps({
            'type': 'driver_location',
            'data': event['data'],
        }))

    async def new_message(self, event):
        payload = event.get('data') or {}
        chat_type = payload.get('chat_type')
        order_id = self._extract_order_id(payload)
        if chat_type != 'shop_customer' or not order_id:
            return
        await self.emit_delta_events(
            await self.get_order_delta_events(
                order_id,
                include_order=True,
                include_shop=True,
                include_on_way=False,
                include_history=True,
            )
        )

    async def support_conversation_update(self, event):
        conversation_id = self._extract_support_conversation_id(event.get('data'))
        if not conversation_id:
            return
        await self.emit_delta_events(
            await self.get_support_delta_events(
                conversation_id,
                include_shop=True,
                include_history=True,
            )
        )

    async def support_message(self, event):
        conversation_id = self._extract_support_conversation_id(event.get('data'))
        if not conversation_id:
            return
        await self.emit_delta_events(
            await self.get_support_delta_events(
                conversation_id,
                include_shop=True,
                include_history=True,
            )
        )

    async def order_upsert(self, event):
        await self.send_realtime_event('order_upsert', event['data'])

    async def order_remove(self, event):
        await self.send_realtime_event('order_remove', event['data'])

    async def shop_upsert(self, event):
        await self.send_realtime_event('shop_upsert', event['data'])

    async def shop_remove(self, event):
        await self.send_realtime_event('shop_remove', event['data'])

    async def on_way_upsert(self, event):
        await self.send_realtime_event('on_way_upsert', event['data'])

    async def on_way_remove(self, event):
        await self.send_realtime_event('on_way_remove', event['data'])

    async def order_history_entry_upsert(self, event):
        await self.send_realtime_event('order_history_entry_upsert', event['data'])

    async def order_history_entry_remove(self, event):
        await self.send_realtime_event('order_history_entry_remove', event['data'])

    async def ring(self, event):
        await self.send(text_data=_json_dumps({
            'type': 'ring',
            'data': event['data'],
        }))

    async def presence_update(self, event):
        await self.send(text_data=_json_dumps({
            'type': 'presence_update',
            'data': event['data'],
        }))

    async def broadcast_presence_updates(self, presence_state):
        batches = await self.get_customer_presence_broadcast_batches(
            presence_state.get('customer_id'),
            presence_state.get('is_online'),
            presence_state.get('last_seen'),
        )

        for batch in batches:
            for group_name in batch['group_names']:
                await self.channel_layer.group_send(
                    group_name,
                    {
                        'type': 'presence_update',
                        'data': batch['data'],
                    }
                )

    async def reject_connection(self, close_code, error_code, message):
        await self.accept()
        await _send_error_event(
            self,
            code=error_code,
            message=message,
        )
        await self.close(code=close_code)

    async def send_realtime_event(self, event_type, data, request_id=None, message=None):
        payload = {
            'type': event_type,
            'data': data,
        }
        if request_id is not None:
            payload['request_id'] = request_id
        if message is not None:
            payload['message'] = message
        await self.send(text_data=_json_dumps(payload))

    async def send_initial_snapshots(self, request_id=None):
        snapshots = await self.get_all_snapshots()
        snapshot_messages = {
            'orders_snapshot': 'orders synced',
            'shops_snapshot': 'shops synced',
            'on_way_snapshot': 'on way synced',
            'order_history_snapshot': 'order history synced',
        }
        for event_type in [
            'orders_snapshot',
            'shops_snapshot',
            'on_way_snapshot',
            'order_history_snapshot',
        ]:
            await self.send_realtime_event(
                event_type,
                snapshots[event_type],
                request_id=request_id,
                message=snapshot_messages[event_type],
            )

    async def send_orders_snapshot(self, request_id=None):
        snapshots = await self.get_all_snapshots()
        await self.send_realtime_event(
            'orders_snapshot',
            snapshots['orders_snapshot'],
            request_id=request_id,
            message='orders synced',
        )

    async def send_shops_snapshot(self, request_id=None):
        snapshots = await self.get_all_snapshots()
        await self.send_realtime_event(
            'shops_snapshot',
            snapshots['shops_snapshot'],
            request_id=request_id,
            message='shops synced',
        )

    async def send_on_way_snapshot(self, request_id=None):
        snapshots = await self.get_all_snapshots()
        await self.send_realtime_event(
            'on_way_snapshot',
            snapshots['on_way_snapshot'],
            request_id=request_id,
            message='on way synced',
        )

    async def send_order_history_snapshot(self, request_id=None):
        snapshots = await self.get_all_snapshots()
        await self.send_realtime_event(
            'order_history_snapshot',
            snapshots['order_history_snapshot'],
            request_id=request_id,
            message='order history synced',
        )

    async def emit_delta_events(self, events):
        for event in events or []:
            await self.send_realtime_event(event['type'], event['data'])

    def _extract_order_id(self, payload):
        if not isinstance(payload, dict):
            return None
        order_id = payload.get('order_id') or payload.get('id')
        order_payload = payload.get('order')
        if not order_id and isinstance(order_payload, dict):
            order_id = order_payload.get('id') or order_payload.get('order_id')
        try:
            return int(order_id) if order_id is not None else None
        except (TypeError, ValueError):
            return None

    def _extract_support_conversation_id(self, payload):
        if not isinstance(payload, dict):
            return None
        return (
            payload.get('support_conversation_id')
            or payload.get('thread_id')
            or payload.get('conversation', {}).get('support_conversation_id')
        )

    @database_sync_to_async
    def get_all_snapshots(self):
        return build_all_snapshots(
            self.customer_id,
            lang=self.lang,
            scope=getattr(self, 'scope', None),
            base_url=getattr(self, 'base_url', None),
        )

    @database_sync_to_async
    def get_order_delta_events(self, order_id, include_order, include_shop, include_on_way, include_history):
        return build_order_delta_events(
            self.customer_id,
            order_id,
            include_order=include_order,
            include_shop=include_shop,
            include_on_way=include_on_way,
            include_history=include_history,
            lang=self.lang,
            scope=getattr(self, 'scope', None),
            base_url=getattr(self, 'base_url', None),
        )

    @database_sync_to_async
    def get_support_delta_events(self, conversation_id, include_shop, include_history):
        return build_support_delta_events(
            self.customer_id,
            conversation_id,
            include_shop=include_shop,
            include_history=include_history,
            lang=self.lang,
            scope=getattr(self, 'scope', None),
            base_url=getattr(self, 'base_url', None),
        )

    @database_sync_to_async
    def register_customer_presence(self, connection_type):
        return mark_customer_websocket_connected(
            customer_id=self.user.id,
            channel_name=self.channel_name,
            connection_type=connection_type,
        )

    @database_sync_to_async
    def unregister_customer_presence(self):
        return mark_customer_websocket_disconnected(self.channel_name)

    @database_sync_to_async
    def get_customer_presence_broadcast_batches(self, customer_id, is_online, last_seen):
        return build_customer_presence_broadcast_batches(customer_id, is_online, last_seen)


class DriverConsumer(AsyncWebsocketConsumer):
    """
    WebSocket consumer for driver updates.
    """

    async def connect(self):
        self.driver_id = self.scope['url_route']['kwargs'].get('driver_id')
        self.room_group_name = f'driver_{self.driver_id}'
        self.base_url = resolve_base_url(scope=self.scope)

        query_string = self.scope.get('query_string', b'').decode('utf-8')
        self.lang = 'ar'
        if 'lang=' in query_string:
            self.lang = query_string.split('lang=')[-1].split('&')[0]

        user = self.scope.get('user')
        user_type = self.scope.get('user_type')

        if not user or user_type != 'driver' or user.id != int(self.driver_id):
            await self.close(code=4401)
            return
        self.user = user
        self.user_type = user_type
        if not await ensure_socket_account_active(self, refresh=True, accept_if_needed=True):
            return

        self.driver_presence_registered = False
        self.driver_presence_timeout_task = None

        await self.channel_layer.group_add(self.room_group_name, self.channel_name)
        await self.accept()

        presence_state = await self.register_driver_presence()
        self.driver_presence_registered = bool(presence_state)
        self.driver_presence_timeout_task = asyncio.create_task(self.watch_driver_presence_timeout())

        await self.send(text_data=_json_dumps(_with_localized_message(
            {'type': 'connection'},
            'تم الاتصال بنجاح',
            lang=self.lang,
        )))

        snapshots = await self.get_driver_snapshots()
        for snapshot in snapshots:
            await self.send(text_data=_json_dumps(snapshot))

        if presence_state and presence_state.get('changed'):
            await self.broadcast_driver_presence()

    async def disconnect(self, close_code):
        if hasattr(self, 'room_group_name'):
            await self.channel_layer.group_discard(self.room_group_name, self.channel_name)

        if getattr(self, 'driver_presence_registered', False):
            self.cancel_driver_presence_timeout_task()
            presence_state = await self.unregister_driver_presence()
            if presence_state and presence_state.get('changed'):
                await self.broadcast_driver_presence()

    @database_sync_to_async
    def register_driver_presence(self):
        return mark_driver_connected(self.driver_id, self.channel_name, connection_type='driver_socket')

    @database_sync_to_async
    def unregister_driver_presence(self):
        return mark_driver_disconnected(self.channel_name)

    @database_sync_to_async
    def broadcast_driver_presence(self):
        return broadcast_driver_presence_update(self.driver_id)

    @database_sync_to_async
    def touch_driver_presence(self):
        return touch_driver_presence(self.channel_name, self.driver_id)

    @database_sync_to_async
    def mark_driver_presence_timed_out(self):
        return mark_driver_connection_timed_out(
            self.channel_name,
            timeout_seconds=DRIVER_PRESENCE_TIMEOUT_SECONDS,
        )

    @database_sync_to_async
    def get_driver_snapshots(self):
        return build_driver_snapshot_events(self.user, scope=self.scope, base_url=self.base_url)

    async def receive(self, text_data):
        try:
            if not await ensure_socket_account_active(self, refresh=True):
                return
            await self.touch_driver_presence()
            data = json.loads(text_data)
            msg_type = data.get('type')
            request_id = data.get('request_id')

            if msg_type == 'location_update':
                await self.handle_location_update(data)
            elif msg_type == 'ring':
                await _handle_ring_request(self, data, request_id=request_id)
            elif msg_type in {'ping', 'presence_ping'}:
                await self.send(text_data=_json_dumps({
                    'type': 'pong',
                    'request_id': request_id,
                    'sent_at': format_utc_iso8601(timezone.now()),
                }))
            else:
                await _send_error_event(
                    self,
                    code='UNKNOWN_EVENT',
                    message='نوع الحدث غير مدعوم',
                    request_id=request_id,
                    details={'type': msg_type},
                )
        except json.JSONDecodeError:
            await _send_error_event(
                self,
                code='INVALID_JSON',
                message='تنسيق البيانات غير صحيح',
            )
        except Exception as e:
            print(f"[DriverConsumer.receive] error: {e}")
            await _send_error_event(
                self,
                code='UNEXPECTED_ERROR',
                message='حدث خطأ غير متوقع',
                details={'error_detail': str(e)},
            )

    def cancel_driver_presence_timeout_task(self):
        task = getattr(self, 'driver_presence_timeout_task', None)
        if task:
            task.cancel()
            self.driver_presence_timeout_task = None

    async def watch_driver_presence_timeout(self):
        try:
            while True:
                await asyncio.sleep(15)
                timed_out_state = await self.mark_driver_presence_timed_out()
                if timed_out_state:
                    if timed_out_state.get('changed'):
                        await self.broadcast_driver_presence()
                    await self.close(code=4001)
                    return
        except asyncio.CancelledError:
            return

    async def handle_location_update(self, data):
        latitude = data.get('latitude')
        longitude = data.get('longitude')

        if latitude and longitude:
            await self.update_driver_location(latitude, longitude)
            await self.broadcast_location_to_customers(latitude, longitude)

    @database_sync_to_async
    def update_driver_location(self, latitude, longitude):
        try:
            driver = Driver.objects.get(id=self.driver_id)
            driver.current_latitude = latitude
            driver.current_longitude = longitude
            driver.location_updated_at = timezone.now()
            driver.save()
        except Exception as e:
            print(f"[DriverConsumer.update_driver_location] error: {e}")

    @database_sync_to_async
    def get_active_orders(self):
        return list(Order.objects.filter(
            driver_id=self.driver_id,
            status__in=['on_way', 'preparing']
        ).values_list('customer_id', flat=True))

    async def broadcast_location_to_customers(self, latitude, longitude):
        customer_ids = await self.get_active_orders()

        for customer_id in customer_ids:
            await self.channel_layer.group_send(
                f'customer_orders_{customer_id}',
                {
                    'type': 'driver_location',
                    'data': {
                        'driver_id': self.driver_id,
                        'latitude': str(latitude),
                        'longitude': str(longitude),
                        'updated_at': timezone.now().isoformat(),
                    }
                }
            )

    async def new_order(self, event):
        await self.send(text_data=_json_dumps({
            'type': 'new_order',
            'data': event['data'],
        }))

    async def order_update(self, event):
        await self.send(text_data=_json_dumps({
            'type': 'order_update',
            'data': event['data'],
        }))

    async def presence_update(self, event):
        await self.send(text_data=_json_dumps({
            'type': 'presence_update',
            'data': event['data'],
        }))

    async def new_message(self, event):
        from user.utils import localize_message
        notif_data = dict(event['data'])
        if 'message' in notif_data and isinstance(notif_data['message'], dict):
            notif_data['message'] = dict(notif_data['message'])
            notif_data['message']['content'] = localize_message(
                None, notif_data['message'].get('content'), lang=getattr(self, 'lang', 'ar')
            )
        await self.send(text_data=_json_dumps({
            'type': 'new_message',
            'data': notif_data,
        }))

    async def ring(self, event):
        await self.send(text_data=_json_dumps({
            'type': 'ring',
            'data': event['data'],
        }))

    async def driver_realtime_event(self, event):
        await self.send(text_data=_json_dumps(event['payload']))
