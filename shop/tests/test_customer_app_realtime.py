import asyncio
import json
from datetime import timedelta

from asgiref.sync import async_to_sync
from channels.routing import ProtocolTypeRouter, URLRouter
from channels.testing import WebsocketCommunicator
from django.test import TransactionTestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIRequestFactory, force_authenticate
from rest_framework_simplejwt.tokens import RefreshToken

from shop.middleware import JWTAuthMiddleware
from shop.models import (
    ChatMessage,
    Customer,
    CustomerSupportConversation,
    CustomerSupportMessage,
    Driver,
    Order,
    ShopDriver,
)
from shop.routing import websocket_urlpatterns
from shop.views import (
    customer_orders_list_create_view,
    customer_support_conversations_view,
    order_detail_view,
)
from user.models import ShopCategory, ShopOwner


@override_settings(
    CHANNEL_LAYERS={'default': {'BACKEND': 'channels.layers.InMemoryChannelLayer'}},
    ALLOWED_HOSTS=['testserver', 'localhost', '127.0.0.1'],
)
class CustomerAppRealtimeTests(TransactionTestCase):
    reset_sequences = True

    def setUp(self):
        super().setUp()
        self.application = ProtocolTypeRouter(
            {
                'websocket': JWTAuthMiddleware(URLRouter(websocket_urlpatterns)),
            }
        )
        self.factory = APIRequestFactory()
        self.category = ShopCategory.objects.create(name='Groceries')
        self.shop = ShopOwner.objects.create(
            owner_name='محمد أحمد',
            shop_name='زايجو سوبر ماركت',
            shop_number='SHOP-001',
            phone_number='01010000001',
            password='secret123',
            shop_category=self.category,
        )
        self.customer = Customer.objects.create(
            shop_owner=self.shop,
            name='أحمد علي',
            phone_number='01020000001',
            password='secret123',
        )
        self.driver = Driver.objects.create(
            name='سائق التجربة',
            phone_number='01030000001',
            password='secret123',
        )
        ShopDriver.objects.create(
            shop_owner=self.shop,
            driver=self.driver,
            status='active',
        )

    def _customer_access_token(self, customer=None):
        customer = customer or self.customer
        refresh = RefreshToken()
        refresh['customer_id'] = customer.id
        refresh['phone_number'] = customer.phone_number
        refresh['user_type'] = 'customer'
        return str(refresh.access_token)

    def _shop_access_token(self, shop_owner=None):
        shop_owner = shop_owner or self.shop
        refresh = RefreshToken()
        refresh['shop_owner_id'] = shop_owner.id
        refresh['user_id'] = shop_owner.id
        refresh['shop_number'] = shop_owner.shop_number
        refresh['user_type'] = 'shop_owner'
        return str(refresh.access_token)

    def _next_order_number(self):
        return f'OD{Order.objects.count() + 1:06d}'

    def _set_timestamps(self, instance, created_at=None, updated_at=None):
        created_at = created_at or instance.created_at
        updated_at = updated_at or created_at
        instance.__class__.objects.filter(pk=instance.pk).update(
            created_at=created_at,
            updated_at=updated_at,
        )
        instance.refresh_from_db()
        return instance

    def _set_message_created_at(self, model_class, pk, created_at):
        model_class.objects.filter(pk=pk).update(created_at=created_at)

    def _create_order(
        self,
        *,
        status='new',
        shop_owner=None,
        customer=None,
        driver=None,
        items=None,
        created_at=None,
    ):
        order = Order.objects.create(
            shop_owner=shop_owner or self.shop,
            customer=customer or self.customer,
            driver=driver,
            order_number=self._next_order_number(),
            status=status,
            items=json.dumps(items or ['Cola', 'Chips'], ensure_ascii=False),
            total_amount='150.00',
            delivery_fee='20.00',
            address='شارع السنترال',
            notes='',
        )
        if created_at:
            order = self._set_timestamps(order, created_at=created_at, updated_at=created_at)
        return order

    def _sender_kwargs(self, sender_type):
        if sender_type == 'customer':
            return {'sender_customer': self.customer}
        if sender_type == 'shop_owner':
            return {'sender_shop_owner': self.shop}
        if sender_type == 'driver':
            return {'sender_driver': self.driver}
        raise ValueError(f'Unsupported sender_type: {sender_type}')

    def _create_order_message(
        self,
        order,
        *,
        sender_type,
        content,
        chat_type='shop_customer',
        is_read=False,
        created_at=None,
    ):
        message = ChatMessage.objects.create(
            order=order,
            chat_type=chat_type,
            sender_type=sender_type,
            message_type='text',
            content=content,
            is_read=is_read,
            **self._sender_kwargs(sender_type),
        )
        if created_at:
            self._set_message_created_at(ChatMessage, message.pk, created_at)
            message.refresh_from_db()
        return message

    def _create_support_conversation(
        self,
        *,
        conversation_type='inquiry',
        shop_owner=None,
        customer=None,
        created_at=None,
    ):
        conversation = CustomerSupportConversation.objects.create(
            shop_owner=shop_owner or self.shop,
            customer=customer or self.customer,
            conversation_type=conversation_type,
        )
        if created_at:
            conversation = self._set_timestamps(
                conversation,
                created_at=created_at,
                updated_at=created_at,
            )
        return conversation

    def _create_support_message(
        self,
        conversation,
        *,
        sender_type,
        content,
        is_read=False,
        created_at=None,
    ):
        sender_kwargs = {}
        if sender_type == 'customer':
            sender_kwargs['sender_customer'] = self.customer
        elif sender_type == 'shop_owner':
            sender_kwargs['sender_shop_owner'] = self.shop
        else:
            raise ValueError(f'Unsupported sender_type: {sender_type}')

        message = CustomerSupportMessage.objects.create(
            conversation=conversation,
            sender_type=sender_type,
            message_type='text',
            content=content,
            is_read=is_read,
            **sender_kwargs,
        )
        if created_at:
            self._set_message_created_at(CustomerSupportMessage, message.pk, created_at)
            message.refresh_from_db()

        conversation.last_message_preview = content
        conversation.last_message_at = message.created_at
        conversation.unread_for_shop_count = conversation.messages.filter(
            is_read=False,
            sender_type='customer',
        ).count()
        conversation.unread_for_customer_count = conversation.messages.filter(
            is_read=False,
        ).exclude(sender_type='customer').count()
        conversation.save(
            update_fields=[
                'last_message_preview',
                'last_message_at',
                'unread_for_shop_count',
                'unread_for_customer_count',
                'updated_at',
            ]
        )
        conversation.refresh_from_db()
        return message

    async def _connect_customer_socket(self, customer=None, route_prefix='/ws/customer/app'):
        customer = customer or self.customer
        communicator = WebsocketCommunicator(
            self.application,
            f'{route_prefix}/{customer.id}/?token={self._customer_access_token(customer)}&lang=ar',
        )
        connected, _ = await communicator.connect()
        self.assertTrue(connected)
        initial_messages = [await communicator.receive_json_from() for _ in range(5)]
        return communicator, initial_messages

    async def _connect_order_chat_as_shop(self, order, chat_type='shop_customer'):
        communicator = WebsocketCommunicator(
            self.application,
            f'/ws/chat/order/{order.id}/?token={self._shop_access_token()}&chat_type={chat_type}&lang=ar',
        )
        connected, _ = await communicator.connect()
        self.assertTrue(connected)
        await communicator.receive_json_from()
        await communicator.receive_json_from()
        return communicator

    async def _connect_order_chat_as_customer(self, order, chat_type='shop_customer'):
        communicator = WebsocketCommunicator(
            self.application,
            f'/ws/chat/order/{order.id}/?token={self._customer_access_token()}&chat_type={chat_type}&lang=ar',
        )
        connected, _ = await communicator.connect()
        self.assertTrue(connected)
        await communicator.receive_json_from()
        await communicator.receive_json_from()
        return communicator

    async def _connect_support_chat_as_shop(self, conversation):
        communicator = WebsocketCommunicator(
            self.application,
            f'/ws/chat/support/{conversation.public_id}/?token={self._shop_access_token()}&lang=ar',
        )
        connected, _ = await communicator.connect()
        self.assertTrue(connected)
        await communicator.receive_json_from()
        await communicator.receive_json_from()
        return communicator

    async def _receive_until_types(self, communicator, expected_types, max_messages=20):
        remaining = set(expected_types)
        received = []
        for _ in range(max_messages):
            payload = await asyncio.wait_for(communicator.receive_json_from(), timeout=2)
            received.append(payload)
            remaining.discard(payload.get('type'))
            if not remaining:
                return received
        self.fail(f'Missing expected event types: {sorted(remaining)}')

    def _call_view(self, view, method, path, data, user):
        request_factory_method = getattr(self.factory, method.lower())
        request = request_factory_method(path, data=data, format='json')
        force_authenticate(request, user=user)
        return view(request)

    def test_connection_sends_all_initial_snapshots(self):
        async def run():
            base_time = timezone.now() - timedelta(hours=1)
            active_order = self._create_order(created_at=base_time)
            self._create_order_message(
                active_order,
                sender_type='shop_owner',
                content='تم استلام طلبك',
                is_read=False,
                created_at=base_time + timedelta(minutes=1),
            )

            on_way_order = self._create_order(
                status='confirmed',
                driver=self.driver,
                created_at=base_time + timedelta(minutes=2),
            )
            self._create_order_message(
                on_way_order,
                sender_type='shop_owner',
                content='المندوب في الطريق',
                is_read=False,
                created_at=base_time + timedelta(minutes=3),
            )

            delivered_order = self._create_order(
                status='delivered',
                created_at=base_time + timedelta(minutes=4),
            )
            self._create_order_message(
                delivered_order,
                sender_type='shop_owner',
                content='تم التسليم',
                is_read=True,
                created_at=base_time + timedelta(minutes=5),
            )

            conversation = self._create_support_conversation(
                conversation_type='inquiry',
                created_at=base_time + timedelta(minutes=6),
            )
            self._create_support_message(
                conversation,
                sender_type='customer',
                content='استفسار',
                is_read=False,
                created_at=base_time + timedelta(minutes=7),
            )

            communicator, initial_messages = await self._connect_customer_socket()
            try:
                self.assertEqual(
                    [message['type'] for message in initial_messages],
                    [
                        'connection',
                        'orders_snapshot',
                        'shops_snapshot',
                        'on_way_snapshot',
                        'order_history_snapshot',
                    ],
                )

                connection = initial_messages[0]
                self.assertEqual(connection['scope'], 'customer_app_realtime')
                self.assertEqual(connection['customer_id'], self.customer.id)

                orders_snapshot = initial_messages[1]
                self.assertEqual(orders_snapshot['data']['count'], 2)

                shops_snapshot = initial_messages[2]
                self.assertEqual(shops_snapshot['data']['count'], 1)
                self.assertEqual(
                    shops_snapshot['data']['results'][0]['chat']['support_conversation_id'],
                    conversation.public_id,
                )

                on_way_snapshot = initial_messages[3]
                self.assertEqual(on_way_snapshot['data']['count'], 1)
                self.assertEqual(on_way_snapshot['data']['results'][0]['order_id'], on_way_order.id)

                history_snapshot = initial_messages[4]
                self.assertEqual(history_snapshot['data']['count'], 4)
            finally:
                await communicator.disconnect()

        async_to_sync(run)()

    def test_create_order_pushes_order_upsert_and_history_update(self):
        async def run():
            communicator, _ = await self._connect_customer_socket()
            try:
                response = self._call_view(
                    customer_orders_list_create_view,
                    'POST',
                    '/api/customer/orders/',
                    {
                        'shop_owner_id': self.shop.id,
                        'address': 'شارع التحرير',
                        'items': ['Cola', 'Chips'],
                    },
                    self.customer,
                )
                self.assertEqual(response.status_code, 201)

                events = await self._receive_until_types(
                    communicator,
                    {'order_upsert', 'shop_upsert', 'order_history_entry_upsert'},
                )
                by_type = {event['type']: event for event in events}
                self.assertEqual(by_type['order_upsert']['data']['shop_id'], self.shop.id)
                self.assertEqual(by_type['order_history_entry_upsert']['data']['entry_type'], 'order')
            finally:
                await communicator.disconnect()

        async_to_sync(run)()

    def test_create_inquiry_pushes_shop_upsert_and_history_update(self):
        async def run():
            communicator, _ = await self._connect_customer_socket()
            try:
                response = self._call_view(
                    customer_support_conversations_view,
                    'POST',
                    '/api/customer/support-chats/',
                    {
                        'shop_owner_id': self.shop.id,
                        'conversation_type': 'inquiry',
                        'initial_message': 'استفسار',
                    },
                    self.customer,
                )
                self.assertEqual(response.status_code, 201)

                events = await self._receive_until_types(
                    communicator,
                    {'shop_upsert', 'order_history_entry_upsert'},
                )
                history_event = next(event for event in events if event['type'] == 'order_history_entry_upsert')
                self.assertEqual(history_event['data']['entry_type'], 'chat')
                self.assertEqual(history_event['data']['chat']['conversation_type'], 'inquiry')
            finally:
                await communicator.disconnect()

        async_to_sync(run)()

    def test_create_complaint_pushes_shop_upsert_and_history_update(self):
        async def run():
            communicator, _ = await self._connect_customer_socket()
            try:
                response = self._call_view(
                    customer_support_conversations_view,
                    'POST',
                    '/api/customer/support-chats/',
                    {
                        'shop_owner_id': self.shop.id,
                        'conversation_type': 'complaint',
                        'initial_message': 'شكوى',
                    },
                    self.customer,
                )
                self.assertEqual(response.status_code, 201)

                events = await self._receive_until_types(
                    communicator,
                    {'shop_upsert', 'order_history_entry_upsert'},
                )
                history_event = next(event for event in events if event['type'] == 'order_history_entry_upsert')
                self.assertEqual(history_event['data']['chat']['conversation_type'], 'complaint')
            finally:
                await communicator.disconnect()

        async_to_sync(run)()

    def test_new_message_on_order_updates_orders_shops_and_history(self):
        async def run():
            order = self._create_order()
            self._create_order_message(
                order,
                sender_type='customer',
                content='مرحبا',
                is_read=True,
            )
            customer_socket, _ = await self._connect_customer_socket()
            shop_chat = await self._connect_order_chat_as_shop(order)
            try:
                await shop_chat.send_json_to(
                    {
                        'type': 'send_message',
                        'message_type': 'text',
                        'content': 'تم استلام طلبك',
                    }
                )
                events = await self._receive_until_types(
                    customer_socket,
                    {'order_upsert', 'shop_upsert', 'order_history_entry_upsert'},
                )
                order_event = next(event for event in events if event['type'] == 'order_upsert')
                self.assertEqual(order_event['data']['id'], order.id)
                self.assertEqual(order_event['data']['unread_messages_count'], 1)
                self.assertEqual(order_event['data']['last_message']['content'], 'تم استلام طلبك')
            finally:
                await shop_chat.disconnect()
                await customer_socket.disconnect()

        async_to_sync(run)()

    def test_new_message_on_support_updates_shops_and_history(self):
        async def run():
            conversation = self._create_support_conversation(conversation_type='inquiry')
            self._create_support_message(
                conversation,
                sender_type='customer',
                content='استفسار',
                is_read=True,
            )
            customer_socket, _ = await self._connect_customer_socket()
            support_chat = await self._connect_support_chat_as_shop(conversation)
            try:
                await support_chat.send_json_to(
                    {
                        'type': 'send_message',
                        'message_type': 'text',
                        'content': 'هذا رد من المحل',
                    }
                )
                events = await self._receive_until_types(
                    customer_socket,
                    {'shop_upsert', 'order_history_entry_upsert'},
                )
                history_event = next(event for event in events if event['type'] == 'order_history_entry_upsert')
                self.assertEqual(history_event['data']['chat']['chat_status'], 'answered')
            finally:
                await support_chat.disconnect()
                await customer_socket.disconnect()

        async_to_sync(run)()

    def test_order_enters_on_way_pushes_on_way_upsert(self):
        async def run():
            order = self._create_order(status='new')
            customer_socket, _ = await self._connect_customer_socket()
            try:
                response = self._call_view(
                    lambda request: order_detail_view(request, order.id),
                    'PUT',
                    f'/api/shop/orders/{order.id}/',
                    {
                        'status': 'confirmed',
                        'driver_id': self.driver.id,
                    },
                    self.shop,
                )
                self.assertEqual(response.status_code, 200)

                events = await self._receive_until_types(
                    customer_socket,
                    {'order_upsert', 'on_way_upsert', 'order_history_entry_upsert'},
                )
                on_way_event = next(event for event in events if event['type'] == 'on_way_upsert')
                self.assertEqual(on_way_event['data']['order_id'], order.id)
                self.assertEqual(on_way_event['data']['driver_id'], self.driver.id)
            finally:
                await customer_socket.disconnect()

        async_to_sync(run)()

    def test_order_leaves_on_way_pushes_on_way_remove(self):
        async def run():
            order = self._create_order(status='confirmed', driver=self.driver)
            customer_socket, _ = await self._connect_customer_socket()
            try:
                response = self._call_view(
                    lambda request: order_detail_view(request, order.id),
                    'PUT',
                    f'/api/shop/orders/{order.id}/',
                    {
                        'status': 'delivered',
                    },
                    self.shop,
                )
                self.assertEqual(response.status_code, 200)

                events = await self._receive_until_types(
                    customer_socket,
                    {'order_remove', 'on_way_remove', 'order_history_entry_upsert'},
                )
                self.assertEqual(
                    next(event for event in events if event['type'] == 'on_way_remove')['data']['order_id'],
                    order.id,
                )
            finally:
                await customer_socket.disconnect()

        async_to_sync(run)()

    def test_reconnect_returns_latest_full_consistent_state(self):
        async def run():
            order = self._create_order(status='new')
            communicator, _ = await self._connect_customer_socket()
            await communicator.disconnect()

            response = self._call_view(
                lambda request: order_detail_view(request, order.id),
                'PUT',
                f'/api/shop/orders/{order.id}/',
                {
                    'status': 'delivered',
                },
                self.shop,
            )
            self.assertEqual(response.status_code, 200)

            reconnect_socket, initial_messages = await self._connect_customer_socket()
            try:
                orders_snapshot = initial_messages[1]
                history_snapshot = initial_messages[4]
                self.assertEqual(orders_snapshot['data']['count'], 0)
                self.assertEqual(history_snapshot['data']['count'], 1)
                self.assertEqual(history_snapshot['data']['results'][0]['order']['history_status'], 'delivered')
            finally:
                await reconnect_socket.disconnect()

        async_to_sync(run)()

    def test_latest_interaction_per_shop_is_deduplicated_correctly(self):
        async def run():
            older_order = self._create_order(created_at=timezone.now() - timedelta(hours=2))
            self._create_order_message(
                older_order,
                sender_type='shop_owner',
                content='رسالة قديمة',
                is_read=False,
                created_at=timezone.now() - timedelta(hours=2) + timedelta(minutes=5),
            )
            newer_support = self._create_support_conversation(
                conversation_type='inquiry',
                created_at=timezone.now() - timedelta(hours=1),
            )
            self._create_support_message(
                newer_support,
                sender_type='customer',
                content='استفسار أحدث',
                is_read=False,
                created_at=timezone.now() - timedelta(hours=1) + timedelta(minutes=10),
            )

            communicator, initial_messages = await self._connect_customer_socket()
            try:
                shops_snapshot = initial_messages[2]
                self.assertEqual(shops_snapshot['data']['count'], 1)
                self.assertEqual(
                    shops_snapshot['data']['results'][0]['chat']['support_conversation_id'],
                    newer_support.public_id,
                )
            finally:
                await communicator.disconnect()

        async_to_sync(run)()

    def test_unread_counts_are_correct_for_customer_side(self):
        async def run():
            order = self._create_order()
            self._create_order_message(
                order,
                sender_type='shop_owner',
                content='رسالة أولى',
                is_read=False,
            )
            self._create_order_message(
                order,
                sender_type='shop_owner',
                content='رسالة ثانية',
                is_read=False,
            )
            self._create_order_message(
                order,
                sender_type='customer',
                content='رسالة من العميل',
                is_read=False,
            )

            customer_socket, initial_messages = await self._connect_customer_socket()
            customer_chat = await self._connect_order_chat_as_customer(order)
            try:
                orders_snapshot = initial_messages[1]
                self.assertEqual(orders_snapshot['data']['results'][0]['unread_messages_count'], 2)

                await customer_chat.send_json_to({'type': 'mark_read'})
                events = await self._receive_until_types(
                    customer_socket,
                    {'order_upsert', 'shop_upsert', 'order_history_entry_upsert'},
                )
                order_event = next(event for event in events if event['type'] == 'order_upsert')
                self.assertEqual(order_event['data']['unread_messages_count'], 0)
                self.assertFalse(order_event['data']['has_unread_messages'])
            finally:
                await customer_chat.disconnect()
                await customer_socket.disconnect()

        async_to_sync(run)()

    def test_order_history_ordering_is_correct_descending_by_ordered_at(self):
        async def run():
            now = timezone.now()
            oldest_order = self._create_order(created_at=now - timedelta(days=2))
            middle_chat = self._create_support_conversation(
                conversation_type='complaint',
                created_at=now - timedelta(days=1),
            )
            newest_order = self._create_order(created_at=now)

            communicator, initial_messages = await self._connect_customer_socket()
            try:
                history_snapshot = initial_messages[4]
                result_ids = [entry['id'] for entry in history_snapshot['data']['results']]
                self.assertEqual(
                    result_ids[:3],
                    [f'order_{newest_order.id}', middle_chat.public_id, f'order_{oldest_order.id}'],
                )
            finally:
                await communicator.disconnect()

        async_to_sync(run)()

    def test_refresh_all_returns_all_snapshots_in_order(self):
        async def run():
            communicator, _ = await self._connect_customer_socket(route_prefix='/ws/orders/customer')
            try:
                await communicator.send_json_to({'type': 'refresh_all'})
                refreshed = [await communicator.receive_json_from() for _ in range(4)]
                self.assertEqual(
                    [payload['type'] for payload in refreshed],
                    [
                        'orders_snapshot',
                        'shops_snapshot',
                        'on_way_snapshot',
                        'order_history_snapshot',
                    ],
                )
            finally:
                await communicator.disconnect()

        async_to_sync(run)()
