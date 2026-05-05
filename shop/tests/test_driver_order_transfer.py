from unittest.mock import patch

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIRequestFactory, force_authenticate

from shop.models import Customer, Driver, Order, ShopDriver
from shop.views import driver_order_transfer_view, order_detail_view
from user.models import ShopCategory, ShopOwner


class DriverOrderTransferViewTests(TestCase):
    def setUp(self):
        super().setUp()
        self.factory = APIRequestFactory()
        self.category = ShopCategory.objects.create(name='Deliveries')
        self.shop = ShopOwner.objects.create(
            owner_name='Shop Owner',
            shop_name='Delivery Store',
            shop_number='SHOP-TRANSFER-001',
            phone_number='01010010011',
            password='secret123',
            shop_category=self.category,
        )
        self.customer = Customer.objects.create(
            shop_owner=self.shop,
            name='Test Customer',
            phone_number='01010010012',
            password='secret123',
        )
        self.driver = Driver.objects.create(
            name='Current Driver',
            phone_number='01010010013',
            password='secret123',
            status='busy',
        )
        self.other_driver = Driver.objects.create(
            name='Replacement Driver',
            phone_number='01010010014',
            password='secret123',
            status='available',
        )
        ShopDriver.objects.create(shop_owner=self.shop, driver=self.driver, status='active')
        ShopDriver.objects.create(shop_owner=self.shop, driver=self.other_driver, status='active')

    def _create_order(self, *, status='on_way', accepted=True, assigned_driver=None):
        assigned_driver = assigned_driver if assigned_driver is not None else self.driver
        accepted_at = timezone.now() if accepted else None
        return Order.objects.create(
            shop_owner=self.shop,
            customer=self.customer,
            driver=assigned_driver,
            order_number=f'OT{Order.objects.count() + 1:06d}',
            status=status,
            items='["meal"]',
            total_amount='120.00',
            delivery_fee='15.00',
            address='Tahrir Street',
            notes='',
            driver_assigned_at=timezone.now(),
            driver_accepted_at=accepted_at,
        )

    @patch('shop.views.emit_order_transferred')
    @patch('shop.views.sync_driver_order_state')
    @patch('shop.views.notify_driver_status_updated')
    @patch('shop.views.notify_order_update')
    @patch('shop.views.emit_order_transfer_requested')
    @patch('shop.views.request_transfer_for_order')
    def test_driver_transfer_request_keeps_order_assigned_and_emits_request_event_only(
        self,
        request_transfer_for_order_mock,
        emit_order_transfer_requested_mock,
        notify_order_update_mock,
        notify_driver_status_updated_mock,
        sync_driver_order_state_mock,
        emit_order_transferred_mock,
    ):
        order = self._create_order(status='on_way', accepted=True)
        original_assigned_at = order.driver_assigned_at
        original_accepted_at = order.driver_accepted_at

        request = self.factory.post(
            f'/api/driver/orders/{order.id}/transfer/',
            {'reason_key': 'vehicle_issue', 'note': 'flat tire'},
            format='json',
        )
        force_authenticate(request, user=self.driver)

        response = driver_order_transfer_view(request, order.id)

        order.refresh_from_db()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(order.driver_id, self.driver.id)
        self.assertEqual(order.status, 'on_way')
        self.assertEqual(order.driver_assigned_at, original_assigned_at)
        self.assertEqual(order.driver_accepted_at, original_accepted_at)
        self.assertEqual(response.data['data']['status'], 'pending_store_approval')
        request_transfer_for_order_mock.assert_called_once()
        emit_order_transfer_requested_mock.assert_called_once_with(
            self.driver.id,
            order.id,
            requested_by_driver_id=self.driver.id,
            reason_key='vehicle_issue',
            note='flat tire',
        )
        emit_order_transferred_mock.assert_not_called()
        sync_driver_order_state_mock.assert_not_called()
        notify_order_update_mock.assert_not_called()
        notify_driver_status_updated_mock.assert_not_called()

    @patch('shop.views.sync_driver_order_state')
    @patch('shop.views.notify_driver_status_updated')
    @patch('shop.views.notify_driver_assigned')
    @patch('shop.views.notify_order_update')
    @patch('shop.views.sync_order_assignment_change')
    @patch('shop.views.broadcast_chat_message_to_order')
    @patch('shop.views.emit_order_transferred')
    def test_store_reassignment_emits_transferred_event_only_on_actual_reassignment(
        self,
        emit_order_transferred_mock,
        broadcast_chat_message_to_order_mock,
        sync_order_assignment_change_mock,
        notify_order_update_mock,
        notify_driver_assigned_mock,
        notify_driver_status_updated_mock,
        sync_driver_order_state_mock,
    ):
        order = self._create_order(status='on_way', accepted=True)

        request = self.factory.put(
            f'/api/shop/orders/{order.id}/',
            {'driver_id': self.other_driver.id},
            format='json',
        )
        force_authenticate(request, user=self.shop)

        response = order_detail_view(request, order.id)

        order.refresh_from_db()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(order.driver_id, self.other_driver.id)
        self.assertIsNone(order.driver_accepted_at)
        emit_order_transferred_mock.assert_called_once_with(
            self.driver.id,
            order.id,
            old_driver_id=self.driver.id,
            new_driver_id=self.other_driver.id,
            transferred_by='store',
            status='transferred',
        )
        notify_driver_assigned_mock.assert_called_once()
        notify_order_update_mock.assert_called_once()
        notify_driver_status_updated_mock.assert_called()
        sync_driver_order_state_mock.assert_called_once()
        sync_order_assignment_change_mock.assert_called_once()
        broadcast_chat_message_to_order_mock.assert_called()
