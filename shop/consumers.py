import json
from channels.generic.websocket import AsyncWebsocketConsumer
from channels.db import database_sync_to_async
from .models import Order, ChatMessage, Customer
from user.models import ShopOwner
from .serializers import ChatMessageSerializer


class ChatConsumer(AsyncWebsocketConsumer):
    """WebSocket Consumer للشات"""
    
    async def connect(self):
        """الاتصال بالـ WebSocket"""
        self.order_id = self.scope['url_route']['kwargs']['order_id']
        self.room_group_name = f'chat_order_{self.order_id}'
        
        # التحقق من المستخدم من scope (تم التحقق في middleware)
        user = self.scope.get('user')
        
        if not user or not isinstance(user, ShopOwner):
            await self.close()
            return
        
        # التحقق من وجود الطلب وأنه يخص هذا المحل
        order_exists = await self.check_order_access(user)
        if not order_exists:
            await self.close()
            return
        
        self.user = user
        self.user_type = 'shop'  # افتراضياً من المحل
        
        # الانضمام إلى مجموعة الطلب
        await self.channel_layer.group_add(
            self.room_group_name,
            self.channel_name
        )
        
        await self.accept()
        
        # إرسال رسالة ترحيبية
        await self.send(text_data=json.dumps({
            'type': 'connection',
            'message': 'تم الاتصال بنجاح',
            'order_id': self.order_id
        }))
    
    async def disconnect(self, close_code):
        """قطع الاتصال"""
        # مغادرة مجموعة الطلب
        await self.channel_layer.group_discard(
            self.room_group_name,
            self.channel_name
        )
    
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
            
        except json.JSONDecodeError:
            await self.send(text_data=json.dumps({
                'type': 'error',
                'message': 'تنسيق البيانات غير صحيح'
            }))
        except Exception as e:
            await self.send(text_data=json.dumps({
                'type': 'error',
                'message': f'حدث خطأ: {str(e)}'
            }))
    
    async def handle_chat_message(self, data):
        """معالجة رسالة الشات"""
        content = data.get('content', '')
        message_type = data.get('message_type', 'text')
        audio_file = data.get('audio_file')
        image_file = data.get('image_file')
        
        if not content and message_type == 'text':
            await self.send(text_data=json.dumps({
                'type': 'error',
                'message': 'محتوى الرسالة مطلوب'
            }))
            return
        
        # حفظ الرسالة في قاعدة البيانات
        message = await self.save_message(
            content=content,
            message_type=message_type,
            audio_file=audio_file,
            image_file=image_file
        )
        
        if message:
            # إرسال الرسالة إلى جميع المشتركين في المجموعة
            await self.channel_layer.group_send(
                self.room_group_name,
                {
                    'type': 'chat_message',
                    'message': await self.serialize_message(message)
                }
            )
    
    async def handle_mark_read(self):
        """تعليم الرسائل كمقروءة"""
        await self.mark_messages_as_read()
        
        # إرسال تأكيد
        await self.channel_layer.group_send(
            self.room_group_name,
            {
                'type': 'messages_read',
                'order_id': self.order_id
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
                'is_typing': is_typing
            }
        )
    
    async def chat_message(self, event):
        """إرسال رسالة الشات إلى WebSocket"""
        await self.send(text_data=json.dumps({
            'type': 'chat_message',
            'data': event['message']
        }))
    
    async def messages_read(self, event):
        """إرسال تأكيد قراءة الرسائل"""
        await self.send(text_data=json.dumps({
            'type': 'messages_read',
            'order_id': event['order_id']
        }))
    
    async def typing_indicator(self, event):
        """إرسال مؤشر الكتابة"""
        await self.send(text_data=json.dumps({
            'type': 'typing',
            'user_type': event['user_type'],
            'is_typing': event['is_typing']
        }))
    
    @database_sync_to_async
    def save_message(self, content, message_type='text', audio_file=None, image_file=None):
        """حفظ الرسالة في قاعدة البيانات"""
        try:
            order = Order.objects.get(id=self.order_id)
            
            message = ChatMessage.objects.create(
                order=order,
                sender_type=self.user_type,
                message_type=message_type,
                content=content,
                audio_file=audio_file,
                image_file=image_file
            )
            
            # تحديث عدد الرسائل غير المقروءة
            if self.user_type == 'shop':
                # إذا كانت الرسالة من المحل، لا نحتاج لتحديث العدد
                pass
            else:
                # إذا كانت من العميل، نحدث العدد
                order.unread_messages_count = order.messages.filter(
                    is_read=False,
                    sender_type='customer'
                ).count()
                order.save()
            
            return message
        except Order.DoesNotExist:
            return None
        except Exception as e:
            print(f"Error saving message: {e}")
            return None
    
    @database_sync_to_async
    def check_order_access(self, shop_owner):
        """التحقق من وجود الطلب وأنه يخص هذا المحل"""
        try:
            Order.objects.get(id=self.order_id, shop_owner=shop_owner)
            return True
        except Order.DoesNotExist:
            return False
    
    @database_sync_to_async
    def serialize_message(self, message):
        """تحويل الرسالة إلى JSON"""
        # في WebSocket لا يوجد request object، لذلك نبني URL يدوياً
        serializer = ChatMessageSerializer(message)
        data = serializer.data
        
        # بناء URLs نسبية للصور والملفات الصوتية (سيتم إكمالها في Frontend)
        if message.audio_file:
            data['audio_file_url'] = message.audio_file.url
        
        if message.image_file:
            data['image_file_url'] = message.image_file.url
        
        return data
    
    @database_sync_to_async
    def mark_messages_as_read(self):
        """تعليم الرسائل كمقروءة"""
        try:
            order = Order.objects.get(id=self.order_id)
            ChatMessage.objects.filter(
                order=order,
                sender_type='customer',
                is_read=False
            ).update(is_read=True)
            order.unread_messages_count = 0
            order.save()
        except Order.DoesNotExist:
            pass


class OrderConsumer(AsyncWebsocketConsumer):
    """WebSocket Consumer لتحديثات الطلبات"""
    
    async def connect(self):
        """الاتصال بالـ WebSocket"""
        self.shop_owner_id = self.scope['url_route']['kwargs'].get('shop_owner_id')
        self.room_group_name = f'shop_orders_{self.shop_owner_id}'
        
        # التحقق من المستخدم من scope (تم التحقق في middleware)
        user = self.scope.get('user')
        
        if not user or not isinstance(user, ShopOwner) or user.id != int(self.shop_owner_id):
            await self.close()
            return
        
        self.user = user
        
        # الانضمام إلى مجموعة الطلبات
        await self.channel_layer.group_add(
            self.room_group_name,
            self.channel_name
        )
        
        await self.accept()
    
    async def disconnect(self, close_code):
        """قطع الاتصال"""
        await self.channel_layer.group_discard(
            self.room_group_name,
            self.channel_name
        )
    
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
