from decimal import Decimal

from django.test import TestCase

from shop.models import ChatMessage, Customer, Order
from shop.realtime.serializers import ShopOrderRealtimeSerializer
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

