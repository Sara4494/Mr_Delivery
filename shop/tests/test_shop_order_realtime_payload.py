from django.test import TestCase
from django.utils import timezone

from shop.realtime.serializers import build_shop_order_realtime_payload
from shop.models import Customer, Driver, Order, ShopDriver
from user.models import ShopCategory, ShopOwner


class ShopOrderRealtimePayloadTests(TestCase):
    def setUp(self):
        super().setUp()
        self.category = ShopCategory.objects.create(name='Deliveries')
        self.shop = ShopOwner.objects.create(
            owner_name='Shop Owner',
            shop_name='Realtime Store',
            shop_number='SHOP-RT-001',
            phone_number='01010014001',
            password='secret123',
            shop_category=self.category,
        )
        self.customer = Customer.objects.create(
            shop_owner=self.shop,
            name='Realtime Customer',
            phone_number='01010014002',
            password='secret123',
        )
        self.driver = Driver.objects.create(
            name='Realtime Driver',
            phone_number='01010014003',
            password='secret123',
            status='available',
        )
        ShopDriver.objects.create(shop_owner=self.shop, driver=self.driver, status='active')

    def _create_order(self, *, status='preparing', accepted_at=None, delivered_at=None):
        return Order.objects.create(
            shop_owner=self.shop,
            customer=self.customer,
            driver=self.driver,
            order_number=f'RT{Order.objects.count() + 1:06d}',
            status=status,
            items='[{"name":"Burger","quantity":1}]',
            total_amount='80.00',
            delivery_fee='10.00',
            address='Test Address',
            notes='',
            driver_assigned_at=timezone.now(),
            driver_accepted_at=accepted_at,
            delivered_at=delivered_at,
        )

    def test_payload_keeps_raw_status_and_full_nested_order_data(self):
        order = self._create_order(status='on_way', accepted_at=timezone.now())

        payload = build_shop_order_realtime_payload(order, lang='ar')

        self.assertEqual(payload['status'], 'on_way')
        self.assertEqual(payload['status_display'], 'المندوب بيوصله')
        self.assertEqual(payload['customer']['id'], self.customer.id)
        self.assertEqual(payload['customer']['name'], self.customer.name)
        self.assertEqual(payload['driver']['id'], self.driver.id)
        self.assertEqual(payload['driver']['name'], self.driver.name)
        self.assertEqual(payload['chat']['thread_id'], str(order.id))
        self.assertEqual(payload['chat']['chat_type'], 'shop_customer')
        self.assertEqual(payload['items'], [{'name': 'Burger', 'quantity': 1}])
        self.assertEqual(payload['delivery_fee'], '10.00')
        self.assertEqual(payload['total_amount'], '80.00')
        self.assertIsNone(payload['last_message'])

    def test_payload_includes_delivered_timestamp_for_delivered_orders(self):
        delivered_at = timezone.now()
        order = self._create_order(status='delivered', accepted_at=timezone.now(), delivered_at=delivered_at)

        payload = build_shop_order_realtime_payload(order, lang='ar')

        self.assertEqual(payload['status'], 'delivered')
        self.assertEqual(payload['status_display'], 'تم التسليم')
        self.assertIsNotNone(payload['delivered_at'])
