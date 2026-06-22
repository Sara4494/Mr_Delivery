from datetime import timedelta
from unittest.mock import AsyncMock, MagicMock, patch

from django.test import TestCase
from django.utils import timezone

from shop.models import ChatRing, Customer, Driver, Employee, Order
from shop.chat_ring_service import (
    ChatRingError,
    apply_chat_ring_status_update,
    _ensure_chat_ring_storage,
    start_chat_ring,
)
from user.models import ShopCategory, ShopOwner


class ChatRingsApiTests(TestCase):
    def setUp(self):
        super().setUp()
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
        self.shop.user_type = 'shop_owner'
        self.employee.user_type = 'employee'
        self.customer.user_type = 'customer'
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
        ring, payload = start_chat_ring(
            chat_id=f'order_{self.order.id}_shop_customer',
            sender_id=self.shop.id,
            receiver_id=self.customer.id,
            order_id=self.order.id,
            user=self.shop,
            request=None,
        )

        ring = ChatRing.objects.get()
        self.assertEqual(ring.status, 'ringing')
        self.assertEqual(ring.sender_type, 'shop_owner')
        self.assertEqual(ring.receiver_type, 'customer')
        self.assertEqual(payload['duration_seconds'], 30)
        self.assertEqual(payload['push']['tokens_sent'], 1)
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

    @patch('shop.chat_ring_service.MigrationRecorder')
    @patch('shop.chat_ring_service.connection')
    def test_chat_ring_storage_is_created_on_demand_when_missing(self, mock_connection, mock_recorder_cls):
        mock_introspection = MagicMock()
        mock_introspection.table_names.return_value = []
        mock_connection.introspection = mock_introspection

        mock_schema_editor = MagicMock()
        mock_connection.schema_editor.return_value.__enter__.return_value = mock_schema_editor

        mock_recorder = MagicMock()
        mock_recorder.applied_migrations.return_value = set()
        mock_recorder_cls.return_value = mock_recorder

        _ensure_chat_ring_storage()

        mock_schema_editor.create_model.assert_called_once_with(ChatRing)
        mock_recorder.record_applied.assert_called_once_with('shop', '0064_chatring')

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
        with self.assertRaises(ChatRingError) as ctx:
            start_chat_ring(
                chat_id=f'order_{self.order.id}_shop_customer',
                sender_id=self.shop.id,
                receiver_id=self.customer.id,
                order_id=self.order.id,
                user=self.shop,
                request=None,
            )

        self.assertEqual(ctx.exception.status_code, 409)
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

        with self.captureOnCommitCallbacks(execute=True):
            _, result = apply_chat_ring_status_update(
                ring_id=ring.public_id,
                actor=self.customer,
                status_value='answered',
                lang='ar',
            )

        ring.refresh_from_db()
        self.assertEqual(ring.status, 'answered')
        self.assertIsNotNone(ring.answered_at)
        self.assertTrue(result['status_changed'])
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

        with self.captureOnCommitCallbacks(execute=True):
            _, result = apply_chat_ring_status_update(
                ring_id=ring.public_id,
                actor=self.shop,
                status_value='cancelled',
                lang='ar',
            )

        ring.refresh_from_db()
        self.assertEqual(ring.status, 'cancelled')
        self.assertTrue(result['status_changed'])
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

        with self.captureOnCommitCallbacks(execute=True):
            _, result = apply_chat_ring_status_update(
                ring_id=ring.public_id,
                actor=self.customer,
                status_value='timeout',
                lang='ar',
            )

        ring.refresh_from_db()
        self.assertEqual(ring.status, 'timeout')
        self.assertIsNotNone(ring.timed_out_at)
        self.assertTrue(result['status_changed'])
        self.assertEqual(mock_send_ring.call_count, 2)
        recipients = {(call.args[0], call.args[1]) for call in mock_send_ring.call_args_list}
        self.assertEqual(recipients, {('shop_owner', self.shop.id), ('customer', self.customer.id)})
        for call in mock_send_ring.call_args_list:
            self.assertEqual(call.args[2]['type'], 'chat_ring_timeout')
            self.assertEqual(call.args[2]['ring_id'], ring.public_id)
        self.assertEqual(mock_channel_layer.group_send.await_count, 2)
        sent_groups = {call.args[0] for call in mock_channel_layer.group_send.await_args_list}
        self.assertEqual(sent_groups, {f'shop_orders_{self.shop.id}', f'customer_orders_{self.customer.id}'})

    @patch('shop.chat_ring_service.get_channel_layer')
    @patch('shop.chat_ring_service._send_ring_event_to_user', return_value={'tokens_sent': 1})
    def test_repeating_the_same_terminal_status_is_idempotent(self, mock_send_ring, mock_get_channel_layer):
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

        with self.captureOnCommitCallbacks(execute=True):
            _, result = apply_chat_ring_status_update(
                ring_id=ring.public_id,
                actor=self.customer,
                status_value='answered',
                lang='ar',
            )

        ring.refresh_from_db()
        self.assertEqual(ring.status, 'answered')
        self.assertTrue(result['status_changed'])
        self.assertEqual(mock_send_ring.call_count, 2)
        self.assertEqual(mock_channel_layer.group_send.await_count, 2)

        with self.captureOnCommitCallbacks(execute=True):
            _, repeat_result = apply_chat_ring_status_update(
                ring_id=ring.public_id,
                actor=self.customer,
                status_value='answered',
                lang='ar',
            )

        ring.refresh_from_db()
        self.assertEqual(ring.status, 'answered')
        self.assertFalse(repeat_result['status_changed'])
        self.assertEqual(mock_send_ring.call_count, 2)
        self.assertEqual(mock_channel_layer.group_send.await_count, 2)

    @patch('shop.chat_ring_service.get_channel_layer')
    @patch('shop.chat_ring_service._send_ring_event_to_user', return_value={'tokens_sent': 1})
    def test_ring_status_broadcast_reaches_assigned_driver_group(self, mock_send_ring, mock_get_channel_layer):
        driver = Driver.objects.create(
            name='Assigned Driver',
            phone_number='01010000994',
            password='secret123',
            is_verified=True,
            is_online=True,
            availability_enabled=True,
            status='available',
        )
        driver.user_type = 'driver'
        self.order.driver = driver
        self.order.save(update_fields=['driver'])

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

        with self.captureOnCommitCallbacks(execute=True):
            _, result = apply_chat_ring_status_update(
                ring_id=ring.public_id,
                actor=self.customer,
                status_value='answered',
                lang='ar',
            )

        ring.refresh_from_db()
        self.assertEqual(ring.status, 'answered')
        self.assertTrue(result['status_changed'])
        self.assertEqual(mock_send_ring.call_count, 2)
        self.assertEqual(mock_channel_layer.group_send.await_count, 3)
        sent_groups = {call.args[0] for call in mock_channel_layer.group_send.await_args_list}
        self.assertEqual(sent_groups, {f'shop_orders_{self.shop.id}', f'customer_orders_{self.customer.id}', f'driver_{driver.id}'})
