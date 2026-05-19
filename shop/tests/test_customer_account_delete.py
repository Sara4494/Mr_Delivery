from django.test import TestCase
from rest_framework.test import APIClient

from shop.models import Customer, FCMDeviceToken, Order
from user.models import ShopCategory, ShopOwner


class CustomerAccountDeleteTests(TestCase):
    def setUp(self):
        super().setUp()
        self.client = APIClient()
        self.category = ShopCategory.objects.create(name='Groceries')
        self.shop = ShopOwner.objects.create(
            owner_name='Shop Owner',
            shop_name='Delete Store',
            shop_number='SHOP-DELETE-001',
            phone_number='01010030001',
            password='secret123',
            shop_category=self.category,
        )
        self.customer = Customer.objects.create(
            shop_owner=self.shop,
            name='Delete Me',
            phone_number='01010030002',
            email='delete.me@example.com',
            password='secret123',
            is_verified=True,
        )
        self.client.force_authenticate(user=self.customer)

    def test_delete_customer_profile_reassigns_history_and_deletes_login_account(self):
        order = Order.objects.create(
            shop_owner=self.shop,
            customer=self.customer,
            order_number='OD-DEL-1',
            status='delivered',
            items='["meal"]',
            total_amount='50.00',
            delivery_fee='10.00',
            address='Tahrir Street',
            notes='',
        )
        FCMDeviceToken.objects.create(
            user_type='customer',
            user_id=self.customer.id,
            device_id='delete-device',
            platform='android',
            fcm_token='delete-token',
            is_active=True,
        )

        response = self.client.delete(
            '/api/customer/profile/',
            {'current_password': 'secret123'},
            format='json',
        )

        self.assertEqual(response.status_code, 200)
        self.assertFalse(Customer.objects.filter(id=self.customer.id).exists())
        order.refresh_from_db()
        self.assertNotEqual(order.customer_id, self.customer.id)
        self.assertTrue(order.customer.name.startswith('Deleted Customer #'))
        self.assertFalse(FCMDeviceToken.objects.filter(user_type='customer', user_id=self.customer.id).exists())

    def test_delete_customer_profile_is_blocked_when_active_orders_exist(self):
        Order.objects.create(
            shop_owner=self.shop,
            customer=self.customer,
            order_number='OD-DEL-2',
            status='confirmed',
            items='["meal"]',
            total_amount='70.00',
            delivery_fee='10.00',
            address='Tahrir Street',
            notes='',
        )

        response = self.client.delete(
            '/api/customer/profile/',
            {'current_password': 'secret123'},
            format='json',
        )

        self.assertEqual(response.status_code, 409)
        self.assertTrue(Customer.objects.filter(id=self.customer.id).exists())
