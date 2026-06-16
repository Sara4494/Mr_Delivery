from unittest.mock import patch

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIRequestFactory, force_authenticate

from shop.models import Customer, Driver, Order, ShopDriver
from shop.views import driver_order_accept_view
from user.models import ShopCategory, ShopOwner


class DriverOrderAcceptViewTests(TestCase):
    def setUp(self):
        super().setUp()
        self.factory = APIRequestFactory()
        self.category = ShopCategory.objects.create(name='Deliveries')
        self.shop = ShopOwner.objects.create(
            owner_name='Shop Owner',
            shop_name='Accept Store',
            shop_number='SHOP-ACCEPT-001',
            phone_number='01010015001',
            password='secret123',
            shop_category=self.category,
        )
        self.customer = Customer.objects.create(
            shop_owner=self.shop,
            name='Accept Customer',
            phone_number='01010015002',
            password='secret123',
        )
        self.driver = Driver.objects.create(
            name='Accept Driver',
            phone_number='01010015003',
            password='secret123',
            status='busy',
        )
        ShopDriver.objects.create(shop_owner=self.shop, driver=self.driver, status='active')

    def _create_order(self):
        return Order.objects.create(
            shop_owner=self.shop,
            customer=self.customer,
            driver=self.driver,
            order_number=f'AC{Order.objects.count() + 1:06d}',
            status='preparing',
            items='["meal"]',
            total_amount='120.00',
            delivery_fee='15.00',
            address='Tahrir Street',
            notes='',
            driver_assigned_at=timezone.now(),
            driver_accepted_at=None,
        )

    @patch('shop.views._notify_shop_about_driver_order_action')
    @patch('shop.views.emit_order_accepted')
    @patch('shop.views.emit_assigned_order_upsert')
    @patch('shop.views.emit_available_order_remove')
    @patch('shop.views.notify_order_update')
    def test_driver_accept_view_moves_order_to_on_way(
        self,
        notify_order_update_mock,
        emit_available_order_remove_mock,
        emit_assigned_order_upsert_mock,
        emit_order_accepted_mock,
        notify_shop_action_mock,
    ):
        order = self._create_order()

        request = self.factory.post(f'/api/driver/orders/{order.id}/accept/', {'order_id': order.id}, format='json')
        force_authenticate(request, user=self.driver)

        response = driver_order_accept_view(request, order.id)

        order.refresh_from_db()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(order.status, 'on_way')
        self.assertIsNotNone(order.driver_accepted_at)
        self.assertEqual(response.data['data']['status'], 'on_way')
        self.assertEqual(response.data['data']['driver_status'], 'in_delivery')
        notify_order_update_mock.assert_called_once()
        emit_available_order_remove_mock.assert_called()
        emit_assigned_order_upsert_mock.assert_called_once()
        emit_order_accepted_mock.assert_called_once()
        notify_shop_action_mock.assert_called_once()
