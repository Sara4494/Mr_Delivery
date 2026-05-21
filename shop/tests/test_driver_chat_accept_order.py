from unittest.mock import patch

from django.test import TestCase
from django.utils import timezone

from shop.driver_chat.service import assign_order_to_driver_conversation, driver_accept_order
from shop.models import (
    Customer,
    Driver,
    DriverChatConversation,
    DriverOrderRejection,
    Order,
    ShopDriver,
)
from user.models import ShopCategory, ShopOwner


class DriverChatAcceptOrderTests(TestCase):
    def setUp(self):
        super().setUp()
        self.category = ShopCategory.objects.create(name='Deliveries')
        self.shop = ShopOwner.objects.create(
            owner_name='Shop Owner',
            shop_name='Delivery Store',
            shop_number='SHOP-CHAT-ACCEPT-001',
            phone_number='01010013001',
            password='secret123',
            shop_category=self.category,
        )
        self.customer = Customer.objects.create(
            shop_owner=self.shop,
            name='Test Customer',
            phone_number='01010013002',
            password='secret123',
        )
        self.source_driver = Driver.objects.create(
            name='Current Driver',
            phone_number='01010013003',
            password='secret123',
            is_online=True,
            availability_enabled=True,
            status='available',
        )
        self.target_driver = Driver.objects.create(
            name='Replacement Driver',
            phone_number='01010013004',
            password='secret123',
            is_online=True,
            availability_enabled=True,
            status='available',
        )
        ShopDriver.objects.create(shop_owner=self.shop, driver=self.source_driver, status='active')
        ShopDriver.objects.create(shop_owner=self.shop, driver=self.target_driver, status='active')

    def _create_order(self):
        return Order.objects.create(
            shop_owner=self.shop,
            customer=self.customer,
            driver=self.source_driver,
            order_number=f'OC{Order.objects.count() + 1:06d}',
            status='confirmed',
            items='["meal"]',
            total_amount='120.00',
            delivery_fee='15.00',
            address='Tahrir Street',
            notes='',
            driver_assigned_at=timezone.now(),
            driver_accepted_at=None,
        )

    @patch('shop.views._notify_shop_about_driver_order_action')
    @patch('shop.websocket_utils.notify_driver_status_updated')
    @patch('shop.websocket_utils.notify_order_update')
    @patch('shop.realtime.driver.sync_driver_order_state')
    def test_driver_chat_accept_order_reassigns_and_marks_driver_as_accepted(
        self,
        sync_driver_order_state_mock,
        notify_order_update_mock,
        notify_driver_status_updated_mock,
        notify_shop_action_mock,
    ):
        order = self._create_order()
        DriverOrderRejection.objects.create(order=order, driver=self.target_driver, reason='busy before')

        conversation, link, _ = assign_order_to_driver_conversation(order, self.target_driver)

        driver_accept_order(conversation=conversation, conversation_order=link)

        order.refresh_from_db()
        link.refresh_from_db()
        self.target_driver.refresh_from_db()

        self.assertEqual(order.driver_id, self.target_driver.id)
        self.assertEqual(order.status, 'on_way')
        self.assertIsNotNone(order.driver_assigned_at)
        self.assertIsNotNone(order.driver_accepted_at)
        self.assertEqual(link.status, 'driver_on_way')
        self.assertFalse(
            DriverOrderRejection.objects.filter(order=order, driver=self.target_driver).exists()
        )
        self.assertEqual(self.target_driver.current_orders_count, 1)
        notify_shop_action_mock.assert_called_once()
        notify_order_update_mock.assert_called_once()
        notify_driver_status_updated_mock.assert_called_once_with(self.target_driver)
        sync_driver_order_state_mock.assert_called_once()
        self.assertEqual(
            sync_driver_order_state_mock.call_args.kwargs['previous_driver_id'],
            self.source_driver.id,
        )
        self.assertIsNone(sync_driver_order_state_mock.call_args.kwargs['previous_driver_accepted_at'])

    def test_assign_order_to_driver_conversation_deactivates_previous_driver_link(self):
        order = self._create_order()
        old_conversation = DriverChatConversation.objects.create(
            shop_owner=self.shop,
            driver=self.source_driver,
            status='awaiting_driver_acceptance',
        )
        old_link = old_conversation.orders.create(
            order=order,
            status='awaiting_driver_acceptance',
            is_active=True,
        )

        conversation, link, _ = assign_order_to_driver_conversation(order, self.target_driver)

        old_link.refresh_from_db()
        self.assertEqual(conversation.driver_id, self.target_driver.id)
        self.assertTrue(link.is_active)
        self.assertEqual(link.status, 'awaiting_driver_acceptance')
        self.assertFalse(old_link.is_active)
        self.assertEqual(old_link.status, 'transferred_to_another_driver')
