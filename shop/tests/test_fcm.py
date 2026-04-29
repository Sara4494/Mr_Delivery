from unittest.mock import patch

from asgiref.sync import async_to_sync
from django.test import TestCase
from rest_framework.test import APIRequestFactory, force_authenticate
from rest_framework_simplejwt.tokens import RefreshToken

from shop.fcm_service import (
    _stringify_payload,
    build_driver_inbox_notification_payload,
    build_incoming_ring_payload,
    send_order_chat_push_fallback,
    send_driver_new_order_notification,
    send_driver_store_invite_notification,
    send_driver_system_notification,
    send_driver_system_notifications,
    send_push_to_token_record,
    send_push_to_user,
    send_ring_push_fallback,
)
from shop.consumers import _build_ring_dispatch_context
from shop.views import _attach_notification_to_user
from shop.fcm_views import (
    fcm_refresh_device_view,
    fcm_register_device_view,
    fcm_unregister_device_view,
)
from shop.models import (
    AccountModerationStatus,
    Customer,
    Driver,
    DriverChatConversation,
    Employee,
    FCMDeviceToken,
    Notification,
    Order,
    ShopDriver,
)
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

    def _access_token_for_user(self, user, user_type):
        refresh = RefreshToken()
        if user_type == 'customer':
            refresh['customer_id'] = user.id
        elif user_type == 'driver':
            refresh['driver_id'] = user.id
        elif user_type == 'employee':
            refresh['employee_id'] = user.id
            refresh['shop_owner_id'] = user.shop_owner_id
        elif user_type == 'shop_owner':
            refresh['shop_owner_id'] = user.id
        else:
            raise ValueError(f'Unsupported user_type: {user_type}')
        refresh['user_type'] = user_type
        return str(refresh.access_token)

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

    def test_register_endpoint_accepts_access_token_in_body(self):
        request = self.factory.post(
            '/api/devices/fcm/register',
            {
                'device_id': 'device-body-token',
                'platform': 'android',
                'fcm_token': 'token-body-123',
                'app_version': '1.0.0',
                'access_token': self._access_token_for_user(self.customer, 'customer'),
            },
            format='json',
        )

        response = fcm_register_device_view(request)

        self.assertEqual(response.status_code, 200)
        token = FCMDeviceToken.objects.get(device_id='device-body-token')
        self.assertEqual(token.user_type, 'customer')
        self.assertEqual(token.user_id, self.customer.id)
        self.assertEqual(token.fcm_token, 'token-body-123')

    def test_register_endpoint_rejects_suspended_account(self):
        AccountModerationStatus.objects.create(
            customer=self.customer,
            is_suspended=True,
            suspension_reason='Suspended by admin',
        )

        response = self._request(
            fcm_register_device_view,
            'POST',
            '/api/devices/fcm/register',
            self.customer,
            {
                'device_id': 'device-suspended',
                'platform': 'android',
                'fcm_token': 'token-suspended',
            },
        )

        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.data['code'], 'account_suspended')
        self.assertEqual(response.data['reason'], 'Suspended by admin')
        self.assertFalse(FCMDeviceToken.objects.filter(device_id='device-suspended').exists())

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

    def test_register_endpoint_creates_additional_record_for_new_device(self):
        existing_token = FCMDeviceToken.objects.create(
            user_type='customer',
            user_id=self.customer.id,
            device_id='device-old',
            platform='android',
            fcm_token='old-token',
            is_active=True,
        )

        response = self._request(
            fcm_register_device_view,
            'POST',
            '/api/devices/fcm/register',
            self.customer,
            {
                'device_id': 'device-new',
                'platform': 'ios',
                'fcm_token': 'new-token',
                'app_version': '4.0.0',
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            FCMDeviceToken.objects.filter(user_type='customer', user_id=self.customer.id).count(),
            2,
        )
        existing_token.refresh_from_db()
        created_token = FCMDeviceToken.objects.get(device_id='device-new')
        self.assertEqual(existing_token.device_id, 'device-old')
        self.assertTrue(existing_token.is_active)
        self.assertEqual(created_token.platform, 'ios')
        self.assertEqual(created_token.fcm_token, 'new-token')
        self.assertEqual(created_token.app_version, '4.0.0')
        self.assertTrue(created_token.is_active)

    def test_register_endpoint_deactivates_same_token_for_other_user(self):
        other_user_token = FCMDeviceToken.objects.create(
            user_type='driver',
            user_id=self.driver.id,
            device_id='driver-device',
            platform='android',
            fcm_token='shared-token',
            is_active=True,
        )
        FCMDeviceToken.objects.create(
            user_type='customer',
            user_id=self.customer.id,
            device_id='device-old',
            platform='android',
            fcm_token='old-token',
            is_active=True,
        )

        response = self._request(
            fcm_register_device_view,
            'POST',
            '/api/devices/fcm/register',
            self.customer,
            {
                'device_id': 'device-current',
                'platform': 'android',
                'fcm_token': 'shared-token',
            },
        )

        self.assertEqual(response.status_code, 200)
        other_user_token.refresh_from_db()
        self.assertFalse(other_user_token.is_active)
        current_user_token = FCMDeviceToken.objects.get(
            user_type='customer',
            user_id=self.customer.id,
            device_id='device-current',
        )
        self.assertTrue(current_user_token.is_active)
        self.assertEqual(current_user_token.fcm_token, 'shared-token')

    def test_refresh_endpoint_accepts_bearer_token_in_body(self):
        token = FCMDeviceToken.objects.create(
            user_type='customer',
            user_id=self.customer.id,
            device_id='device-body-refresh',
            platform='android',
            fcm_token='old-body-token',
            is_active=True,
        )

        request = self.factory.post(
            '/api/devices/fcm/refresh',
            {
                'device_id': 'device-body-refresh',
                'platform': 'ios',
                'fcm_token': 'new-body-token',
                'app_version': '3.0.0',
                'access_token': f'Bearer {self._access_token_for_user(self.customer, "customer")}',
            },
            format='json',
        )

        response = fcm_refresh_device_view(request)

        self.assertEqual(response.status_code, 200)
        token.refresh_from_db()
        self.assertEqual(token.platform, 'ios')
        self.assertEqual(token.fcm_token, 'new-body-token')
        self.assertEqual(token.app_version, '3.0.0')

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

    def test_unregister_endpoint_accepts_access_token_in_body(self):
        own_token = FCMDeviceToken.objects.create(
            user_type='customer',
            user_id=self.customer.id,
            device_id='device-body-unregister',
            platform='android',
            fcm_token='customer-body-token',
            is_active=True,
        )

        request = self.factory.delete(
            '/api/devices/fcm/unregister',
            {
                'device_id': 'device-body-unregister',
                'access_token': self._access_token_for_user(self.customer, 'customer'),
            },
            format='json',
        )

        response = fcm_unregister_device_view(request)

        self.assertEqual(response.status_code, 200)
        own_token.refresh_from_db()
        self.assertFalse(own_token.is_active)


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
            profile_image='drivers/driver_2.jpg',
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
        for call in mock_send.call_args_list:
            self.assertEqual(call.kwargs['channel_id'], 'incoming_ring_channel')
            self.assertTrue(call.kwargs['high_priority'])

    def test_incoming_ring_payload_includes_driver_image_url_for_driver_sender(self):
        payload = build_incoming_ring_payload(
            order=self.order,
            ring_payload={
                'ring_id': 'ring-driver-1',
                'sender_type': 'driver',
                'sender_id': self.driver.id,
                'sender_name': self.driver.name,
                'chat_type': 'driver_customer',
            },
            target='customer',
            shop_name=self.shop.shop_name,
            shop_profile_image_url='https://example.com/media/shop_profiles/shop.jpg',
        )

        self.assertEqual(payload['sender_type'], 'driver')
        self.assertIn('driver_image_url', payload)
        self.assertTrue(str(payload['driver_image_url'] or '').endswith('/media/drivers/driver_2.jpg'))

    def test_ring_dispatch_context_includes_driver_image_url_for_driver_sender(self):
        context = async_to_sync(_build_ring_dispatch_context)(
            self.driver,
            'driver',
            self.order.id,
            ['customer'],
            chat_type='driver_customer',
        )

        self.assertNotIn('error', context)
        self.assertEqual(context['payload']['sender_type'], 'driver')
        self.assertEqual(context['payload']['chat_type'], 'driver_customer')
        self.assertIn('driver_image_url', context['payload'])
        self.assertTrue(str(context['payload']['driver_image_url'] or '').endswith('/media/drivers/driver_2.jpg'))


class FCMServiceTests(TestCase):
    def setUp(self):
        super().setUp()
        self.category = ShopCategory.objects.create(name='Groceries')
        self.shop = ShopOwner.objects.create(
            owner_name='مالك المحل',
            shop_name='شاورما',
            shop_number='SHOP-300',
            phone_number='01010000003',
            password='secret123',
            shop_category=self.category,
        )
        self.customer = Customer.objects.create(
            shop_owner=self.shop,
            name='أحمد',
            phone_number='01020000003',
            password='secret123',
        )

    @patch('shop.fcm_service._firebase_modules', side_effect=Exception('mock firebase unavailable'))
    @patch('shop.fcm_service.send_push_to_token_record', return_value={'success': True, 'invalid_token': False})
    def test_send_push_to_user_targets_all_active_devices(self, mock_send, mock_firebase_modules):
        FCMDeviceToken.objects.create(
            user_type='customer',
            user_id=self.customer.id,
            device_id='device-a',
            platform='android',
            fcm_token='token-a',
            is_active=True,
        )
        FCMDeviceToken.objects.create(
            user_type='customer',
            user_id=self.customer.id,
            device_id='device-b',
            platform='ios',
            fcm_token='token-b',
            is_active=True,
        )

        summary = send_push_to_user(
            user_type='customer',
            user_id=self.customer.id,
            title='رسالة جديدة',
            body='لديك رسالة جديدة',
            data={'type': 'chat_message'},
            channel_id='chat_channel',
            sound='default',
        )

        self.assertEqual(summary['tokens_total'], 2)
        self.assertEqual(summary['tokens_sent'], 2)
        self.assertEqual(mock_send.call_count, 2)

    @patch('shop.fcm_service._send_push_to_fcm_token', side_effect=Exception('UNREGISTERED'))
    def test_send_push_to_token_record_deactivates_invalid_tokens(self, mock_send):
        token_record = FCMDeviceToken.objects.create(
            user_type='customer',
            user_id=self.customer.id,
            device_id='device-invalid',
            platform='android',
            fcm_token='invalid-token',
            is_active=True,
        )

        result = send_push_to_token_record(
            token_record,
            title='رسالة جديدة',
            body='لديك رسالة جديدة',
            data={'type': 'chat_message'},
            channel_id='chat_channel',
            sound='default',
        )

        self.assertFalse(result['success'])
        self.assertTrue(result['invalid_token'])
        token_record.refresh_from_db()
        self.assertFalse(token_record.is_active)

    def test_stringify_payload_renames_reserved_fcm_keys(self):
        payload = _stringify_payload(
            {
                'message_type': 'text',
                'type': 'chat_message',
                'is_urgent': True,
            }
        )

        self.assertEqual(payload['content_type'], 'text')
        self.assertEqual(payload['type'], 'chat_message')
        self.assertEqual(payload['is_urgent'], 'true')
        self.assertNotIn('message_type', payload)


class DriverNotificationModeTests(TestCase):
    def setUp(self):
        super().setUp()
        self.category = ShopCategory.objects.create(name='Groceries')
        self.shop = ShopOwner.objects.create(
            owner_name='Owner',
            shop_name='Store',
            shop_number='SHOP-400',
            phone_number='01010000004',
            password='secret123',
            shop_category=self.category,
        )
        self.driver = Driver.objects.create(
            name='Driver One',
            phone_number='01030000004',
            password='secret123',
        )
        self.other_driver = Driver.objects.create(
            name='Driver Two',
            phone_number='01030000005',
            password='secret123',
        )
        self.order = Order.objects.create(
            shop_owner=self.shop,
            order_number='OD400',
            status='new',
            items='["Item"]',
            total_amount='80.00',
            delivery_fee='10.00',
            address='Street',
            notes='',
        )
        self.invitation = ShopDriver.objects.create(
            shop_owner=self.shop,
            driver=self.driver,
            status='pending',
        )

    @patch('shop.fcm_service.send_to_user', return_value={'tokens_total': 1, 'tokens_sent': 1, 'tokens_failed': 0, 'tokens_invalidated': 0})
    def test_push_only_driver_notifications_do_not_create_inbox_records(self, mock_send):
        send_driver_new_order_notification(self.driver, self.order)
        send_driver_store_invite_notification(self.driver, self.shop, self.invitation)

        self.assertEqual(mock_send.call_count, 2)
        self.assertFalse(Notification.objects.filter(driver=self.driver).exists())

    @patch('shop.fcm_service.send_to_user', return_value={'tokens_total': 1, 'tokens_sent': 1, 'tokens_failed': 0, 'tokens_invalidated': 0})
    def test_driver_system_notification_creates_record_and_push_payload(self, mock_send):
        result = send_driver_system_notification(
            self.driver,
            title='Important notice',
            body='Message from admin',
            data={'type': 'general_notification'},
            reference_id='admin-1',
            idempotency_key='driver-admin-1',
        )

        notification = result['notification']
        self.assertIsNotNone(notification)
        self.assertEqual(notification.driver_id, self.driver.id)
        self.assertEqual(notification.notification_type, 'general_notification')
        self.assertEqual(notification.data['screen'], 'notifications')
        sent_payload = mock_send.call_args.kwargs['data']
        self.assertEqual(sent_payload['notification_id'], str(notification.id))
        self.assertEqual(sent_payload['screen'], 'notifications')
        self.assertEqual(sent_payload['type'], 'general_notification')
        self.assertEqual(sent_payload['route'], '/notifications')
        self.assertEqual(sent_payload['click_action'], 'OPEN_NOTIFICATIONS')

    @patch('shop.fcm_service.send_to_user', return_value={'tokens_total': 1, 'tokens_sent': 1, 'tokens_failed': 0, 'tokens_invalidated': 0})
    def test_driver_system_notifications_create_independent_read_records_per_driver(self, mock_send):
        summary = send_driver_system_notifications(
            [self.driver, self.other_driver],
            title='Broadcast',
            body='For all drivers',
            data={'type': 'general_notification'},
            reference_id='broadcast-1',
            idempotency_key='broadcast-1',
        )

        self.assertEqual(summary['drivers_targeted'], 2)
        self.assertEqual(Notification.objects.filter(reference_id='broadcast-1').count(), 2)
        self.assertEqual(mock_send.call_count, 2)

    @patch('shop.fcm_service.send_to_user', return_value={'users_targeted': 1, 'tokens_total': 1, 'tokens_sent': 1, 'tokens_failed': 0, 'tokens_invalidated': 0})
    def test_store_driver_chat_message_sends_push_only_to_driver(self, mock_send):
        from shop.driver_chat.service import store_send_text

        conversation = DriverChatConversation.objects.create(
            shop_owner=self.shop,
            driver=self.driver,
            status='waiting_reply',
        )

        message = store_send_text(conversation=conversation, text='New store message')

        self.assertIsNotNone(message)
        self.assertEqual(mock_send.call_count, 1)
        self.assertFalse(Notification.objects.filter(driver=self.driver, notification_type='chat_message').exists())
        sent_payload = mock_send.call_args.kwargs['data']
        self.assertEqual(sent_payload['type'], 'chat_message')
        self.assertEqual(sent_payload['screen'], 'chat')
        self.assertEqual(sent_payload['conversation_id'], conversation.public_id)

    @patch('shop.fcm_service.send_to_user', return_value={'tokens_total': 2, 'tokens_sent': 1, 'tokens_failed': 1, 'tokens_invalidated': 1})
    def test_attach_driver_notification_dispatches_fcm_after_commit(self, mock_send):
        with self.captureOnCommitCallbacks(execute=True):
            notification = _attach_notification_to_user(
                'driver',
                self.driver,
                title='Account suspended',
                message='Suspended by support.',
                notification_type='account_suspended',
                data={'type': 'account_suspended'},
            )

        self.assertIsNotNone(notification)
        sent_payload = mock_send.call_args.kwargs['data']
        self.assertEqual(sent_payload['type'], 'account_suspended')
        self.assertEqual(sent_payload['screen'], 'notifications')
        self.assertEqual(sent_payload['route'], '/notifications')
        self.assertEqual(sent_payload['notification_id'], str(notification.id))
        self.assertEqual(mock_send.call_args.kwargs['click_action'], 'OPEN_NOTIFICATIONS')

    def test_build_driver_inbox_notification_payload_normalizes_order_and_chat(self):
        order_payload = build_driver_inbox_notification_payload(
            notification_type='order_status',
            notification_id=68,
            data={'order_id': 99},
        )
        chat_payload = build_driver_inbox_notification_payload(
            notification_type='chat',
            notification_id=69,
            data={'conversation_id': 'conv-1', 'order_id': 100},
        )

        self.assertEqual(order_payload['type'], 'order')
        self.assertEqual(order_payload['screen'], 'order_details')
        self.assertEqual(order_payload['order_id'], '99')
        self.assertEqual(order_payload['click_action'], 'OPEN_ORDER')
        self.assertEqual(chat_payload['type'], 'chat_message')
        self.assertEqual(chat_payload['screen'], 'chat')
        self.assertEqual(chat_payload['conversation_id'], 'conv-1')
        self.assertEqual(chat_payload['order_id'], '100')
        self.assertEqual(chat_payload['click_action'], 'OPEN_CHAT')
