from django.test import TestCase
from rest_framework.test import APIRequestFactory, force_authenticate

from shop.models import Driver
from shop.views import driver_status_view


class DriverStatusSnapshotTests(TestCase):
    def setUp(self):
        super().setUp()
        self.factory = APIRequestFactory()
        self.driver = Driver.objects.create(
            name='Driver One',
            phone_number='01050000111',
            is_verified=True,
            availability_enabled=False,
            status='offline',
        )
        self.driver.set_password('secret123')
        self.driver.save()

    def test_availability_snapshot_keeps_driver_online_without_websocket(self):
        self.driver.availability_enabled = True
        self.driver.save(update_fields=['availability_enabled', 'updated_at'])

        snapshot = self.driver.get_availability_snapshot(active_orders_count=0, in_delivery_count=0)

        self.assertFalse(snapshot['presence_online'])
        self.assertTrue(snapshot['is_online'])
        self.assertTrue(snapshot['can_receive_orders'])
        self.assertEqual(snapshot['status'], 'available')

    def test_driver_status_patch_returns_online_when_availability_is_enabled(self):
        request = self.factory.patch(
            '/api/driver/status/',
            {'is_online': True},
            format='json',
        )
        force_authenticate(request, user=self.driver)

        response = driver_status_view(request)

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data['data']['is_online'])
        self.assertTrue(response.data['data']['can_receive_orders'])
        self.assertEqual(response.data['data']['status'], 'available')

