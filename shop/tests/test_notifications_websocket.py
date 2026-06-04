from channels.db import database_sync_to_async
from channels.routing import ProtocolTypeRouter, URLRouter
from channels.testing import WebsocketCommunicator
from django.test import TransactionTestCase, override_settings

from shop.middleware import JWTAuthMiddleware
from shop.models import Notification
from shop.routing import websocket_urlpatterns
from shop.views import _attach_notification_to_user
from user.authentication import build_session_refresh_token, rotate_user_session
from user.models import ShopCategory, ShopOwner


@override_settings(
    CHANNEL_LAYERS={'default': {'BACKEND': 'channels.layers.InMemoryChannelLayer'}},
    ALLOWED_HOSTS=['testserver', 'localhost', '127.0.0.1'],
)
class ShopNotificationsWebSocketTests(TransactionTestCase):
    reset_sequences = True

    def setUp(self):
        super().setUp()
        self.application = ProtocolTypeRouter(
            {
                'websocket': JWTAuthMiddleware(URLRouter(websocket_urlpatterns)),
            }
        )
        self.category = ShopCategory.objects.create(name='Notifications Category')
        self.shop = ShopOwner.objects.create(
            owner_name='Notifications Owner',
            shop_name='Notifications Store',
            shop_number='SHOP-NOTIF-1',
            phone_number='01020000001',
            password='secret123',
            shop_category=self.category,
        )
        self.other_shop = ShopOwner.objects.create(
            owner_name='Other Owner',
            shop_name='Other Store',
            shop_number='SHOP-NOTIF-2',
            phone_number='01020000002',
            password='secret123',
            shop_category=self.category,
        )

    def _token(self):
        if not self.shop.active_session_key:
            rotate_user_session(self.shop)
            self.shop.save(update_fields=['active_session_key'])
        refresh = build_session_refresh_token(user=self.shop, user_type='shop_owner')
        return str(refresh.access_token)

    async def _connect(self):
        communicator = WebsocketCommunicator(
            self.application,
            f'/ws/notifications/shop/{self.shop.id}/?token={self._token()}&lang=ar',
        )
        connected, _ = await communicator.connect()
        self.assertTrue(connected)
        initial = await communicator.receive_json_from()
        self.assertEqual(initial['type'], 'notifications.initial')
        return communicator

    def test_fetch_returns_only_current_shop_notifications(self):
        Notification.objects.create(
            shop_owner=self.shop,
            notification_type='order_update',
            title='طلب جديد',
            message='تم استلام طلب جديد.',
            data={'order_id': 11, 'order_code': 'OD-11', 'status': 'new'},
        )
        Notification.objects.create(
            shop_owner=self.other_shop,
            notification_type='order_update',
            title='طلب آخر',
            message='طلب لمتجر آخر.',
            data={'order_id': 22, 'order_code': 'OD-22', 'status': 'new'},
        )

        async def scenario():
            communicator = await self._connect()
            await communicator.send_json_to(
                {
                    'action': 'notifications.fetch',
                    'page': 1,
                    'limit': 50,
                }
            )
            payload = await communicator.receive_json_from()
            self.assertEqual(payload['type'], 'notifications.list')
            self.assertEqual(payload['data']['unread_count'], 1)
            self.assertEqual(len(payload['data']['notifications']), 1)
            row = payload['data']['notifications'][0]
            self.assertEqual(row['notification_type'], 'order_update')
            self.assertEqual(row['notification_type_display'], 'تحديث طلب')
            self.assertIsInstance(row['id'], int)
            self.assertIsInstance(row['data'], dict)
            self.assertIn('created_at', row)
            await communicator.disconnect()

        self.async_run(scenario)

    def test_created_read_and_mark_all_read_flow(self):
        async def scenario():
            communicator = await self._connect()

            await database_sync_to_async(_attach_notification_to_user)(
                'shop_owner',
                self.shop,
                title='طلب جديد',
                message='تم استلام طلب جديد رقم #ODUX8NMB',
                notification_type='order_update',
                data={
                    'order_id': 123,
                    'order_code': 'ODUX8NMB',
                    'status': 'new',
                },
            )

            created = await communicator.receive_json_from()
            self.assertEqual(created['type'], 'notification.created')
            self.assertEqual(created['data']['notification_type'], 'order_update')
            self.assertEqual(created['data']['notification_type_display'], 'تحديث طلب')
            self.assertFalse(created['data']['is_read'])
            self.assertEqual(created['unread_count'], 1)

            counts = await communicator.receive_json_from()
            self.assertEqual(counts['type'], 'notifications.counts')
            self.assertEqual(counts['data']['unread_count'], 1)
            self.assertEqual(counts['data']['total_count'], 1)

            notification_id = created['data']['id']
            await communicator.send_json_to(
                {
                    'action': 'notification.mark_read',
                    'notification_id': notification_id,
                }
            )
            marked = await communicator.receive_json_from()
            self.assertEqual(marked['type'], 'notification.read')
            self.assertEqual(marked['data']['notification_id'], notification_id)
            self.assertTrue(marked['data']['is_read'])
            self.assertEqual(marked['data']['unread_count'], 0)

            counts_after_read = await communicator.receive_json_from()
            self.assertEqual(counts_after_read['type'], 'notifications.counts')
            self.assertEqual(counts_after_read['data']['unread_count'], 0)

            await database_sync_to_async(_attach_notification_to_user)(
                'shop_owner',
                self.shop,
                title='إشعار آخر',
                message='إشعار جديد للمتجر',
                notification_type='company_announcement',
                data={},
            )

            await communicator.receive_json_from()  # notification.created
            await communicator.receive_json_from()  # notifications.counts

            await communicator.send_json_to(
                {
                    'action': 'notifications.mark_all_read',
                }
            )
            all_read = await communicator.receive_json_from()
            self.assertEqual(all_read['type'], 'notifications.all_read')
            self.assertEqual(all_read['data']['unread_count'], 0)

            final_counts = await communicator.receive_json_from()
            self.assertEqual(final_counts['type'], 'notifications.counts')
            self.assertEqual(final_counts['data']['unread_count'], 0)
            await communicator.disconnect()

        self.async_run(scenario)

    def test_foreign_shop_path_is_rejected(self):
        async def scenario():
            communicator = WebsocketCommunicator(
                self.application,
                f'/ws/notifications/shop/{self.other_shop.id}/?token={self._token()}&lang=ar',
            )
            connected, _ = await communicator.connect()
            self.assertFalse(connected)

        self.async_run(scenario)

    def async_run(self, coroutine):
        import asyncio

        asyncio.run(coroutine())
