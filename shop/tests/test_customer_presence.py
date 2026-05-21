from datetime import timedelta

from django.test import TestCase, override_settings
from django.utils import timezone

from shop.models import Customer, CustomerPresenceConnection, Driver, Order, ShopDriver
from shop.realtime.driver import build_driver_order_payload
from shop.realtime.presence import (
    CUSTOMER_PRESENCE_TIMEOUT_SECONDS,
    get_order_customer_presence_snapshot,
    mark_customer_connection_timed_out,
    mark_customer_websocket_connected,
    mark_customer_websocket_disconnected,
    touch_customer_presence,
)
from user.models import ShopCategory, ShopOwner


class CustomerPresenceServiceTests(TestCase):
    def setUp(self):
        super().setUp()
        self.category = ShopCategory.objects.create(name='Presence Category')
        self.shop = ShopOwner.objects.create(
            owner_name='Shop Owner',
            shop_name='Presence Store',
            shop_number='SHOP-CUST-PRES-1',
            phone_number='01010004001',
            password='secret123',
            shop_category=self.category,
        )
        self.customer = Customer.objects.create(
            shop_owner=self.shop,
            name='Presence Customer',
            phone_number='01010004002',
            password='secret123',
        )
        self.driver = Driver.objects.create(
            name='Presence Driver',
            phone_number='01010004003',
            password='secret123',
            is_verified=True,
            is_online=True,
            availability_enabled=True,
            status='available',
        )
        ShopDriver.objects.create(shop_owner=self.shop, driver=self.driver, status='active')
        self.order = Order.objects.create(
            shop_owner=self.shop,
            customer=self.customer,
            driver=self.driver,
            order_number='OD-CUST-PRES-1',
            status='confirmed',
            items='["meal"]',
            total_amount='120.00',
            delivery_fee='15.00',
            address='Tahrir Street',
            notes='',
            driver_assigned_at=timezone.now(),
            driver_accepted_at=timezone.now(),
        )

    def test_customer_presence_uses_active_connection_count(self):
        first = mark_customer_websocket_connected(self.customer.id, 'cust-pres-1', connection_type='orders')
        second = mark_customer_websocket_connected(self.customer.id, 'cust-pres-2', connection_type='chat')

        self.customer.refresh_from_db()
        self.assertTrue(first['is_online'])
        self.assertTrue(second['is_online'])
        self.assertTrue(self.customer.is_online)

        still_online = mark_customer_websocket_disconnected('cust-pres-1')
        self.customer.refresh_from_db()
        self.assertTrue(still_online['is_online'])
        self.assertTrue(self.customer.is_online)

        offline = mark_customer_websocket_disconnected('cust-pres-2')
        self.customer.refresh_from_db()
        self.assertFalse(offline['is_online'])
        self.assertFalse(self.customer.is_online)
        self.assertIsNotNone(self.customer.last_seen)

    def test_touch_customer_presence_refreshes_heartbeat(self):
        mark_customer_websocket_connected(self.customer.id, 'cust-touch', connection_type='orders')
        connection = CustomerPresenceConnection.objects.get(channel_name='cust-touch')
        old_heartbeat = timezone.now() - timedelta(seconds=30)
        connection.last_heartbeat_at = old_heartbeat
        connection.save(update_fields=['last_heartbeat_at'])

        touch_customer_presence('cust-touch', self.customer.id)

        connection.refresh_from_db()
        self.assertGreater(connection.last_heartbeat_at, old_heartbeat)

    def test_stale_customer_connection_times_out_and_marks_offline(self):
        mark_customer_websocket_connected(self.customer.id, 'cust-timeout', connection_type='orders')
        connection = CustomerPresenceConnection.objects.get(channel_name='cust-timeout')
        connection.last_heartbeat_at = timezone.now() - timedelta(seconds=CUSTOMER_PRESENCE_TIMEOUT_SECONDS + 5)
        connection.save(update_fields=['last_heartbeat_at'])

        timed_out = mark_customer_connection_timed_out('cust-timeout')

        self.customer.refresh_from_db()
        self.assertTrue(timed_out['timed_out'])
        self.assertFalse(self.customer.is_online)
        self.assertFalse(CustomerPresenceConnection.objects.filter(channel_name='cust-timeout').exists())
        self.assertIsNotNone(self.customer.last_seen)

    @override_settings(CUSTOMER_PHONE_REVEAL_DELAY_SECONDS=120)
    def test_order_snapshot_marks_stale_customer_offline_and_exposes_phone_timer(self):
        self.customer.is_online = True
        self.customer.last_seen = timezone.now()
        self.customer.save(update_fields=['is_online', 'last_seen', 'updated_at'])
        CustomerPresenceConnection.objects.create(
            customer=self.customer,
            channel_name='cust-stale-snapshot',
            connection_type='chat',
            last_heartbeat_at=timezone.now() - timedelta(seconds=CUSTOMER_PRESENCE_TIMEOUT_SECONDS + 5),
        )

        snapshot = get_order_customer_presence_snapshot(self.order.id)

        self.customer.refresh_from_db()
        self.assertFalse(snapshot['is_online'])
        self.assertEqual(snapshot['customer_online_status'], 'offline')
        self.assertFalse(self.customer.is_online)
        self.assertIsNotNone(snapshot['offline_since'])
        self.assertIsNotNone(snapshot['phone_available_at'])
        self.assertGreater(snapshot['remaining_seconds'], 0)
        self.assertFalse(snapshot['can_show_customer_phone'])

    @override_settings(CUSTOMER_PHONE_REVEAL_DELAY_SECONDS=120)
    def test_driver_order_payload_uses_presence_snapshot_for_customer_status(self):
        self.customer.is_online = True
        self.customer.last_seen = timezone.now()
        self.customer.save(update_fields=['is_online', 'last_seen', 'updated_at'])
        CustomerPresenceConnection.objects.create(
            customer=self.customer,
            channel_name='cust-stale-driver-payload',
            connection_type='orders',
            last_heartbeat_at=timezone.now() - timedelta(seconds=CUSTOMER_PRESENCE_TIMEOUT_SECONDS + 5),
        )

        payload = build_driver_order_payload(self.order)

        self.assertFalse(payload['customer']['is_online'])
        self.assertIsNotNone(payload['customer']['last_seen'])
