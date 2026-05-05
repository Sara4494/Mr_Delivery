from datetime import timedelta

from django.test import TestCase
from django.utils import timezone
from django.core.files.uploadedfile import SimpleUploadedFile
from rest_framework.test import APIClient

from shop.models import Customer
from user.models import AdminDesktopUser, AppMaintenanceSettings, AppStatusSettings


class AppStatusEndpointTests(TestCase):
    def setUp(self):
        super().setUp()
        self.client = APIClient()
        self.maintenance = AppMaintenanceSettings.get_solo()
        self.app_status = AppStatusSettings.get_solo()

    def test_app_maintenance_singleton_sets_timestamps_when_created(self):
        AppMaintenanceSettings.objects.all().delete()

        maintenance = AppMaintenanceSettings()
        maintenance.save()

        self.assertEqual(maintenance.pk, 1)
        self.assertIsNotNone(maintenance.created_at)
        self.assertIsNotNone(maintenance.updated_at)

    def test_app_status_returns_disabled_payload_by_default(self):
        response = self.client.get(
            "/api/app/status/",
            {
                "platform": "android",
                "app_version": "1.0.0",
                "build_number": "1",
                "user_type": "customer",
                "lang": "ar",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Cache-Control"], "no-store")

        payload = response.json()
        self.assertEqual(payload["status"], 200)
        self.assertFalse(payload["data"]["maintenance"]["enabled"])
        self.assertIsNone(payload["data"]["maintenance"]["code"])
        self.assertIsNone(payload["data"]["maintenance"]["title"])
        self.assertIsNone(payload["data"]["maintenance"]["message"])

    def test_app_status_returns_localized_maintenance_payload_when_live(self):
        self.maintenance.enabled = True
        self.maintenance.target_user_type = "customer"
        self.maintenance.target_platform = "android"
        self.maintenance.title_ar = "نقوم حاليًا بأعمال صيانة"
        self.maintenance.title_en = "We are currently performing maintenance"
        self.maintenance.message_ar = "نعمل الآن على تحسين الخدمة وتجهيز تحديثات مهمة للتطبيق. يرجى المحاولة مرة أخرى بعد قليل."
        self.maintenance.message_en = "We are improving the service and preparing important app updates. Please try again shortly."
        self.maintenance.footnote_ar = "شكرًا لصبرك. سنعود إليك في أقرب وقت ممكن."
        self.maintenance.footnote_en = "Thank you for your patience. We will be back as soon as possible."
        self.maintenance.retry_after_seconds = 300
        self.maintenance.starts_at = timezone.now() - timedelta(minutes=10)
        self.maintenance.ends_at = timezone.now() + timedelta(minutes=50)
        self.maintenance.save()

        response = self.client.get(
            "/api/app/status/",
            {
                "platform": "android",
                "app_version": "1.0.0",
                "build_number": "1",
                "user_type": "customer",
                "lang": "ar",
            },
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        maintenance = payload["data"]["maintenance"]
        self.assertTrue(maintenance["enabled"])
        self.assertEqual(maintenance["code"], "maintenance_mode")
        self.assertEqual(maintenance["title"], "نقوم حاليًا بأعمال صيانة")
        self.assertEqual(maintenance["message"], "نعمل الآن على تحسين الخدمة وتجهيز تحديثات مهمة للتطبيق. يرجى المحاولة مرة أخرى بعد قليل.")
        self.assertEqual(maintenance["footnote"], "شكرًا لصبرك. سنعود إليك في أقرب وقت ممكن.")
        self.assertEqual(maintenance["retry_after_seconds"], 300)
        self.assertTrue(maintenance["starts_at"].endswith("Z"))
        self.assertTrue(maintenance["ends_at"].endswith("Z"))

    def test_app_status_respects_target_filters(self):
        self.maintenance.enabled = True
        self.maintenance.target_user_type = "customer"
        self.maintenance.target_platform = "ios"
        self.maintenance.starts_at = timezone.now() - timedelta(minutes=5)
        self.maintenance.ends_at = timezone.now() + timedelta(minutes=5)
        self.maintenance.save()

        response = self.client.get(
            "/api/app/status/",
            {"platform": "android", "user_type": "customer", "lang": "en"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json()["data"]["maintenance"]["enabled"])

    def test_app_status_supports_multiple_targets(self):
        self.maintenance.enabled = True
        self.maintenance.set_target_user_types(["customer", "driver"])
        self.maintenance.set_target_platforms(["android", "ios"])
        self.maintenance.starts_at = timezone.now() - timedelta(minutes=5)
        self.maintenance.ends_at = timezone.now() + timedelta(minutes=5)
        self.maintenance.save()

        customer_response = self.client.get(
            "/api/app/status/",
            {"platform": "ios", "user_type": "customer", "lang": "en"},
        )
        shop_response = self.client.get(
            "/api/app/status/",
            {"platform": "ios", "user_type": "shop", "lang": "en"},
        )

        self.assertTrue(customer_response.json()["data"]["maintenance"]["enabled"])
        self.assertFalse(shop_response.json()["data"]["maintenance"]["enabled"])

    def test_app_status_returns_update_values_from_model(self):
        self.app_status.maintenance_mode = True
        self.app_status.update_enabled = True
        self.app_status.force_update = True
        self.app_status.android_min_version = "2.1.0"
        self.app_status.android_store_url = "https://play.google.com/store/apps/details?id=mr.delivery"
        self.app_status.ios_min_version = "2.2.0"
        self.app_status.ios_store_url = "https://apps.apple.com/app/id123456789"
        self.app_status.windows_min_version = "1.5.0"
        self.app_status.windows_download_url = "https://example.com/windows.exe"
        self.app_status.maintenance_title_ar = "تحديث مهم"
        self.app_status.maintenance_title_en = "Important update"
        self.app_status.maintenance_message_ar = "يرجى تحديث التطبيق"
        self.app_status.maintenance_message_en = "Please update the app"
        self.app_status.maintenance_window_label_ar = "الآن"
        self.app_status.maintenance_window_label_en = "Now"
        self.app_status.save()

        response = self.client.get(
            "/api/app/status/",
            {"platform": "android", "user_type": "customer", "lang": "ar"},
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()["data"]
        self.assertTrue(payload["maintenance_mode"])
        self.assertTrue(payload["update"]["enabled"])
        self.assertTrue(payload["update"]["force_update"])
        self.assertEqual(payload["update"]["android"]["min_version"], "2.1.0")
        self.assertEqual(payload["update"]["ios"]["min_version"], "2.2.0")
        self.assertEqual(payload["update"]["windows"]["download_url"], "https://example.com/windows.exe")
        self.assertEqual(payload["maintenance"]["title_ar"], "تحديث مهم")
        self.assertEqual(payload["maintenance"]["message_ar"], "يرجى تحديث التطبيق")
        self.assertEqual(payload["maintenance"]["window_label_ar"], "الآن")

    def test_app_status_prefers_uploaded_windows_installer_file(self):
        self.app_status.windows_download_url = "https://example.com/old.exe"
        self.app_status.windows_installer_file = SimpleUploadedFile(
            "MrDeliverySetup.exe",
            b"dummy-binary",
            content_type="application/octet-stream",
        )
        self.app_status.save()

        response = self.client.get(
            "/api/app/status/",
            {"platform": "android", "user_type": "customer", "lang": "ar"},
        )

        self.assertEqual(response.status_code, 200)
        download_url = response.json()["data"]["update"]["windows"]["download_url"]
        self.assertIn("/media/downloads/app_status/MrDeliverySetup", download_url)


class CustomerMaintenanceBlockingTests(TestCase):
    def setUp(self):
        super().setUp()
        self.client = APIClient()
        self.customer = Customer.objects.create(
            name="Maintenance Customer",
            phone_number="+201000001111",
            password="secret123",
            is_verified=True,
        )
        maintenance = AppMaintenanceSettings.get_solo()
        maintenance.enabled = True
        maintenance.target_user_type = "customer"
        maintenance.target_platform = "android"
        maintenance.retry_after_seconds = 300
        maintenance.starts_at = timezone.now() - timedelta(minutes=5)
        maintenance.ends_at = timezone.now() + timedelta(minutes=5)
        maintenance.save()

    def test_public_status_remains_available_during_maintenance(self):
        response = self.client.get(
            "/api/app/status/",
            {"platform": "android", "user_type": "customer", "lang": "en"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["data"]["maintenance"]["enabled"])

    def test_customer_protected_api_returns_503_when_maintenance_matches(self):
        self.client.force_authenticate(user=self.customer)
        response = self.client.get("/api/customer/profile/", HTTP_X_PLATFORM="android")

        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()["code"], "maintenance_mode")
        self.assertEqual(response.json()["retry_after_seconds"], 300)

    def test_customer_protected_api_continues_when_platform_does_not_match(self):
        self.client.force_authenticate(user=self.customer)
        response = self.client.get("/api/customer/profile/", HTTP_X_PLATFORM="ios")

        self.assertEqual(response.status_code, 200)


class AdminDesktopMaintenanceSettingsTests(TestCase):
    def setUp(self):
        super().setUp()
        self.client = APIClient()
        self.admin_user = AdminDesktopUser.objects.create(
            name="System Developer",
            phone_number="+201000001222",
            email="developer@example.com",
            password="secret123",
            role="system_developer",
        )
        self.client.force_authenticate(user=self.admin_user)

    def test_admin_desktop_can_read_maintenance_settings(self):
        response = self.client.get("/api/admin-desktop/app-status/maintenance/")

        self.assertEqual(response.status_code, 200)
        self.assertIn("maintenance", response.data["data"])
        self.assertEqual(response.data["data"]["maintenance"]["code"], "maintenance_mode")

    def test_admin_desktop_can_update_maintenance_settings(self):
        response = self.client.patch(
            "/api/admin-desktop/app-status/maintenance/",
            {
                "enabled": True,
                "target_user_types": ["customer", "driver"],
                "target_platforms": ["android", "ios"],
                "title_ar": "صيانة مجدولة",
                "title_en": "Scheduled maintenance",
                "message_ar": "يرجى الانتظار قليلًا.",
                "message_en": "Please wait a moment.",
                "footnote_ar": "شكرًا لتفهمك.",
                "footnote_en": "Thank you for understanding.",
                "starts_at": "2026-04-26T20:00:00Z",
                "ends_at": "2026-04-26T22:00:00Z",
                "retry_after_seconds": 300,
            },
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        settings_obj = AppMaintenanceSettings.get_solo()
        self.assertTrue(settings_obj.enabled)
        self.assertEqual(settings_obj.get_target_user_types(), ["customer", "driver"])
        self.assertEqual(settings_obj.get_target_platforms(), ["android", "ios"])
        self.assertEqual(settings_obj.title_ar, "صيانة مجدولة")
