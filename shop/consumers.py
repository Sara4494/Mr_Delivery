import json
from channels.generic.websocket import AsyncWebsocketConsumer
from channels.db import database_sync_to_async
from django.core.serializers.json import DjangoJSONEncoder
from django.utils import timezone
from .models import Order, ChatMessage, Customer, Employee, Driver
from user.models import ShopOwner
from .serializers import OrderSerializer
from user.utils import build_message_fields


def _with_localized_message(payload, message, lang=None):
    return {
        **payload,
        **build_message_fields(message, lang=lang),
    }


def _json_dumps(payload):
    return json.dumps(payload, cls=DjangoJSONEncoder)







class ChatConsumer(AsyncWebsocketConsumer):
    """
    WebSocket Consumer للشات - يدعم جميع الأطراف:
    - shop_owner ↔ customer (shop_customer chat)
    - employee ↔ customer (shop_customer chat)
    - driver ↔ customer (driver_customer chat)
    
    URL: ws://server/ws/chat/order/{order_id}/?token=JWT_TOKEN&chat_type=shop_customer
    """
    
    async def connect(self):
        """الاتصال بالـ WebSocket"""
        try:
            self.order_id = self.scope['url_route']['kwargs']['order_id']
            
            # استخراج chat_type من query string
            query_string = self.scope.get('query_string', b'').decode('utf-8')
            self.chat_type = 'shop_customer'  # default
            if 'chat_type=' in query_string:
                chat_type_param = query_string.split('chat_type=')[-1].split('&')[0]
                if chat_type_param in ['shop_customer', 'driver_customer']:
                    self.chat_type = chat_type_param

            # استخراج lang من query string
            self.lang = 'ar'
            if 'lang=' in query_string:
                self.lang = query_string.split('lang=')[-1].split('&')[0]
            
            self.room_group_name = f'chat_order_{self.order_id}_{self.chat_type}'
            
            # التحقق من المستخدم
            user = self.scope.get('user')
            user_type = self.scope.get('user_type')
            
            print(f"[ChatConsumer.connect] order_id={self.order_id} chat_type={self.chat_type} user_type={user_type}")
            
            if not user or not user_type:
                await self.close(code=4401)  # unauthorized
                return
            
            # التحقق من صلاحية الوصول للطلب
            has_access = await self.check_order_access(user, user_type)
            if not has_access:
                await self.close(code=4403)  # forbidden
                return
            
            # التحقق من صلاحية chat_type
            if self.chat_type == 'driver_customer' and user_type not in ['driver', 'customer']:
                await self.close(code=4403)
                return
            
            if self.chat_type == 'shop_customer' and user_type not in ['shop_owner', 'employee', 'customer']:
                await self.close(code=4403)
                return
            
            self.user = user
            self.user_type = user_type
            
            # الانضمام إلى مجموعة الشات
            await self.channel_layer.group_add(self.room_group_name, self.channel_name)
            await self.accept()
            
            # إرسال رسالة ترحيبية
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
            
            # إرسال الرسائل السابقة
            previous_messages = await self.get_previous_messages()
            await self.send(text_data=_json_dumps({
                'type': 'previous_messages',
                'messages': previous_messages
            }))
                
        except Exception as e:
            print(f"[ChatConsumer.connect] error: {e}")
            await self.close(code=1011)
            await self.channel_layer.group_discard(self.room_group_name, self.channel_name)
    
    async def receive(self, text_data):
        """استقبال رسالة من العميل"""
        try:
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
    
    async def handle_chat_message(self, data, request_id=None, action='chat_message'):
        """معالجة رسالة الشات"""
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
        
        # حفظ الرسالة
        message = await self.save_message(
            content=content,
            message_type=msg_type,
            latitude=data.get('latitude'),
            longitude=data.get('longitude')
        )
        
        if message:
            serialized = await self.serialize_message(message)
            
            # إرسال الرسالة لجميع المشتركين
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
        """معالجة رسالة الموقع"""
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
        """تعليم الرسائل كمقروءة"""
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
        """معالجة حالة الكتابة"""
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
    
    # ==================== Event Handlers ====================
    
    async def chat_message(self, event):
        """إرسال رسالة الشات"""
        from user.utils import localize_message
        msg_data = dict(event['message'])
        msg_data['content'] = localize_message(None, msg_data.get('content'), lang=getattr(self, 'lang', 'ar'))
        await self.send(text_data=_json_dumps({
            'type': 'chat_message',
            'data': msg_data
        }))
    
    async def messages_read(self, event):
        """إرسال تأكيد قراءة الرسائل"""
        await self.send(text_data=_json_dumps({
            'type': 'messages_read',
            'order_id': event['order_id'],
            'reader_type': event['reader_type'],
            'count': event.get('count', 0),
        }))
    
    async def typing_indicator(self, event):
        """إرسال مؤشر الكتابة"""
        await self.send(text_data=_json_dumps({
            'type': 'typing',
            'user_type': event['user_type'],
            'user_name': event['user_name'],
            'is_typing': event['is_typing']
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

    async def broadcast_order_snapshot_update(self):
        order_snapshot = await self.get_order_snapshot()
        if not order_snapshot:
            return

        group_names = await self.get_order_channel_targets()
        for group_name in group_names:
            await self.channel_layer.group_send(
                group_name,
                {
                    'type': 'order_update',
                    'data': order_snapshot,
                }
            )
    
    # ==================== Database Operations ====================
    
    @database_sync_to_async
    def check_order_access(self, user, user_type):
        """التحقق من صلاحية الوصول للطلب"""
        try:
            order = Order.objects.get(id=self.order_id)
            
            if user_type == 'shop_owner':
                has_access = order.shop_owner_id == user.id
                print(f"[check_order_access] shop_owner: order.shop_owner_id={order.shop_owner_id}, user.id={user.id}, access={has_access}")
                return has_access
            elif user_type == 'employee':
                has_access = order.shop_owner_id == user.shop_owner_id
                print(f"[check_order_access] employee: order.shop_owner_id={order.shop_owner_id}, user.shop_owner_id={user.shop_owner_id}, access={has_access}")
                return has_access
            elif user_type == 'driver':
                has_access = order.driver_id == user.id
                print(f"[check_order_access] driver: order.driver_id={order.driver_id}, user.id={user.id}, access={has_access}")
                return has_access
            elif user_type == 'customer':
                has_access = order.customer_id == user.id
                print(f"[check_order_access] customer: order.customer_id={order.customer_id}, user.id={user.id}, access={has_access}")
                return has_access
            
            return False
        except Order.DoesNotExist:
            print(f"[check_order_access] Order {self.order_id} does not exist!")
            return False
    
    @database_sync_to_async
    def save_message(self, content, message_type='text', latitude=None, longitude=None):
        """حفظ الرسالة في قاعدة البيانات"""
        try:
            order = Order.objects.get(id=self.order_id)
            
            # تحديد المرسل
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
            
            # تحديث عدد الرسائل غير المقروءة في الطلب
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
        """جلب الرسائل السابقة"""
        try:
            messages = ChatMessage.objects.filter(
                order_id=self.order_id,
                chat_type=self.chat_type
            ).order_by('created_at')[:50]
            
            from user.utils import localize_message
            result = []
            for msg in messages:
                result.append({
                    'id': msg.id,
                    'order_id': msg.order_id,
                    'chat_type': msg.chat_type,
                    'sender_type': msg.sender_type,
                    'sender_name': msg.sender_name,
                    'sender_id': self._get_sender_id(msg),
                    'message_type': msg.message_type,
                    'content': localize_message(None, msg.content, lang=self.lang),
                    'latitude': str(msg.latitude) if msg.latitude is not None else None,
                    'longitude': str(msg.longitude) if msg.longitude is not None else None,
                    'is_read': msg.is_read,
                    'created_at': msg.created_at.isoformat(),
                    'audio_file_url': msg.audio_file.url if msg.audio_file else None,
                    'image_file_url': msg.image_file.url if msg.image_file else None,
                })
            return result
        except Exception as e:
            print(f"[ChatConsumer.get_previous_messages] error: {e}")
            return []
    
    @database_sync_to_async
    def serialize_message(self, message):
        """تحويل الرسالة إلى JSON"""
        from user.utils import localize_message
        return {
            'id': message.id,
            'order_id': message.order_id,
            'chat_type': message.chat_type,
            'sender_type': message.sender_type,
            'sender_name': message.sender_name,
            'sender_id': self._get_sender_id(message),
            'message_type': message.message_type,
            'content': localize_message(None, message.content, lang=self.lang),
            'latitude': str(message.latitude) if message.latitude is not None else None,
            'longitude': str(message.longitude) if message.longitude is not None else None,
            'is_read': message.is_read,
            'created_at': message.created_at.isoformat(),
            'audio_file_url': message.audio_file.url if message.audio_file else None,
            'image_file_url': message.image_file.url if message.image_file else None,
        }
    
    @database_sync_to_async
    def mark_messages_as_read(self):
        """تعليم الرسائل كمقروءة"""
        try:
            order = Order.objects.get(id=self.order_id)
            
            # تحديد الرسائل التي يجب تعليمها كمقروءة
            # (الرسائل التي ليست من المستخدم الحالي)
            marked_count = ChatMessage.objects.filter(
                order=order,
                chat_type=self.chat_type,
                is_read=False
            ).exclude(sender_type=self.user_type).update(is_read=True)
            
            # تحديث عدد الرسائل غير المقروءة
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
        """الحصول على اسم المستخدم"""
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
            'order': OrderSerializer(order).data,
        }

    @database_sync_to_async
    def get_order_snapshot(self):
        try:
            order = Order.objects.select_related('customer', 'employee', 'driver').get(id=self.order_id)
        except Order.DoesNotExist:
            return None
        return OrderSerializer(order).data

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


class OrderConsumer(AsyncWebsocketConsumer):
    """
    WebSocket Consumer لتحديثات الطلبات في الوقت الحقيقي
    
    URL: ws://server/ws/orders/shop/{shop_owner_id}/?token=JWT_TOKEN
    
    يُستخدم لإرسال:
    - طلبات جديدة
    - تحديثات حالة الطلبات
    - إشعارات
    """
    
    async def connect(self):
        """الاتصال بالـ WebSocket"""
        self.shop_owner_id = self.scope['url_route']['kwargs'].get('shop_owner_id')
        self.room_group_name = f'shop_orders_{self.shop_owner_id}'
        
        query_string = self.scope.get('query_string', b'').decode('utf-8')
        self.lang = 'ar'
        if 'lang=' in query_string:
            self.lang = query_string.split('lang=')[-1].split('&')[0]
        
        user = self.scope.get('user')
        user_type = self.scope.get('user_type')
        
        # التحقق من أن المستخدم هو صاحب المحل أو موظف
        if not user:
            await self.close(code=4401)
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
        
        self.user = user
        self.user_type = user_type
        
        await self.channel_layer.group_add(self.room_group_name, self.channel_name)
        await self.accept()
        
        await self.send(text_data=_json_dumps(_with_localized_message(
            {
                'type': 'connection',
                'shop_owner_id': self.shop_owner_id
            },
            'تم الاتصال بنجاح'
        )))

        orders_snapshot = await self.get_orders_snapshot()
        await self.send(text_data=_json_dumps(_with_localized_message(
            {
                'type': 'orders_snapshot',
                'data': {
                    'orders': orders_snapshot,
                },
            },
            'تمت مزامنة قائمة الطلبات بنجاح'
        )))
    
    async def disconnect(self, close_code):
        """قطع الاتصال"""
        if hasattr(self, 'room_group_name'):
            await self.channel_layer.group_discard(self.room_group_name, self.channel_name)
    
    async def order_update(self, event):
        """إرسال تحديث الطلب"""
        await self.send(text_data=_json_dumps({
            'type': 'order_update',
            'data': event['data']
        }))
    
    async def new_order(self, event):
        """إرسال إشعار بطلب جديد"""
        await self.send(text_data=_json_dumps({
            'type': 'new_order',
            'data': event['data']
        }))
    
    async def new_message(self, event):
        """إشعار برسالة جديدة"""
        from user.utils import localize_message
        notif_data = dict(event['data'])
        if 'message' in notif_data and isinstance(notif_data['message'], dict):
            notif_data['message'] = dict(notif_data['message'])
            notif_data['message']['content'] = localize_message(
                None, notif_data['message'].get('content'), lang=getattr(self, 'lang', 'ar')
            )
        await self.send(text_data=_json_dumps({
            'type': 'new_message',
            'data': notif_data
        }))

    async def store_status_updated(self, event):
        """تحديث حالة المتجر في الوقت الحقيقي"""
        await self.send(text_data=_json_dumps({
            'type': 'store_status_updated',
            'data': event['data']
        }))

    async def driver_status_updated(self, event):
        """تحديث حالة السائق في الوقت الحقيقي"""
        await self.send(text_data=_json_dumps({
            'type': 'driver_status_updated',
            'data': event['data']
        }))

    @database_sync_to_async
    def get_orders_snapshot(self):
        orders = (
            Order.objects
            .filter(shop_owner_id=self.shop_owner_id)
            .select_related('customer', 'employee', 'driver')
            .order_by('-updated_at')[:50]
        )
        return OrderSerializer(orders, many=True).data


class CustomerOrderConsumer(AsyncWebsocketConsumer):
    """
    WebSocket Consumer لتحديثات طلبات العميل
    
    URL: ws://server/ws/orders/customer/{customer_id}/?token=JWT_TOKEN
    
    يُستخدم لإرسال:
    - تحديثات حالة الطلب
    - موقع السائق
    - رسائل جديدة
    """
    
    async def connect(self):
        """الاتصال بالـ WebSocket"""
        self.customer_id = self.scope['url_route']['kwargs'].get('customer_id')
        self.room_group_name = f'customer_orders_{self.customer_id}'
        
        query_string = self.scope.get('query_string', b'').decode('utf-8')
        self.lang = 'ar'
        if 'lang=' in query_string:
            self.lang = query_string.split('lang=')[-1].split('&')[0]
        
        user = self.scope.get('user')
        user_type = self.scope.get('user_type')
        
        if not user or user_type != 'customer' or user.id != int(self.customer_id):
            await self.close(code=4401)
            return
        
        self.user = user
        
        await self.channel_layer.group_add(self.room_group_name, self.channel_name)
        await self.accept()
        
        await self.send(text_data=_json_dumps(_with_localized_message(
            {'type': 'connection'},
            'تم الاتصال بنجاح'
        )))
    
    async def disconnect(self, close_code):
        """قطع الاتصال"""
        if hasattr(self, 'room_group_name'):
            await self.channel_layer.group_discard(self.room_group_name, self.channel_name)
    
    async def order_update(self, event):
        """تحديث حالة الطلب"""
        await self.send(text_data=_json_dumps({
            'type': 'order_update',
            'data': event['data']
        }))
    
    async def driver_location(self, event):
        """تحديث موقع السائق"""
        await self.send(text_data=_json_dumps({
            'type': 'driver_location',
            'data': event['data']
        }))
    
    async def new_message(self, event):
        """إشعار برسالة جديدة"""
        from user.utils import localize_message
        notif_data = dict(event['data'])
        if 'message' in notif_data and isinstance(notif_data['message'], dict):
            notif_data['message'] = dict(notif_data['message'])
            notif_data['message']['content'] = localize_message(
                None, notif_data['message'].get('content'), lang=getattr(self, 'lang', 'ar')
            )
        await self.send(text_data=_json_dumps({
            'type': 'new_message',
            'data': notif_data
        }))


class DriverConsumer(AsyncWebsocketConsumer):
    """
    WebSocket Consumer للسائق
    
    URL: ws://server/ws/driver/{driver_id}/?token=JWT_TOKEN
    
    يُستخدم لإرسال:
    - طلبات توصيل جديدة
    - تحديثات الطلبات
    - رسائل من العملاء
    """
    
    async def connect(self):
        """الاتصال بالـ WebSocket"""
        self.driver_id = self.scope['url_route']['kwargs'].get('driver_id')
        self.room_group_name = f'driver_{self.driver_id}'
        
        user = self.scope.get('user')
        user_type = self.scope.get('user_type')
        
        if not user or user_type != 'driver' or user.id != int(self.driver_id):
            await self.close(code=4401)
            return
        
        self.user = user
        
        await self.channel_layer.group_add(self.room_group_name, self.channel_name)
        await self.accept()
        
        await self.send(text_data=_json_dumps(_with_localized_message(
            {'type': 'connection'},
            'تم الاتصال بنجاح'
        )))
    
    async def disconnect(self, close_code):
        """قطع الاتصال"""
        if hasattr(self, 'room_group_name'):
            await self.channel_layer.group_discard(self.room_group_name, self.channel_name)
    
    async def receive(self, text_data):
        """استقبال بيانات من السائق"""
        try:
            data = json.loads(text_data)
            msg_type = data.get('type')
            
            if msg_type == 'location_update':
                await self.handle_location_update(data)
                
        except Exception as e:
            print(f"[DriverConsumer.receive] error: {e}")
    
    async def handle_location_update(self, data):
        """تحديث موقع السائق"""
        latitude = data.get('latitude')
        longitude = data.get('longitude')
        
        if latitude and longitude:
            await self.update_driver_location(latitude, longitude)
            
            # إرسال الموقع للعملاء الذين لديهم طلبات نشطة مع هذا السائق
            await self.broadcast_location_to_customers(latitude, longitude)
    
    @database_sync_to_async
    def update_driver_location(self, latitude, longitude):
        """تحديث موقع السائق في قاعدة البيانات"""
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
        """جلب الطلبات النشطة للسائق"""
        return list(Order.objects.filter(
            driver_id=self.driver_id,
            status__in=['on_way', 'preparing']
        ).values_list('customer_id', flat=True))
    
    async def broadcast_location_to_customers(self, latitude, longitude):
        """إرسال الموقع للعملاء"""
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
                        'updated_at': timezone.now().isoformat()
                    }
                }
            )
    
    async def new_order(self, event):
        """طلب توصيل جديد"""
        await self.send(text_data=_json_dumps({
            'type': 'new_order',
            'data': event['data']
        }))
    
    async def order_update(self, event):
        """تحديث طلب"""
        await self.send(text_data=_json_dumps({
            'type': 'order_update',
            'data': event['data']
        }))
    
    async def new_message(self, event):
        """إشعار برسالة جديدة"""
        from user.utils import localize_message
        notif_data = dict(event['data'])
        if 'message' in notif_data and isinstance(notif_data['message'], dict):
            notif_data['message'] = dict(notif_data['message'])
            notif_data['message']['content'] = localize_message(
                None, notif_data['message'].get('content'), lang=getattr(self, 'lang', 'ar')
            )
        await self.send(text_data=_json_dumps({
            'type': 'new_message',
            'data': notif_data
        }))
