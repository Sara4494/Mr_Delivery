from datetime import timedelta

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from user.models import AdminDesktopUser, AppMaintenanceSettings


class AdminDesktopExcludedFromCustomerMaintenanceTests(TestCase):
    def setUp(self):
        super().setUp()
        self.client = APIClient()
        self.admin_user = AdminDesktopUser.objects.create(
            name="Maintenance Admin",
            phone_number="+201000001333",
            email="maintenance-admin@example.com",
            password="secret123",
            role="system_developer",
        )
        maintenance = AppMaintenanceSettings.get_solo()
        maintenance.enabled = True
        maintenance.target_user_type = "customer"
        maintenance.target_platform = "android"
        maintenance.retry_after_seconds = 300
        maintenance.starts_at = timezone.now() - timedelta(minutes=5)
        maintenance.ends_at = timezone.now() + timedelta(minutes=5)
        maintenance.save()

    def test_admin_desktop_endpoint_remains_available_during_customer_maintenance(self):
        self.client.force_authenticate(user=self.admin_user)
        response = self.client.get("/api/admin-desktop/app-status/maintenance/", HTTP_X_PLATFORM="android")

        self.assertEqual(response.status_code, 200)
