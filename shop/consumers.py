import json
from channels.generic.websocket import AsyncWebsocketConsumer
from channels.db import database_sync_to_async
from django.utils import timezone
from .models import Order, ChatMessage, Customer, Employee, Driver
from user.models import ShopOwner
from .serializers import ChatMessageSerializer
from user.utils import build_message_fields


def _with_localized_message(payload, message):
    return {
        **payload,
        **build_message_fields(message),
    }


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
            await self.send(text_data=json.dumps(_with_localized_message(
                {
                    'type': 'connection',
                    'order_id': self.order_id,
                    'chat_type': self.chat_type,
                    'user_type': self.user_type
                },
                'تم الاتصال بنجاح'
            )))
            
            # إرسال الرسائل السابقة
            previous_messages = await self.get_previous_messages()
            if previous_messages:
                await self.send(text_data=json.dumps({
                    'type': 'previous_messages',
                    'messages': previous_messages
                }))
                
        except Exception as e:
            print(f"[ChatConsumer.connect] error: {e}")
            await self.close(code=1011)
    
    async def disconnect(self, close_code):
        """قطع الاتصال"""
        if hasattr(self, 'room_group_name'):
            await self.channel_layer.group_discard(self.room_group_name, self.channel_name)
    
    async def receive(self, text_data):
        """استقبال رسالة من العميل"""
        try:
            data = json.loads(text_data)
            message_type = data.get('type', 'chat_message')
            
            if message_type == 'chat_message':
                await self.handle_chat_message(data)
            elif message_type == 'mark_read':
                await self.handle_mark_read()
            elif message_type == 'typing':
                await self.handle_typing(data)
            elif message_type == 'location':
                await self.handle_location(data)
                
        except json.JSONDecodeError:
            await self.send(text_data=json.dumps(_with_localized_message(
                {'type': 'error'},
                'تنسيق البيانات غير صحيح'
            )))
        except Exception as e:
            print(f"[ChatConsumer.receive] error: {e}")
            await self.send(text_data=json.dumps(_with_localized_message(
                {
                    'type': 'error',
                    'error_detail': str(e)
                },
                'حدث خطأ غير متوقع'
            )))
    
    async def handle_chat_message(self, data):
        """معالجة رسالة الشات"""
        content = data.get('content', '')
        msg_type = data.get('message_type', 'text')
        
        if msg_type == 'text' and not content:
            await self.send(text_data=json.dumps(_with_localized_message(
                {'type': 'error'},
                'محتوى الرسالة مطلوب'
            )))
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
    
    async def handle_location(self, data):
        """معالجة رسالة الموقع"""
        latitude = data.get('latitude')
        longitude = data.get('longitude')
        content = data.get('content', 'موقعي الحالي')
        
        if not latitude or not longitude:
            await self.send(text_data=json.dumps(_with_localized_message(
                {'type': 'error'},
                'الإحداثيات مطلوبة'
            )))
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
    
    async def handle_mark_read(self):
        """تعليم الرسائل كمقروءة"""
        await self.mark_messages_as_read()
        
        await self.channel_layer.group_send(
            self.room_group_name,
            {
                'type': 'messages_read',
                'order_id': self.order_id,
                'reader_type': self.user_type
            }
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
        await self.send(text_data=json.dumps({
            'type': 'chat_message',
            'data': event['message']
        }))
    
    async def messages_read(self, event):
        """إرسال تأكيد قراءة الرسائل"""
        await self.send(text_data=json.dumps({
            'type': 'messages_read',
            'order_id': event['order_id'],
            'reader_type': event['reader_type']
        }))
    
    async def typing_indicator(self, event):
        """إرسال مؤشر الكتابة"""
        await self.send(text_data=json.dumps({
            'type': 'typing',
            'user_type': event['user_type'],
            'user_name': event['user_name'],
            'is_typing': event['is_typing']
        }))
    
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
            
            result = []
            for msg in messages:
                result.append({
                    'id': msg.id,
                    'chat_type': msg.chat_type,
                    'sender_type': msg.sender_type,
                    'sender_name': msg.sender_name,
                    'message_type': msg.message_type,
                    'content': msg.content,
                    'latitude': str(msg.latitude) if msg.latitude else None,
                    'longitude': str(msg.longitude) if msg.longitude else None,
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
        return {
            'id': message.id,
            'chat_type': message.chat_type,
            'sender_type': message.sender_type,
            'sender_name': message.sender_name,
            'message_type': message.message_type,
            'content': message.content,
            'latitude': str(message.latitude) if message.latitude else None,
            'longitude': str(message.longitude) if message.longitude else None,
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
            ChatMessage.objects.filter(
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
                
        except Exception as e:
            print(f"[ChatConsumer.mark_messages_as_read] error: {e}")
    
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
        
        await self.send(text_data=json.dumps(_with_localized_message(
            {
                'type': 'connection',
                'shop_owner_id': self.shop_owner_id
            },
            'تم الاتصال بنجاح'
        )))
    
    async def disconnect(self, close_code):
        """قطع الاتصال"""
        if hasattr(self, 'room_group_name'):
            await self.channel_layer.group_discard(self.room_group_name, self.channel_name)
    
    async def order_update(self, event):
        """إرسال تحديث الطلب"""
        await self.send(text_data=json.dumps({
            'type': 'order_update',
            'data': event['data']
        }))
    
    async def new_order(self, event):
        """إرسال إشعار بطلب جديد"""
        await self.send(text_data=json.dumps({
            'type': 'new_order',
            'data': event['data']
        }))
    
    async def new_message(self, event):
        """إشعار برسالة جديدة"""
        await self.send(text_data=json.dumps({
            'type': 'new_message',
            'data': event['data']
        }))


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
        
        user = self.scope.get('user')
        user_type = self.scope.get('user_type')
        
        if not user or user_type != 'customer' or user.id != int(self.customer_id):
            await self.close(code=4401)
            return
        
        self.user = user
        
        await self.channel_layer.group_add(self.room_group_name, self.channel_name)
        await self.accept()
        
        await self.send(text_data=json.dumps(_with_localized_message(
            {'type': 'connection'},
            'تم الاتصال بنجاح'
        )))
    
    async def disconnect(self, close_code):
        """قطع الاتصال"""
        if hasattr(self, 'room_group_name'):
            await self.channel_layer.group_discard(self.room_group_name, self.channel_name)
    
    async def order_update(self, event):
        """تحديث حالة الطلب"""
        await self.send(text_data=json.dumps({
            'type': 'order_update',
            'data': event['data']
        }))
    
    async def driver_location(self, event):
        """تحديث موقع السائق"""
        await self.send(text_data=json.dumps({
            'type': 'driver_location',
            'data': event['data']
        }))
    
    async def new_message(self, event):
        """رسالة جديدة"""
        await self.send(text_data=json.dumps({
            'type': 'new_message',
            'data': event['data']
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
        
        await self.send(text_data=json.dumps(_with_localized_message(
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
        await self.send(text_data=json.dumps({
            'type': 'new_order',
            'data': event['data']
        }))
    
    async def order_update(self, event):
        """تحديث طلب"""
        await self.send(text_data=json.dumps({
            'type': 'order_update',
            'data': event['data']
        }))
    
    async def new_message(self, event):
        """رسالة جديدة من عميل"""
        await self.send(text_data=json.dumps({
            'type': 'new_message',
            'data': event['data']
        }))
