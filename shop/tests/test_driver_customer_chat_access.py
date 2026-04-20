import json

from asgiref.sync import async_to_sync
from channels.routing import ProtocolTypeRouter, URLRouter
from channels.testing import WebsocketCommunicator
from django.test import TransactionTestCase, override_settings
from django.utils import timezone
from django.core.files.uploadedfile import SimpleUploadedFile
from rest_framework.test import APIRequestFactory, force_authenticate
from rest_framework_simplejwt.tokens import RefreshToken

from shop.middleware import JWTAuthMiddleware
from shop.models import ChatMessage, Customer, Driver, Order, ShopDriver
from shop.routing import websocket_urlpatterns
from shop.views import chat_order_media_upload_view, customer_order_chat_view, driver_order_chat_view
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
        refresh = RefreshToken()
        refresh['customer_id'] = customer.id
        refresh['phone_number'] = customer.phone_number
        refresh['user_type'] = 'customer'
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

    def test_customer_chat_get_returns_json_404_for_missing_order(self):
        request = self.factory.get('/api/customer/orders/999999/chat/')
        force_authenticate(request, user=self.customer)

        response = customer_order_chat_view(request, 999999)

        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.data['message'], 'Chat not found')

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
