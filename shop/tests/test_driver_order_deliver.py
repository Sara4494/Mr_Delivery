from unittest.mock import patch

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIRequestFactory, force_authenticate

from shop.models import Customer, Driver, Order, ShopDriver
from shop.views import driver_order_deliver_view
from user.models import ShopCategory, ShopOwner


class DriverOrderDeliverViewTests(TestCase):
    def setUp(self):
        super().setUp()
        self.factory = APIRequestFactory()
        self.category = ShopCategory.objects.create(name='Deliveries')
        self.shop = ShopOwner.objects.create(
            owner_name='صاحب المتجر',
            shop_name='متجر التوصيل',
            shop_number='SHOP-DELIVER-001',
            phone_number='01010010001',
            password='secret123',
            shop_category=self.category,
        )
        self.customer = Customer.objects.create(
            shop_owner=self.shop,
            name='عميل التجربة',
            phone_number='01010010002',
            password='secret123',
        )
        self.driver = Driver.objects.create(
            name='مندوب التجربة',
            phone_number='01010010003',
            password='secret123',
            status='busy',
        )
        ShopDriver.objects.create(shop_owner=self.shop, driver=self.driver, status='active')

    def _create_order(self, *, status='on_way', accepted=True, assigned_driver=None):
        assigned_driver = assigned_driver if assigned_driver is not None else self.driver
        accepted_at = timezone.now() if accepted else None
        return Order.objects.create(
            shop_owner=self.shop,
            customer=self.customer,
            driver=assigned_driver,
            order_number=f'OD{Order.objects.count() + 1:06d}',
            status=status,
            items='["وجبة"]',
            total_amount='120.00',
            delivery_fee='15.00',
            address='شارع التحرير',
            notes='',
            driver_assigned_at=timezone.now(),
            driver_accepted_at=accepted_at,
        )

    @patch('shop.views.notify_driver_status_updated')
    @patch('shop.views.notify_order_update')
    def test_driver_can_mark_on_way_order_as_delivered(self, notify_order_update_mock, notify_driver_status_updated_mock):
        order = self._create_order(status='on_way', accepted=True)

        request = self.factory.post(f'/api/driver/orders/{order.id}/deliver/', {'order_id': order.id}, format='json')
        force_authenticate(request, user=self.driver)

        response = driver_order_deliver_view(request, order.id)

        order.refresh_from_db()
        self.driver.refresh_from_db()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['data']['order_id'], order.id)
        self.assertEqual(response.data['data']['status'], 'delivered')
        self.assertIsNotNone(response.data['data']['delivered_at'])
        self.assertEqual(order.status, 'delivered')
        self.assertIsNotNone(order.delivered_at)
        self.assertEqual(self.driver.current_orders_count, 0)
        notify_order_update_mock.assert_called_once()
        notify_driver_status_updated_mock.assert_called_once()

    def test_driver_cannot_deliver_order_in_wrong_status(self):
        order = self._create_order(status='confirmed', accepted=True)

        request = self.factory.post(f'/api/driver/orders/{order.id}/deliver/', {'order_id': order.id}, format='json')
        force_authenticate(request, user=self.driver)

        response = driver_order_deliver_view(request, order.id)

        order.refresh_from_db()
        self.assertEqual(response.status_code, 400)
        self.assertEqual(order.status, 'confirmed')
        self.assertIsNone(order.delivered_at)

    def test_driver_cannot_deliver_unaccepted_order(self):
        order = self._create_order(status='on_way', accepted=False)

        request = self.factory.post(f'/api/driver/orders/{order.id}/deliver/', {'order_id': order.id}, format='json')
        force_authenticate(request, user=self.driver)

        response = driver_order_deliver_view(request, order.id)

        order.refresh_from_db()
        self.assertEqual(response.status_code, 400)
        self.assertEqual(order.status, 'on_way')
        self.assertIsNone(order.delivered_at)
