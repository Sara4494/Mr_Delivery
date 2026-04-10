from unittest.mock import patch

from django.test import TestCase

from shop.websocket_utils import broadcast_chat_message
from shop.models import Customer, Order
from user.models import ShopCategory, ShopOwner


class BroadcastChatMessageTests(TestCase):
    def setUp(self):
        super().setUp()
        self.category = ShopCategory.objects.create(name='Groceries')
        self.shop = ShopOwner.objects.create(
            owner_name='مالك المحل',
            shop_name='متجر التجربة',
            shop_number='SHOP-200',
            phone_number='01010000020',
            password='secret123',
            shop_category=self.category,
        )
        self.customer = Customer.objects.create(
            shop_owner=self.shop,
            name='أحمد',
            phone_number='01020000020',
            password='secret123',
        )
        self.order = Order.objects.create(
            shop_owner=self.shop,
            customer=self.customer,
            order_number='ODTEST200',
            status='confirmed',
            items='["وجبة"]',
            total_amount='150.00',
            delivery_fee='20.00',
            address='شارع التحرير',
            notes='',
        )

    @patch('shop.websocket_utils.send_order_chat_push_fallback', return_value={})
    @patch('shop.websocket_utils.broadcast_customer_order_changed')
    @patch('shop.websocket_utils.send_to_group')
    def test_shop_customer_message_notifies_customer_orders_group(
        self,
        mock_send_to_group,
        mock_broadcast_customer_order_changed,
        mock_send_push,
    ):
        broadcast_chat_message(
            self.order.id,
            'shop_customer',
            {
                'id': 10,
                'sender_type': 'shop_owner',
                'sender_name': 'المحل',
                'message_type': 'text',
                'content': 'تم تأكيد طلبك',
            },
        )

        sent_groups = [call.args[0] for call in mock_send_to_group.call_args_list]
        self.assertIn(f'shop_orders_{self.shop.id}', sent_groups)
        self.assertIn(f'customer_orders_{self.customer.id}', sent_groups)
        mock_broadcast_customer_order_changed.assert_not_called()
        mock_send_push.assert_called_once()
