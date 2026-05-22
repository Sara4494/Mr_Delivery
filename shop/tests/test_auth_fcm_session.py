from unittest.mock import patch

from django.test import TestCase
from rest_framework.test import APIRequestFactory, force_authenticate

from shop.models import Customer, Driver, FCMDeviceToken
from shop.views import customer_login_view, customer_logout_view, driver_login_view, driver_logout_view
from user.models import ShopCategory, ShopOwner


class AuthFCMSessionTests(TestCase):
    def setUp(self):
        super().setUp()
        self.factory = APIRequestFactory()
        self.category = ShopCategory.objects.create(name='Groceries')
        self.shop = ShopOwner.objects.create(
            owner_name='Shop Owner',
            shop_name='ZAYGO Store',
            shop_number='SHOP-FCM-1',
            phone_number='01010000111',
            password='secret123',
            shop_category=self.category,
        )
        self.customer = Customer.objects.create(
            shop_owner=self.shop,
            name='Customer One',
            phone_number='01020000111',
            is_verified=True,
        )
        self.customer.set_password('secret123')
        self.customer.save()

        self.driver = Driver.objects.create(
            name='Driver One',
            phone_number='01030000111',
            is_verified=True,
        )
        self.driver.set_password('secret123')
        self.driver.save()

    @patch('shop.fcm.service.send_push_to_token_record', return_value={'success': True, 'invalid_token': False})
    def test_customer_login_replaces_old_fcm_tokens_and_registers_new_device(self, mock_send_push):
        old_token = FCMDeviceToken.objects.create(
            user_type='customer',
            user_id=self.customer.id,
            device_id='customer-old-device',
            platform='android',
            fcm_token='customer-old-token',
            is_active=True,
        )

        request = self.factory.post(
            '/api/customer/login/',
            {
                'phone_number': self.customer.phone_number,
                'password': 'secret123',
                'device_id': 'customer-new-device',
                'platform': 'android',
                'fcm_token': 'customer-new-token',
            },
            format='json',
        )

        response = customer_login_view(request)

        self.assertEqual(response.status_code, 200)
        self.assertFalse(FCMDeviceToken.objects.filter(pk=old_token.pk).exists())
        new_token = FCMDeviceToken.objects.get(
            user_type='customer',
            user_id=self.customer.id,
            device_id='customer-new-device',
        )
        self.assertEqual(new_token.fcm_token, 'customer-new-token')
        self.assertEqual(response.data['data']['fcm_device']['device_id'], 'customer-new-device')
        self.assertEqual(response.data['data']['force_logged_out_devices'], 1)
        self.assertEqual(mock_send_push.call_count, 1)
        self.assertEqual(mock_send_push.call_args.kwargs['data'], {'type': 'force_logout'})
        self.assertTrue(mock_send_push.call_args.kwargs['data_only'])

    def test_customer_logout_deletes_only_current_fcm_token(self):
        current_token = FCMDeviceToken.objects.create(
            user_type='customer',
            user_id=self.customer.id,
            device_id='customer-current-device',
            platform='android',
            fcm_token='customer-current-token',
            is_active=True,
        )
        other_token = FCMDeviceToken.objects.create(
            user_type='customer',
            user_id=self.customer.id,
            device_id='customer-other-device',
            platform='android',
            fcm_token='customer-other-token',
            is_active=True,
        )

        request = self.factory.post(
            '/api/customer/logout/',
            {
                'fcm_token': 'customer-current-token',
            },
            format='json',
        )
        force_authenticate(request, user=self.customer)

        response = customer_logout_view(request)

        self.assertEqual(response.status_code, 200)
        self.assertFalse(FCMDeviceToken.objects.filter(pk=current_token.pk).exists())
        self.assertTrue(FCMDeviceToken.objects.filter(pk=other_token.pk).exists())
        self.assertEqual(response.data['data']['deactivated_tokens'], 1)

    @patch('shop.fcm.service.send_push_to_token_record', return_value={'success': True, 'invalid_token': False})
    def test_driver_login_replaces_old_fcm_tokens_and_registers_new_device(self, mock_send_push):
        old_token = FCMDeviceToken.objects.create(
            user_type='driver',
            user_id=self.driver.id,
            device_id='driver-old-device',
            platform='android',
            fcm_token='driver-old-token',
            is_active=True,
        )

        request = self.factory.post(
            '/api/driver/login/',
            {
                'phone_number': self.driver.phone_number,
                'password': 'secret123',
                'device_id': 'driver-new-device',
                'platform': 'android',
                'fcm_token': 'driver-new-token',
            },
            format='json',
        )

        response = driver_login_view(request)

        self.assertEqual(response.status_code, 200)
        self.assertFalse(FCMDeviceToken.objects.filter(pk=old_token.pk).exists())
        new_token = FCMDeviceToken.objects.get(
            user_type='driver',
            user_id=self.driver.id,
            device_id='driver-new-device',
        )
        self.assertEqual(new_token.fcm_token, 'driver-new-token')
        self.assertEqual(response.data['data']['fcm_device']['device_id'], 'driver-new-device')
        self.assertEqual(response.data['data']['force_logged_out_devices'], 1)
        self.assertEqual(mock_send_push.call_count, 1)

    def test_driver_logout_deletes_only_current_fcm_token(self):
        current_token = FCMDeviceToken.objects.create(
            user_type='driver',
            user_id=self.driver.id,
            device_id='driver-current-device',
            platform='android',
            fcm_token='driver-current-token',
            is_active=True,
        )
        other_token = FCMDeviceToken.objects.create(
            user_type='driver',
            user_id=self.driver.id,
            device_id='driver-other-device',
            platform='android',
            fcm_token='driver-other-token',
            is_active=True,
        )

        request = self.factory.post(
            '/api/driver/logout/',
            {
                'fcm_token': 'driver-current-token',
            },
            format='json',
        )
        force_authenticate(request, user=self.driver)

        response = driver_logout_view(request)

        self.assertEqual(response.status_code, 200)
        self.assertFalse(FCMDeviceToken.objects.filter(pk=current_token.pk).exists())
        self.assertTrue(FCMDeviceToken.objects.filter(pk=other_token.pk).exists())
        self.assertEqual(response.data['data']['deactivated_tokens'], 1)
