from datetime import timedelta
from unittest.mock import AsyncMock, MagicMock, patch

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from shop.models import ChatRing, Customer, Employee, Order
from user.models import ShopCategory, ShopOwner


class ChatRingsApiTests(TestCase):
    def setUp(self):
        super().setUp()
        self.client = APIClient()
        self.category = ShopCategory.objects.create(name='Groceries')
        self.shop = ShopOwner.objects.create(
            owner_name='Shop Owner',
            shop_name='Ring Store',
            shop_number='SHOP-RING-1',
            phone_number='01010000991',
            password='secret123',
            shop_category=self.category,
        )
        self.employee = Employee.objects.create(
            shop_owner=self.shop,
            name='Store Employee',
            phone_number='01010000992',
            password='secret123',
            role='manager',
            is_active=True,
        )
        self.customer = Customer.objects.create(
            shop_owner=self.shop,
            name='Ring Customer',
            phone_number='01010000993',
            password='secret123',
            is_verified=True,
        )
        self.order = Order.objects.create(
            shop_owner=self.shop,
            customer=self.customer,
            order_number='ORD-RING-1',
            items='[]',
            total_amount='100.00',
            delivery_fee='10.00',
            address='Cairo',
        )

    @patch('shop.chat_ring_service._send_ring_event_to_user', return_value={'tokens_sent': 1})
    def test_shop_owner_can_start_chat_ring_for_customer(self, mock_send_ring):
        self.client.force_authenticate(user=self.shop)

        response = self.client.post(
            '/api/chat-rings/start',
            {
                'chat_id': f'order_{self.order.id}_shop_customer',
                'sender_id': self.shop.id,
                'receiver_id': self.customer.id,
                'order_id': self.order.id,
            },
            format='json',
        )

        self.assertEqual(response.status_code, 201)
        ring = ChatRing.objects.get()
        self.assertEqual(ring.status, 'ringing')
        self.assertEqual(ring.sender_type, 'shop_owner')
        self.assertEqual(ring.receiver_type, 'customer')
        self.assertEqual(response.data['data']['duration_seconds'], 30)
        self.assertEqual(response.data['data']['push']['tokens_sent'], 1)
        mock_send_ring.assert_called_once()
        args, kwargs = mock_send_ring.call_args
        self.assertEqual(args[0], 'customer')
        self.assertEqual(args[1], self.customer.id)
        self.assertEqual(args[2]['type'], 'chat_ring')
        self.assertEqual(args[2]['chat_id'], f'order_{self.order.id}_shop_customer')
        self.assertEqual(args[2]['order_id'], str(self.order.id))
        self.assertEqual(args[2]['duration_seconds'], '30')
        self.assertEqual(args[2]['action'], 'open_chat')
        self.assertIn('expires_at', kwargs)

    @patch('shop.chat_ring_service._send_ring_event_to_user', return_value={'tokens_sent': 1})
    def test_duplicate_active_ring_is_rejected(self, mock_send_ring):
        ChatRing.objects.create(
            order=self.order,
            chat_id=f'order_{self.order.id}_shop_customer',
            sender_type='shop_owner',
            sender_id=self.shop.id,
            receiver_type='customer',
            receiver_id=self.customer.id,
            expires_at=timezone.now() + timedelta(seconds=30),
        )
        self.client.force_authenticate(user=self.shop)

        response = self.client.post(
            '/api/chat-rings/start',
            {
                'chat_id': f'order_{self.order.id}_shop_customer',
                'sender_id': self.shop.id,
                'receiver_id': self.customer.id,
                'order_id': self.order.id,
            },
            format='json',
        )

        self.assertEqual(response.status_code, 409)
        self.assertEqual(ChatRing.objects.count(), 1)
        mock_send_ring.assert_not_called()

    @patch('shop.chat_ring_service.get_channel_layer')
    @patch('shop.chat_ring_service._send_ring_event_to_user', return_value={'tokens_sent': 1})
    def test_customer_answered_updates_status_and_notifies_both_sides(self, mock_send_ring, mock_get_channel_layer):
        ring = ChatRing.objects.create(
            order=self.order,
            chat_id=f'order_{self.order.id}_shop_customer',
            sender_type='shop_owner',
            sender_id=self.shop.id,
            receiver_type='customer',
            receiver_id=self.customer.id,
            expires_at=timezone.now() + timedelta(seconds=30),
            metadata={'sender_name': 'Ring Store', 'sender_avatar': 'https://example.com/shop.png'},
        )
        mock_channel_layer = MagicMock()
        mock_channel_layer.group_send = AsyncMock()
        mock_get_channel_layer.return_value = mock_channel_layer
        self.client.force_authenticate(user=self.customer)

        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(f'/api/chat-rings/{ring.public_id}/answered', {}, format='json')

        self.assertEqual(response.status_code, 200)
        ring.refresh_from_db()
        self.assertEqual(ring.status, 'answered')
        self.assertIsNotNone(ring.answered_at)
        self.assertEqual(mock_send_ring.call_count, 2)
        recipients = {(call.args[0], call.args[1]) for call in mock_send_ring.call_args_list}
        self.assertEqual(recipients, {('shop_owner', self.shop.id), ('customer', self.customer.id)})
        for call in mock_send_ring.call_args_list:
            self.assertEqual(call.args[2]['type'], 'chat_ring_answered')
            self.assertEqual(call.args[2]['ring_id'], ring.public_id)
            self.assertEqual(call.args[2]['chat_id'], ring.chat_id)
        self.assertEqual(mock_channel_layer.group_send.await_count, 2)
        sent_groups = {call.args[0] for call in mock_channel_layer.group_send.await_args_list}
        self.assertEqual(sent_groups, {f'shop_orders_{self.shop.id}', f'customer_orders_{self.customer.id}'})

    @patch('shop.chat_ring_service.get_channel_layer')
    @patch('shop.chat_ring_service._send_ring_event_to_user', return_value={'tokens_sent': 1})
    def test_shop_owner_cancel_sends_cancelled_event_to_both_sides(self, mock_send_ring, mock_get_channel_layer):
        ring = ChatRing.objects.create(
            order=self.order,
            chat_id=f'order_{self.order.id}_shop_customer',
            sender_type='shop_owner',
            sender_id=self.shop.id,
            receiver_type='customer',
            receiver_id=self.customer.id,
            expires_at=timezone.now() + timedelta(seconds=30),
        )
        mock_channel_layer = MagicMock()
        mock_channel_layer.group_send = AsyncMock()
        mock_get_channel_layer.return_value = mock_channel_layer
        self.client.force_authenticate(user=self.shop)

        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(f'/api/chat-rings/{ring.public_id}/cancel', {}, format='json')

        self.assertEqual(response.status_code, 200)
        ring.refresh_from_db()
        self.assertEqual(ring.status, 'cancelled')
        self.assertEqual(mock_send_ring.call_count, 2)
        recipients = {(call.args[0], call.args[1]) for call in mock_send_ring.call_args_list}
        self.assertEqual(recipients, {('shop_owner', self.shop.id), ('customer', self.customer.id)})
        for call in mock_send_ring.call_args_list:
            self.assertEqual(call.args[2]['type'], 'chat_ring_cancelled')
            self.assertEqual(call.args[2]['ring_id'], ring.public_id)
        self.assertEqual(mock_channel_layer.group_send.await_count, 2)
        sent_groups = {call.args[0] for call in mock_channel_layer.group_send.await_args_list}
        self.assertEqual(sent_groups, {f'shop_orders_{self.shop.id}', f'customer_orders_{self.customer.id}'})

    @patch('shop.chat_ring_service.get_channel_layer')
    @patch('shop.chat_ring_service._send_ring_event_to_user', return_value={'tokens_sent': 1})
    def test_timeout_marks_ring_and_notifies_both_sides(self, mock_send_ring, mock_get_channel_layer):
        ring = ChatRing.objects.create(
            order=self.order,
            chat_id=f'order_{self.order.id}_shop_customer',
            sender_type='shop_owner',
            sender_id=self.shop.id,
            receiver_type='customer',
            receiver_id=self.customer.id,
            expires_at=timezone.now() + timedelta(seconds=30),
        )
        mock_channel_layer = MagicMock()
        mock_channel_layer.group_send = AsyncMock()
        mock_get_channel_layer.return_value = mock_channel_layer
        self.client.force_authenticate(user=self.customer)

        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(f'/api/chat-rings/{ring.public_id}/timeout', {}, format='json')

        self.assertEqual(response.status_code, 200)
        ring.refresh_from_db()
        self.assertEqual(ring.status, 'timeout')
        self.assertIsNotNone(ring.timed_out_at)
        self.assertEqual(mock_send_ring.call_count, 2)
        recipients = {(call.args[0], call.args[1]) for call in mock_send_ring.call_args_list}
        self.assertEqual(recipients, {('shop_owner', self.shop.id), ('customer', self.customer.id)})
        for call in mock_send_ring.call_args_list:
            self.assertEqual(call.args[2]['type'], 'chat_ring_timeout')
            self.assertEqual(call.args[2]['ring_id'], ring.public_id)
        self.assertEqual(mock_channel_layer.group_send.await_count, 2)
        sent_groups = {call.args[0] for call in mock_channel_layer.group_send.await_args_list}
        self.assertEqual(sent_groups, {f'shop_orders_{self.shop.id}', f'customer_orders_{self.customer.id}'})
