import json
from datetime import timedelta

from asgiref.sync import async_to_sync
from channels.routing import ProtocolTypeRouter, URLRouter
from channels.testing import WebsocketCommunicator
from django.test import TransactionTestCase, override_settings
from django.utils import timezone
from django.core.files.uploadedfile import SimpleUploadedFile
from rest_framework.test import APIRequestFactory, force_authenticate
from rest_framework_simplejwt.tokens import RefreshToken

from shop.middleware import JWTAuthMiddleware
from shop.models import ChatMessage, ChatParticipantBlock, Customer, Driver, Order, ShopDriver
from shop.routing import websocket_urlpatterns
from shop.views import (
    chat_block_detail_view,
    chat_blocks_view,
    chat_message_image_delete_view,
    chat_order_media_upload_view,
    customer_order_chat_view,
    driver_order_customer_contact_status_view,
    driver_order_chat_open_view,
    driver_order_chat_view,
)
from user.authentication import build_session_refresh_token, rotate_user_session
from user.models import ShopCategory, ShopOwner


@override_settings(
    CHANNEL_LAYERS={'default': {'BACKEND': 'channels.layers.InMemoryChannelLayer'}},
    ALLOWED_HOSTS=['testserver', 'localhost', '127.0.0.1'],
)
class DriverCustomerChatAccessTests(TransactionTestCase):
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
            shop_name='متجر التجربة',
            shop_number='SHOP-CHAT-001',
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

    def _next_order_number(self):
        return f'OD{Order.objects.count() + 1:06d}'

    def _customer_access_token(self, customer=None):
        customer = customer or self.customer
        if not customer.active_session_key:
            rotate_user_session(customer)
            customer.save(update_fields=['active_session_key'])
        refresh = build_session_refresh_token(user=customer, user_type='customer')
        return str(refresh.access_token)

    def _driver_access_token(self, driver=None):
        driver = driver or self.driver
        if not driver.active_session_key:
            rotate_user_session(driver)
            driver.save(update_fields=['active_session_key'])
        refresh = build_session_refresh_token(user=driver, user_type='driver')
        return str(refresh.access_token)

    def _create_order(self, *, accepted=False):
        accepted_at = timezone.now() if accepted else None
        return Order.objects.create(
            shop_owner=self.shop,
            customer=self.customer,
            driver=self.driver,
            order_number=self._next_order_number(),
            status='confirmed',
            items=json.dumps(['Cola', 'Chips'], ensure_ascii=False),
            total_amount='150.00',
            delivery_fee='20.00',
            address='شارع السنترال',
            notes='',
            driver_assigned_at=timezone.now(),
            driver_accepted_at=accepted_at,
            driver_chat_opened_at=None,
        )

    def test_chat_get_is_available_immediately_after_accept(self):
        order = self._create_order(accepted=True)

        request = self.factory.get(f'/api/driver/orders/{order.id}/chat/')
        force_authenticate(request, user=self.driver)

        response = driver_order_chat_view(request, order.id)

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data['data']['can_open'])

        order.refresh_from_db()
        self.assertIsNotNone(order.driver_chat_opened_at)

    def test_chat_open_returns_bootstrap_payload_for_new_chat_after_accept(self):
        order = self._create_order(accepted=True)

        request = self.factory.post(f'/api/driver/orders/{order.id}/chat/open/')
        force_authenticate(request, user=self.driver)

        response = driver_order_chat_open_view(request, order.id)

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data['data']['can_open'])
        self.assertEqual(response.data['data']['chat_type'], 'driver_customer')
        self.assertEqual(response.data['data']['messages'], [])
        self.assertFalse(response.data['data']['is_existing'])
        self.assertTrue(response.data['data']['is_new'])
        self.assertEqual(response.data['data']['ws_url'], response.data['data']['ws_path'])

    def test_chat_post_is_forbidden_before_accept(self):
        order = self._create_order(accepted=False)

        request = self.factory.post(
            f'/api/driver/orders/{order.id}/chat/',
            {
                'chat_type': 'driver_customer',
                'message_type': 'text',
                'text': 'مرحبا',
            },
            format='json',
        )
        force_authenticate(request, user=self.driver)

        response = driver_order_chat_view(request, order.id)

        self.assertEqual(response.status_code, 403)
        self.assertFalse(ChatMessage.objects.filter(order=order, chat_type='driver_customer').exists())

    def test_customer_websocket_can_connect_after_accept_without_open_endpoint(self):
        order = self._create_order(accepted=True)
        token = self._customer_access_token()

        async def scenario():
            communicator = WebsocketCommunicator(
                self.application,
                f'/ws/chat/order/{order.id}/?token={token}&chat_type=driver_customer&lang=ar',
            )
            connected, _ = await communicator.connect()
            try:
                self.assertTrue(connected)
            finally:
                await communicator.disconnect()

        async_to_sync(scenario)()

    def test_customer_websocket_is_blocked_before_accept(self):
        order = self._create_order(accepted=False)
        token = self._customer_access_token()

        async def scenario():
            communicator = WebsocketCommunicator(
                self.application,
                f'/ws/chat/order/{order.id}/?token={token}&chat_type=driver_customer&lang=ar',
            )
            connected, _ = await communicator.connect()
            self.assertFalse(connected)

        async_to_sync(scenario)()

    def test_customer_chat_get_returns_json_payload(self):
        order = self._create_order(accepted=True)

        request = self.factory.get(f'/api/customer/orders/{order.id}/chat/')
        force_authenticate(request, user=self.customer)

        response = customer_order_chat_view(request, order.id)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['data']['order_id'], order.id)
        self.assertEqual(response.data['data']['chat_type'], 'driver_customer')
        self.assertTrue(response.data['data']['can_open'])

    def test_driver_chat_bootstrap_hides_customer_phone_while_customer_online(self):
        order = self._create_order(accepted=True)
        self.customer.is_online = True
        self.customer.last_seen = timezone.now()
        self.customer.save(update_fields=['is_online', 'last_seen', 'updated_at'])

        request = self.factory.get(f'/api/driver/orders/{order.id}/chat/')
        force_authenticate(request, user=self.driver)

        response = driver_order_chat_view(request, order.id)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['data']['customer_online_status'], 'online')
        self.assertFalse(response.data['data']['can_show_customer_phone'])
        self.assertIsNone(response.data['data']['customer_phone'])
        self.assertEqual(response.data['data']['remaining_seconds'], 120)

    def test_driver_customer_contact_status_reveals_phone_after_offline_timeout(self):
        order = self._create_order(accepted=True)
        self.customer.is_online = False
        self.customer.last_seen = timezone.now() - timedelta(seconds=125)
        self.customer.save(update_fields=['is_online', 'last_seen', 'updated_at'])

        request = self.factory.get(f'/api/driver/orders/{order.id}/chat/customer-contact/')
        force_authenticate(request, user=self.driver)

        response = driver_order_customer_contact_status_view(request, order.id)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['data']['customer_online_status'], 'offline')
        self.assertTrue(response.data['data']['can_show_customer_phone'])
        self.assertEqual(response.data['data']['customer_phone'], self.customer.phone_number)
        self.assertEqual(response.data['data']['remaining_seconds'], 0)

    def test_customer_chat_get_returns_json_404_for_missing_order(self):
        request = self.factory.get('/api/customer/orders/999999/chat/')
        force_authenticate(request, user=self.customer)

        response = customer_order_chat_view(request, 999999)

        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.data['message'], 'Chat not found')

    @override_settings(CUSTOMER_PHONE_REVEAL_DELAY_SECONDS=1)
    def test_driver_socket_receives_customer_presence_and_phone_availability_events(self):
        order = self._create_order(accepted=True)
        driver_token = self._driver_access_token()
        customer_token = self._customer_access_token()

        async def _drain_initial_messages(communicator):
            received = []
            for _ in range(3):
                received.append(await communicator.receive_json_from())
            return received

        async def _receive_until_type(communicator, expected_type, attempts=8):
            for _ in range(attempts):
                payload = await communicator.receive_json_from(timeout=3)
                if payload.get('type') == expected_type:
                    return payload
            self.fail(f'Missing websocket event: {expected_type}')

        async def scenario():
            driver_socket = WebsocketCommunicator(
                self.application,
                f'/ws/chat/order/{order.id}/?token={driver_token}&chat_type=driver_customer&lang=ar',
            )
            connected, _ = await driver_socket.connect()
            self.assertTrue(connected)
            await _drain_initial_messages(driver_socket)

            customer_socket = WebsocketCommunicator(
                self.application,
                f'/ws/chat/order/{order.id}/?token={customer_token}&chat_type=driver_customer&lang=ar',
            )
            customer_connected, _ = await customer_socket.connect()
            self.assertTrue(customer_connected)
            await _drain_initial_messages(customer_socket)

            customer_online = await _receive_until_type(driver_socket, 'customer_online')
            self.assertTrue(customer_online['data']['is_online'])
            self.assertFalse(customer_online['data']['can_show_customer_phone'])

            await customer_socket.disconnect()

            customer_offline = await _receive_until_type(driver_socket, 'customer_offline')
            self.assertFalse(customer_offline['data']['is_online'])
            self.assertFalse(customer_offline['data']['can_show_customer_phone'])

            phone_available = await _receive_until_type(driver_socket, 'phone_available')
            self.assertTrue(phone_available['data']['can_show_customer_phone'])
            self.assertEqual(phone_available['data']['customer_phone'], self.customer.phone_number)
            self.assertEqual(phone_available['data']['remaining_seconds'], 0)

            await driver_socket.disconnect()

        async_to_sync(scenario)()

    def test_customer_can_upload_driver_chat_image_after_accept(self):
        order = self._create_order(accepted=True)
        image_file = SimpleUploadedFile('chat.jpg', b'fake-image-content', content_type='image/jpeg')

        request = self.factory.post(
            f'/api/chat/order/{order.id}/send-media/',
            {
                'chat_type': 'driver_customer',
                'message_type': 'image',
                'image_file': image_file,
            },
            format='multipart',
        )
        force_authenticate(request, user=self.customer)

        response = chat_order_media_upload_view(request, order.id)

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data['data']['chat_type'], 'driver_customer')
        self.assertEqual(response.data['data']['message_type'], 'image')

    def test_driver_message_sender_name_uses_shop_delegate_label_for_customer_chat(self):
        order = self._create_order(accepted=True)
        message = ChatMessage.objects.create(
            order=order,
            chat_type='driver_customer',
            sender_type='driver',
            sender_driver=self.driver,
            message_type='text',
            content='أنا في الطريق',
        )

        self.assertEqual(message.sender_name, f'مندوب {self.shop.shop_name}')

    def test_customer_cannot_upload_driver_chat_image_before_accept(self):
        order = self._create_order(accepted=False)
        image_file = SimpleUploadedFile('chat.jpg', b'fake-image-content', content_type='image/jpeg')

        request = self.factory.post(
            f'/api/chat/order/{order.id}/send-media/',
            {
                'chat_type': 'driver_customer',
                'message_type': 'image',
                'image_file': image_file,
            },
            format='multipart',
        )
        force_authenticate(request, user=self.customer)

        response = chat_order_media_upload_view(request, order.id)

        self.assertEqual(response.status_code, 403)

    def test_customer_can_block_driver(self):
        request = self.factory.post(
            '/api/chat/blocks/',
            {
                'target_type': 'driver',
                'target_id': self.driver.id,
                'reason': 'spam',
            },
            format='json',
        )
        force_authenticate(request, user=self.customer)

        response = chat_blocks_view(request)

        self.assertEqual(response.status_code, 201)
        self.assertTrue(
            ChatParticipantBlock.objects.filter(
                source_type='customer',
                source_customer=self.customer,
                target_type='driver',
                target_driver=self.driver,
            ).exists()
        )

    def test_customer_block_prevents_driver_customer_media_upload(self):
        order = self._create_order(accepted=True)
        ChatParticipantBlock.objects.create(
            source_type='customer',
            source_customer=self.customer,
            target_type='driver',
            target_driver=self.driver,
            reason='blocked',
        )
        image_file = SimpleUploadedFile('chat.jpg', b'fake-image-content', content_type='image/jpeg')

        request = self.factory.post(
            f'/api/chat/order/{order.id}/send-media/',
            {
                'chat_type': 'driver_customer',
                'message_type': 'image',
                'image_file': image_file,
            },
            format='multipart',
        )
        force_authenticate(request, user=self.driver)

        response = chat_order_media_upload_view(request, order.id)

        self.assertEqual(response.status_code, 403)
        self.assertIn('block', response.data.get('errors', {}))

    def test_customer_block_prevents_driver_customer_text_message(self):
        order = self._create_order(accepted=True)
        ChatParticipantBlock.objects.create(
            source_type='customer',
            source_customer=self.customer,
            target_type='driver',
            target_driver=self.driver,
            reason='blocked',
        )

        request = self.factory.post(
            f'/api/driver/orders/{order.id}/chat/',
            {
                'chat_type': 'driver_customer',
                'message_type': 'text',
                'content': 'hello',
            },
            format='json',
        )
        force_authenticate(request, user=self.driver)

        response = driver_order_chat_view(request, order.id)

        self.assertEqual(response.status_code, 403)
        self.assertIn('block', response.data.get('errors', {}))
        self.assertFalse(
            ChatMessage.objects.filter(
                order=order,
                chat_type='driver_customer',
                sender_type='driver',
                content='hello',
            ).exists()
        )

    def test_customer_can_delete_own_chat_image(self):
        order = self._create_order(accepted=True)
        message = ChatMessage.objects.create(
            order=order,
            chat_type='driver_customer',
            sender_type='customer',
            sender_customer=self.customer,
            message_type='image',
            image_file=SimpleUploadedFile('chat.jpg', b'fake-image-content', content_type='image/jpeg'),
        )

        request = self.factory.delete(f'/api/chat/messages/{message.id}/delete-image/')
        force_authenticate(request, user=self.customer)

        response = chat_message_image_delete_view(request, message.id)

        self.assertEqual(response.status_code, 200)
        message.refresh_from_db()
        self.assertFalse(bool(message.image_file))
        self.assertEqual(message.content, 'تم حذف الصورة')
        self.assertTrue(bool((message.metadata or {}).get('image_deleted')))

    def test_customer_can_unblock_driver(self):
        ChatParticipantBlock.objects.create(
            source_type='customer',
            source_customer=self.customer,
            target_type='driver',
            target_driver=self.driver,
        )

        request = self.factory.delete(f'/api/chat/blocks/driver/{self.driver.id}/')
        force_authenticate(request, user=self.customer)

        response = chat_block_detail_view(request, 'driver', self.driver.id)

        self.assertEqual(response.status_code, 200)
        self.assertFalse(
            ChatParticipantBlock.objects.filter(
                source_type='customer',
                source_customer=self.customer,
                target_type='driver',
                target_driver=self.driver,
            ).exists()
        )
