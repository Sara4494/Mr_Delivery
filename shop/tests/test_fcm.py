from unittest.mock import patch

from django.test import TestCase
from rest_framework.test import APIRequestFactory, force_authenticate

from shop.fcm_service import send_order_chat_push_fallback, send_ring_push_fallback
from shop.fcm_views import (
    fcm_refresh_device_view,
    fcm_register_device_view,
    fcm_unregister_device_view,
)
from shop.models import Customer, Driver, Employee, FCMDeviceToken, Order
from user.models import ShopCategory, ShopOwner


class FCMDeviceApiTests(TestCase):
    def setUp(self):
        super().setUp()
        self.factory = APIRequestFactory()
        self.category = ShopCategory.objects.create(name='Groceries')
        self.shop = ShopOwner.objects.create(
            owner_name='مالك المحل',
            shop_name='شاورما',
            shop_number='SHOP-100',
            phone_number='01010000001',
            password='secret123',
            shop_category=self.category,
        )
        self.customer = Customer.objects.create(
            shop_owner=self.shop,
            name='أحمد',
            phone_number='01020000001',
            password='secret123',
        )
        self.driver = Driver.objects.create(
            name='محمود',
            phone_number='01030000001',
            password='secret123',
        )

    def _request(self, view, method, path, user, data):
        request = getattr(self.factory, method.lower())(path, data, format='json')
        force_authenticate(request, user=user)
        return view(request)

    def test_register_endpoint_creates_device_token_for_authenticated_user(self):
        response = self._request(
            fcm_register_device_view,
            'POST',
            '/api/devices/fcm/register',
            self.customer,
            {
                'device_id': 'device-1',
                'platform': 'android',
                'fcm_token': 'token-123',
                'app_version': '1.0.0',
            },
        )

        self.assertEqual(response.status_code, 200)
        token = FCMDeviceToken.objects.get(device_id='device-1')
        self.assertEqual(token.user_type, 'customer')
        self.assertEqual(token.user_id, self.customer.id)
        self.assertEqual(token.platform, 'android')
        self.assertEqual(token.fcm_token, 'token-123')
        self.assertTrue(token.is_active)

    def test_refresh_endpoint_updates_existing_device_token(self):
        token = FCMDeviceToken.objects.create(
            user_type='customer',
            user_id=self.customer.id,
            device_id='device-1',
            platform='android',
            fcm_token='old-token',
            is_active=True,
        )

        response = self._request(
            fcm_refresh_device_view,
            'POST',
            '/api/devices/fcm/refresh',
            self.customer,
            {
                'device_id': 'device-1',
                'platform': 'ios',
                'fcm_token': 'new-token',
                'app_version': '2.0.0',
            },
        )

        self.assertEqual(response.status_code, 200)
        token.refresh_from_db()
        self.assertEqual(token.platform, 'ios')
        self.assertEqual(token.fcm_token, 'new-token')
        self.assertEqual(token.app_version, '2.0.0')
        self.assertTrue(token.is_active)

    def test_unregister_endpoint_only_deactivates_current_users_tokens(self):
        own_token = FCMDeviceToken.objects.create(
            user_type='customer',
            user_id=self.customer.id,
            device_id='device-1',
            platform='android',
            fcm_token='customer-token',
            is_active=True,
        )
        other_token = FCMDeviceToken.objects.create(
            user_type='driver',
            user_id=self.driver.id,
            device_id='device-1',
            platform='android',
            fcm_token='driver-token',
            is_active=True,
        )

        response = self._request(
            fcm_unregister_device_view,
            'DELETE',
            '/api/devices/fcm/unregister',
            self.customer,
            {
                'device_id': 'device-1',
            },
        )

        self.assertEqual(response.status_code, 200)
        own_token.refresh_from_db()
        other_token.refresh_from_db()
        self.assertFalse(own_token.is_active)
        self.assertTrue(other_token.is_active)


class FCMFallbackDispatchTests(TestCase):
    def setUp(self):
        super().setUp()
        self.category = ShopCategory.objects.create(name='Groceries')
        self.shop = ShopOwner.objects.create(
            owner_name='مالك المحل',
            shop_name='شاورما',
            shop_number='SHOP-200',
            phone_number='01010000002',
            password='secret123',
            shop_category=self.category,
        )
        self.customer = Customer.objects.create(
            shop_owner=self.shop,
            name='أحمد',
            phone_number='01020000002',
            password='secret123',
        )
        self.driver = Driver.objects.create(
            name='محمود',
            phone_number='01030000002',
            password='secret123',
        )
        self.employee = Employee.objects.create(
            shop_owner=self.shop,
            name='موظف',
            phone_number='01040000002',
            password='secret123',
            role='cashier',
            is_active=True,
        )
        self.order = Order.objects.create(
            shop_owner=self.shop,
            customer=self.customer,
            driver=self.driver,
            order_number='ODZQJ2H6',
            status='confirmed',
            items='["وجبة"]',
            total_amount='150.00',
            delivery_fee='20.00',
            address='شارع التحرير',
            notes='',
        )

    @patch('shop.fcm_service.send_push_to_token_record', return_value={'success': True, 'invalid_token': False})
    def test_chat_fallback_targets_customer_for_shop_message(self, mock_send):
        FCMDeviceToken.objects.create(
            user_type='customer',
            user_id=self.customer.id,
            device_id='customer-device',
            platform='android',
            fcm_token='customer-token',
            is_active=True,
        )
        FCMDeviceToken.objects.create(
            user_type='shop_owner',
            user_id=self.shop.id,
            device_id='shop-device',
            platform='android',
            fcm_token='shop-token',
            is_active=True,
        )

        summary = send_order_chat_push_fallback(
            self.order.id,
            'shop_customer',
            {
                'sender_type': 'shop_owner',
                'message_type': 'text',
                'content': 'رسالة جديدة',
            },
        )

        self.assertEqual(summary['tokens_total'], 1)
        self.assertEqual(summary['tokens_sent'], 1)
        self.assertEqual(mock_send.call_count, 1)
        target_record = mock_send.call_args[0][0]
        self.assertEqual(target_record.user_type, 'customer')
        self.assertEqual(target_record.user_id, self.customer.id)

    @patch('shop.fcm_service.send_push_to_token_record', return_value={'success': True, 'invalid_token': False})
    def test_ring_fallback_targets_shop_owner_and_employees_for_shop_target(self, mock_send):
        FCMDeviceToken.objects.create(
            user_type='shop_owner',
            user_id=self.shop.id,
            device_id='shop-device',
            platform='android',
            fcm_token='shop-token',
            is_active=True,
        )
        FCMDeviceToken.objects.create(
            user_type='employee',
            user_id=self.employee.id,
            device_id='employee-device',
            platform='android',
            fcm_token='employee-token',
            is_active=True,
        )

        summary = send_ring_push_fallback(
            self.order.id,
            {
                'ring_id': 'ring-1',
                'sender_type': 'customer',
                'sender_name': 'أحمد',
                'targets': ['shop'],
                'shop_name': self.shop.shop_name,
                'chat_type': 'shop_customer',
            },
        )

        self.assertEqual(summary['tokens_total'], 2)
        self.assertEqual(summary['tokens_sent'], 2)
        self.assertEqual(mock_send.call_count, 2)
        target_types = sorted(call.args[0].user_type for call in mock_send.call_args_list)
        self.assertEqual(target_types, ['employee', 'shop_owner'])
