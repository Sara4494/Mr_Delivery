from datetime import timedelta

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from shop.driver_chat.service import (
    DRIVER_PRESENCE_TIMEOUT_SECONDS,
    get_driver_presence_snapshot,
    mark_driver_connected,
    mark_driver_connection_timed_out,
    mark_driver_disconnected,
    touch_driver_presence,
)
from shop.models import Customer, Driver, DriverPresenceConnection, Order
from user.models import ShopCategory, ShopOwner


class DriverPresenceServiceTests(TestCase):
    def setUp(self):
        super().setUp()
        self.category = ShopCategory.objects.create(name='Presence Category')
        self.shop = ShopOwner.objects.create(
            owner_name='صاحب المحل',
            shop_name='متجر الحضور',
            shop_number='SHOP-PRES-1',
            phone_number='01010001001',
            password='secret123',
            shop_category=self.category,
        )
        self.driver = Driver.objects.create(
            name='مندوب الحضور',
            phone_number='01010001002',
            password='secret123',
            is_verified=True,
            status='available',
        )
        self.customer = Customer.objects.create(
            shop_owner=self.shop,
            name='عميل الحضور',
            phone_number='01010001003',
            password='secret123',
        )
        self.driver.shops.add(self.shop)
        self.order = Order.objects.create(
            shop_owner=self.shop,
            customer=self.customer,
            driver=self.driver,
            order_number='OD-PRES-1',
            status='confirmed',
            items='["وجبة"]',
            total_amount='120.00',
            delivery_fee='15.00',
            address='شارع النيل',
            notes='',
        )

    def test_presence_uses_active_connection_count(self):
        first = mark_driver_connected(self.driver.id, 'presence-chan-1', connection_type='driver_socket')
        second = mark_driver_connected(self.driver.id, 'presence-chan-2', connection_type='order_chat')

        self.driver.refresh_from_db()
        self.assertTrue(first['is_online'])
        self.assertEqual(second['active_connections_count'], 2)
        self.assertTrue(self.driver.is_online)

        still_online = mark_driver_disconnected('presence-chan-1')
        self.driver.refresh_from_db()
        self.assertTrue(still_online['is_online'])
        self.assertEqual(still_online['active_connections_count'], 1)
        self.assertTrue(self.driver.is_online)

        offline = mark_driver_disconnected('presence-chan-2')
        self.driver.refresh_from_db()
        self.assertFalse(offline['is_online'])
        self.assertEqual(offline['active_connections_count'], 0)
        self.assertFalse(self.driver.is_online)
        self.assertIsNotNone(self.driver.last_seen_at)

    def test_stale_connection_times_out_and_updates_last_seen(self):
        mark_driver_connected(self.driver.id, 'presence-timeout', connection_type='driver_socket')
        connection = DriverPresenceConnection.objects.get(channel_name='presence-timeout')
        connection.last_heartbeat_at = timezone.now() - timedelta(seconds=DRIVER_PRESENCE_TIMEOUT_SECONDS + 5)
        connection.save(update_fields=['last_heartbeat_at'])

        timed_out = mark_driver_connection_timed_out('presence-timeout')

        self.driver.refresh_from_db()
        self.assertTrue(timed_out['timed_out'])
        self.assertFalse(self.driver.is_online)
        self.assertFalse(DriverPresenceConnection.objects.filter(channel_name='presence-timeout').exists())
        self.assertIsNotNone(self.driver.last_seen_at)

    def test_touch_driver_presence_refreshes_heartbeat(self):
        mark_driver_connected(self.driver.id, 'presence-touch', connection_type='driver_socket')
        connection = DriverPresenceConnection.objects.get(channel_name='presence-touch')
        old_heartbeat = timezone.now() - timedelta(seconds=30)
        connection.last_heartbeat_at = old_heartbeat
        connection.save(update_fields=['last_heartbeat_at'])

        touch_driver_presence('presence-touch', self.driver.id)

        connection.refresh_from_db()
        self.assertGreater(connection.last_heartbeat_at, old_heartbeat)


class DriverPresenceApiTests(TestCase):
    def setUp(self):
        super().setUp()
        self.client = APIClient()
        self.category = ShopCategory.objects.create(name='Presence API Category')
        self.shop = ShopOwner.objects.create(
            owner_name='صاحب المحل',
            shop_name='متجر الـ API',
            shop_number='SHOP-PRES-2',
            phone_number='01010002001',
            password='secret123',
            shop_category=self.category,
        )
        self.driver = Driver.objects.create(
            name='مندوب API',
            phone_number='01010002002',
            password='secret123',
            is_verified=True,
            status='available',
        )
        self.customer = Customer.objects.create(
            shop_owner=self.shop,
            name='عميل API',
            phone_number='01010002003',
            password='secret123',
        )
        self.driver.shops.add(self.shop)
        self.order = Order.objects.create(
            shop_owner=self.shop,
            customer=self.customer,
            driver=self.driver,
            order_number='OD-PRES-2',
            status='confirmed',
            items='["طلب"]',
            total_amount='95.00',
            delivery_fee='10.00',
            address='شارع الجامعة',
            notes='',
        )

    def test_presence_endpoint_returns_websocket_derived_data(self):
        mark_driver_connected(self.driver.id, 'presence-api', connection_type='driver_socket')
        self.client.force_authenticate(user=self.customer)

        response = self.client.get(f'/api/drivers/{self.driver.id}/presence/')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['data']['driver_id'], self.driver.id)
        self.assertTrue(response.data['data']['is_online'])
        self.assertEqual(
            response.data['data']['last_seen_at'],
            get_driver_presence_snapshot(self.driver.id)['last_seen_at'],
        )

    def test_driver_customer_chat_bootstrap_includes_driver_presence(self):
        mark_driver_connected(self.driver.id, 'presence-bootstrap', connection_type='driver_socket')
        self.client.force_authenticate(user=self.customer)

        response = self.client.get(f'/api/customer/orders/{self.order.id}/chat/?chat_type=driver_customer')

        self.assertEqual(response.status_code, 200)
        self.assertIn('driver_presence', response.data['data'])
        self.assertTrue(response.data['data']['driver_presence']['is_online'])
