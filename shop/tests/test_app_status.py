from datetime import timedelta

from django.contrib.admin.sites import AdminSite
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import RequestFactory
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from shop.models import Customer
from user.admin import AppMaintenanceSettingsAdmin, AppMaintenanceSettingsAdminForm
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
        self.assertFalse(payload["data"]["maintenance_mode"])
        self.assertFalse(payload["data"]["update"]["enabled"])
        self.assertFalse(payload["data"]["update"]["force_update"])
        self.assertEqual(payload["data"]["update"]["android"]["min_version"], "")
        self.assertEqual(payload["data"]["update"]["android"]["store_url"], "")
        self.assertEqual(payload["data"]["update"]["ios"]["min_version"], "")
        self.assertEqual(payload["data"]["update"]["ios"]["store_url"], "")
        self.assertEqual(payload["data"]["update"]["windows"]["min_version"], "")
        self.assertEqual(payload["data"]["update"]["windows"]["download_url"], "")
        self.assertFalse(payload["data"]["maintenance"]["enabled"])
        self.assertIsNone(payload["data"]["maintenance"]["code"])
        self.assertIsNone(payload["data"]["maintenance"]["title"])
        self.assertIsNone(payload["data"]["maintenance"]["message"])
        self.assertIsNone(payload["data"]["maintenance"]["footnote"])
        self.assertEqual(payload["data"]["maintenance"]["title_ar"], "")
        self.assertEqual(payload["data"]["maintenance"]["title_en"], "")
        self.assertEqual(payload["data"]["maintenance"]["message_ar"], "")
        self.assertEqual(payload["data"]["maintenance"]["message_en"], "")

    def test_app_status_returns_localized_maintenance_payload_when_live(self):
        self.maintenance.enabled = True
        self.maintenance.target_user_type = "customer"
        self.maintenance.target_platform = "android"
        self.maintenance.title_ar = "Maintenance in progress"
        self.maintenance.title_en = "We are currently performing maintenance"
        self.maintenance.message_ar = "Please try again shortly."
        self.maintenance.message_en = "We are improving the service and preparing important app updates. Please try again shortly."
        self.maintenance.footnote_ar = "Thank you for your patience."
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
        self.assertTrue(payload["data"]["maintenance_mode"])
        self.assertTrue(maintenance["enabled"])
        self.assertEqual(maintenance["code"], "maintenance_mode")
        self.assertEqual(maintenance["title"], "Maintenance in progress")
        self.assertEqual(maintenance["message"], "Please try again shortly.")
        self.assertEqual(maintenance["footnote"], "Thank you for your patience.")
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

    def test_app_status_defaults_public_status_endpoint_to_customer(self):
        self.maintenance.enabled = True
        self.maintenance.target_user_type = "customer"
        self.maintenance.target_platform = "android"
        self.maintenance.starts_at = timezone.now() - timedelta(minutes=5)
        self.maintenance.ends_at = timezone.now() + timedelta(minutes=5)
        self.maintenance.save()

        response = self.client.get(
            "/api/app/status/",
            {"platform": "android", "lang": "en"},
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()["data"]
        self.assertTrue(payload["maintenance_mode"])
        self.assertTrue(payload["maintenance"]["enabled"])
        self.assertEqual(payload["maintenance"]["code"], "maintenance_mode")

    def test_app_status_respects_explicit_shop_user_type_even_when_customer_maintenance_is_live(self):
        self.maintenance.enabled = True
        self.maintenance.target_user_type = "customer"
        self.maintenance.target_platform = "android"
        self.maintenance.starts_at = timezone.now() - timedelta(minutes=5)
        self.maintenance.ends_at = timezone.now() + timedelta(minutes=5)
        self.maintenance.save()

        response = self.client.get(
            "/api/app/status/",
            {"platform": "android", "user_type": "shop", "lang": "en"},
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()["data"]
        self.assertFalse(payload["maintenance_mode"])
        self.assertFalse(payload["maintenance"]["enabled"])
        self.assertIsNone(payload["maintenance"]["code"])
        self.assertIsNone(payload["maintenance"]["title"])
        self.assertIsNone(payload["maintenance"]["message"])

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
        self.app_status.maintenance_title_ar = "Important update"
        self.app_status.maintenance_title_en = "Important update"
        self.app_status.maintenance_message_ar = "Please update the app"
        self.app_status.maintenance_message_en = "Please update the app"
        self.app_status.maintenance_window_label_ar = "Now"
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
        self.assertEqual(payload["maintenance"]["title_ar"], "Important update")
        self.assertEqual(payload["maintenance"]["message_ar"], "Please update the app")
        self.assertEqual(payload["maintenance"]["window_label_ar"], "Now")

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
                "title_ar": "Scheduled maintenance",
                "title_en": "Scheduled maintenance",
                "message_ar": "Please wait a moment.",
                "message_en": "Please wait a moment.",
                "footnote_ar": "Thank you for understanding.",
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
        self.assertEqual(settings_obj.title_ar, "Scheduled maintenance")

    def test_enabling_maintenance_without_new_schedule_activates_it_immediately(self):
        settings_obj = AppMaintenanceSettings.get_solo()
        settings_obj.enabled = False
        settings_obj.target_user_type = "customer"
        settings_obj.target_platform = "all"
        settings_obj.starts_at = timezone.now() + timedelta(hours=10)
        settings_obj.ends_at = timezone.now() + timedelta(hours=34)
        settings_obj.title_ar = "Maintenance"
        settings_obj.title_en = "Maintenance"
        settings_obj.message_ar = "Working on it"
        settings_obj.message_en = "Working on it"
        settings_obj.save()

        response = self.client.patch(
            "/api/admin-desktop/app-status/maintenance/",
            {
                "enabled": True,
            },
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        settings_obj.refresh_from_db()
        self.assertTrue(settings_obj.enabled)
        self.assertTrue(settings_obj.is_live())
        self.assertLessEqual(settings_obj.starts_at, timezone.now())


class AppMaintenanceAdminFormTests(TestCase):
    def setUp(self):
        super().setUp()
        self.factory = RequestFactory()
        self.site = AdminSite()
        self.admin = AppMaintenanceSettingsAdmin(AppMaintenanceSettings, self.site)

    def test_admin_form_enables_maintenance_immediately_with_duration_hours(self):
        settings_obj = AppMaintenanceSettings.get_solo()
        settings_obj.enabled = False
        settings_obj.save()

        form = AppMaintenanceSettingsAdminForm(
            data={
                "enabled": "on",
                "target_user_type": "customer",
                "target_platform": "android",
                "duration_hours": "6",
                "retry_after_seconds": "",
                "title_ar": "Maintenance",
                "title_en": "Maintenance",
                "message_ar": "Please try again later.",
                "message_en": "Please try again later.",
                "footnote_ar": "",
                "footnote_en": "",
                "target_user_types": '["all"]',
                "target_platforms": '["all"]',
            },
            instance=settings_obj,
        )

        self.assertTrue(form.is_valid(), form.errors)
        obj = form.save(commit=False)
        request = self.factory.post("/admin/user/appmaintenancesettings/1/change/")
        self.admin.save_model(request, obj, form, change=True)

        settings_obj.refresh_from_db()
        self.assertTrue(settings_obj.enabled)
        self.assertEqual(settings_obj.get_target_user_types(), ["customer"])
        self.assertEqual(settings_obj.get_target_platforms(), ["android"])
        self.assertTrue(settings_obj.is_live())
        self.assertLessEqual(settings_obj.starts_at, timezone.now())
        self.assertIsNotNone(settings_obj.ends_at)
        self.assertGreater(settings_obj.ends_at, settings_obj.starts_at)

    def test_admin_form_respects_manual_start_and_end_datetimes(self):
        settings_obj = AppMaintenanceSettings.get_solo()
        settings_obj.enabled = False
        settings_obj.save()

        start_at = timezone.now() + timedelta(hours=2)
        end_at = start_at + timedelta(hours=5)
        form = AppMaintenanceSettingsAdminForm(
            data={
                "enabled": "on",
                "target_user_type": "customer",
                "target_platform": "android",
                "duration_hours": "",
                "retry_after_seconds": "",
                "starts_at": start_at.strftime("%Y-%m-%d %H:%M:%S"),
                "ends_at": end_at.strftime("%Y-%m-%d %H:%M:%S"),
                "title_ar": "Maintenance",
                "title_en": "Maintenance",
                "message_ar": "Please try again later.",
                "message_en": "Please try again later.",
                "footnote_ar": "",
                "footnote_en": "",
                "target_user_types": '["all"]',
                "target_platforms": '["all"]',
            },
            instance=settings_obj,
        )

        self.assertTrue(form.is_valid(), form.errors)
        obj = form.save(commit=False)
        request = self.factory.post("/admin/user/appmaintenancesettings/1/change/")
        self.admin.save_model(request, obj, form, change=True)

        settings_obj.refresh_from_db()
        self.assertEqual(settings_obj.get_target_user_types(), ["customer"])
        self.assertEqual(settings_obj.get_target_platforms(), ["android"])
        self.assertIsNotNone(settings_obj.starts_at)
        self.assertIsNotNone(settings_obj.ends_at)
        self.assertEqual(settings_obj.starts_at.replace(microsecond=0), start_at.replace(microsecond=0))
        self.assertEqual(settings_obj.ends_at.replace(microsecond=0), end_at.replace(microsecond=0))
