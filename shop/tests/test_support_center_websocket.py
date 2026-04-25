import asyncio

from channels.routing import ProtocolTypeRouter, URLRouter
from channels.testing import WebsocketCommunicator
from django.test import TransactionTestCase, override_settings
from rest_framework_simplejwt.tokens import RefreshToken

from shop.middleware import JWTAuthMiddleware
from shop.routing import websocket_urlpatterns
from shop.models import AccountModerationStatus
from user.models import AdminDesktopUser, ShopCategory, ShopOwner
from shop.models import Employee


@override_settings(
    CHANNEL_LAYERS={'default': {'BACKEND': 'channels.layers.InMemoryChannelLayer'}},
    ALLOWED_HOSTS=['testserver', 'localhost', '127.0.0.1'],
)
class SupportCenterWebSocketTests(TransactionTestCase):
    reset_sequences = True

    def setUp(self):
        super().setUp()
        self.application = ProtocolTypeRouter(
            {
                'websocket': JWTAuthMiddleware(URLRouter(websocket_urlpatterns)),
            }
        )
        self.category = ShopCategory.objects.create(name='Support Category')
        self.shop = ShopOwner.objects.create(
            owner_name='صاحب المحل',
            shop_name='متجر التجربة',
            shop_number='SHOP-SUP-1',
            phone_number='01010000091',
            password='secret123',
            shop_category=self.category,
        )
        self.employee = Employee.objects.create(
            shop_owner=self.shop,
            name='موظف المحل',
            phone_number='01010000092',
            password='secret123',
            role='manager',
        )
        self.admin_user = AdminDesktopUser.objects.create(
            name='دعم الشركة',
            phone_number='01010000093',
            password='secret123',
            role='technical_support',
        )

    def _shop_token(self):
        refresh = RefreshToken()
        refresh['shop_owner_id'] = self.shop.id
        refresh['user_id'] = self.shop.id
        refresh['shop_number'] = self.shop.shop_number
        refresh['user_type'] = 'shop_owner'
        return str(refresh.access_token)

    def _admin_token(self):
        refresh = RefreshToken()
        refresh['admin_desktop_user_id'] = self.admin_user.id
        refresh['permissions'] = self.admin_user.get_resolved_permissions()
        refresh['user_type'] = 'admin_desktop'
        return str(refresh.access_token)

    async def _connect_shop(self):
        communicator = WebsocketCommunicator(
            self.application,
            f'/ws/support-center/shop/{self.shop.id}/?token={self._shop_token()}&lang=ar',
        )
        connected, _ = await communicator.connect()
        self.assertTrue(connected)
        connection = await communicator.receive_json_from()
        snapshot = await communicator.receive_json_from()
        return communicator, connection, snapshot

    async def _connect_admin(self):
        communicator = WebsocketCommunicator(
            self.application,
            f'/ws/support-center/admin/{self.admin_user.id}/?token={self._admin_token()}&lang=ar',
        )
        connected, _ = await communicator.connect()
        self.assertTrue(connected)
        connection = await communicator.receive_json_from()
        snapshot = await communicator.receive_json_from()
        return communicator, connection, snapshot

    def test_admin_desktop_can_authenticate_over_websocket(self):
        async def scenario():
            communicator, connection, snapshot = await self._connect_admin()
            self.assertEqual(connection['type'], 'support.connection')
            self.assertEqual(snapshot['type'], 'support.snapshot')
            await communicator.disconnect()

        asyncio.run(scenario())

    def test_suspended_shop_owner_socket_emits_account_suspended_event(self):
        self.shop.admin_status = 'suspended'
        self.shop.is_active = False
        self.shop.suspension_reason = 'Suspended by company dashboard'
        self.shop.save(update_fields=['admin_status', 'is_active', 'suspension_reason'])
        AccountModerationStatus.objects.create(
            shop_owner=self.shop,
            is_suspended=True,
            suspension_reason='Suspended by company dashboard',
        )

        async def scenario():
            communicator = WebsocketCommunicator(
                self.application,
                f'/ws/support-center/shop/{self.shop.id}/?token={self._shop_token()}&lang=en',
            )
            connected, _ = await communicator.connect()
            self.assertTrue(connected)
            payload = await communicator.receive_json_from()
            self.assertEqual(payload['type'], 'account_suspended')
            self.assertEqual(payload['code'], 'account_suspended')
            self.assertEqual(payload['message'], 'Your account has been suspended. Please contact support.')
            self.assertEqual(payload['reason'], 'Suspended by company dashboard')
            closed = await communicator.wait_closed()
            self.assertTrue(closed)

        asyncio.run(scenario())

    def test_shop_ticket_creation_and_admin_reply_broadcast(self):
        async def scenario():
            shop_socket, _, shop_snapshot = await self._connect_shop()
            admin_socket, _, admin_snapshot = await self._connect_admin()

            self.assertEqual(shop_snapshot['data']['stats']['total'], 0)
            self.assertEqual(admin_snapshot['data']['stats']['total'], 0)

            await shop_socket.send_json_to(
                {
                    'action': 'support.ticket.create',
                    'request_id': 'req-create',
                    'subject': 'POS crashes when confirming order',
                    'priority': 'high',
                    'initial_message': 'التطبيق بيقفل عند الضغط على تأكيد الطلب.',
                }
            )

            shop_created = await shop_socket.receive_json_from()
            admin_created = await admin_socket.receive_json_from()
            ticket_id = shop_created['data']['ticket']['ticket_id']
            self.assertEqual(shop_created['type'], 'support.ticket.created')
            self.assertEqual(admin_created['type'], 'support.ticket.created')

            await shop_socket.receive_json_from()  # message_created
            await shop_socket.receive_json_from()  # ticket_updated
            await shop_socket.receive_json_from()  # thread
            shop_ack = await shop_socket.receive_json_from()
            self.assertEqual(shop_ack['type'], 'support.ack')
            self.assertEqual(shop_ack['action'], 'support.ticket.create')

            await admin_socket.receive_json_from()  # message_created
            admin_ticket_updated = await admin_socket.receive_json_from()
            self.assertEqual(admin_ticket_updated['type'], 'support.ticket.updated')
            self.assertEqual(admin_ticket_updated['data']['ticket']['unread_for_admin_count'], 1)

            await admin_socket.send_json_to(
                {
                    'action': 'support.ticket.send_message',
                    'request_id': 'req-reply',
                    'ticket_id': ticket_id,
                    'message_type': 'text',
                    'content': 'تم استلام البلاغ وجاري الفحص الآن.',
                }
            )

            admin_message = await admin_socket.receive_json_from()
            shop_message = await shop_socket.receive_json_from()
            self.assertEqual(admin_message['type'], 'support.ticket.message_created')
            self.assertEqual(shop_message['type'], 'support.ticket.message_created')

            admin_update = await admin_socket.receive_json_from()
            shop_update = await shop_socket.receive_json_from()
            self.assertEqual(admin_update['type'], 'support.ticket.updated')
            self.assertEqual(shop_update['type'], 'support.ticket.updated')
            self.assertEqual(shop_update['data']['ticket']['status'], 'in_progress')
            self.assertEqual(shop_update['data']['ticket']['unread_for_shop_count'], 1)

            admin_ack = await admin_socket.receive_json_from()
            self.assertEqual(admin_ack['type'], 'support.ack')
            self.assertEqual(admin_ack['action'], 'support.ticket.send_message')

            await admin_socket.disconnect()
            await shop_socket.disconnect()

        asyncio.run(scenario())
