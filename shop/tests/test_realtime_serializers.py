from decimal import Decimal

from django.utils import timezone
from django.test import TestCase

from shop.models import ChatMessage, Customer, Driver, Order
from shop.realtime.serializers import ShopOrderRealtimeSerializer
from shop.realtime.customer_app import CustomerAppRealtimeOnWaySerializer
from user.models import ShopCategory, ShopOwner


class ShopRealtimeSerializerTests(TestCase):
    def setUp(self):
        super().setUp()
        self.category = ShopCategory.objects.create(name='Fast Food')
        self.shop_owner = ShopOwner.objects.create(
            owner_name='Shop Owner',
            shop_name='Demo Shop',
            shop_number='SHOP-100',
            phone_number='01000000001',
            password='secret123',
            shop_category=self.category,
        )
        self.customer = Customer.objects.create(
            shop_owner=self.shop_owner,
            name='Customer One',
            phone_number='01000000002',
            is_verified=True,
        )
        self.order = Order.objects.create(
            shop_owner=self.shop_owner,
            customer=self.customer,
            order_number='ODTEST01',
            status='new',
            items='[]',
            total_amount=Decimal('100.00'),
            delivery_fee=Decimal('10.00'),
            address='Cairo',
        )
        self.driver = Driver.objects.create(
            name='Driver One',
            phone_number='01000000003',
            status='available',
        )

    def test_customer_on_way_entry_exposes_driver_chat_after_acceptance(self):
        self.order.driver = self.driver
        self.order.status = 'on_way'
        self.order.driver_accepted_at = timezone.now()
        self.order.save(update_fields=['driver', 'status', 'driver_accepted_at', 'updated_at'])

        payload = CustomerAppRealtimeOnWaySerializer(
            self.order,
            context={'base_url': 'http://testserver'},
        ).data

        self.assertEqual(payload['driver_id'], self.driver.id)
        self.assertEqual(payload['driver_name'], self.driver.name)
        self.assertIsNotNone(payload['chat'])
        self.assertEqual(payload['chat']['chat_type'], 'driver_customer')
        self.assertTrue(payload['chat']['can_open'])

    def test_shop_order_unread_count_ignores_shop_auto_reply(self):
        ChatMessage.objects.create(
            order=self.order,
            chat_type='shop_customer',
            sender_type='customer',
            sender_customer=self.customer,
            message_type='text',
            content='hello',
        )
        ChatMessage.objects.create(
            order=self.order,
            chat_type='shop_customer',
            sender_type='shop_owner',
            sender_shop_owner=self.shop_owner,
            message_type='text',
            content='تم استلام طلبك ويرجى الانتظار حتى يتم إرسال الفاتورة.',
        )

        payload = ShopOrderRealtimeSerializer(
            self.order,
            context={'base_url': 'http://testserver'},
        ).data

        self.assertEqual(payload['unread_messages_count'], 1)
        self.assertEqual(payload['last_message']['sender_type'], 'shop_owner')
