from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase

from user.models import AppVersion


class DriverAppVersionEndpointTests(TestCase):
    def test_returns_false_when_no_driver_app_version_exists(self):
        response = self.client.get("/api/driver/app-version/")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertFalse(payload["status"])
        self.assertEqual(payload["message"], "No app version found")
        self.assertIsNone(payload["data"])

    def test_returns_latest_driver_app_version_payload(self):
        AppVersion.objects.create(
            version_code=4,
            version_name="1.0.4",
            apk_file=SimpleUploadedFile(
                "zaygo_delivery_v1.0.4.apk",
                b"old-apk",
                content_type="application/vnd.android.package-archive",
            ),
            is_force_update=False,
            release_notes="Old release.",
        )
        AppVersion.objects.create(
            version_code=5,
            version_name="1.0.5",
            apk_file=SimpleUploadedFile(
                "zaygo_delivery_v1.0.5.apk",
                b"new-apk",
                content_type="application/vnd.android.package-archive",
            ),
            is_force_update=True,
            release_notes="- Added live tracking.\n- Improved order delivery speed.",
        )

        response = self.client.get("/api/driver/app-version/")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["status"])
        self.assertEqual(payload["message"], "Success")
        self.assertEqual(payload["data"]["version_code"], 5)
        self.assertEqual(payload["data"]["version_name"], "1.0.5")
        self.assertTrue(payload["data"]["is_force_update"])
        self.assertEqual(payload["data"]["release_notes"], "- Added live tracking.\n- Improved order delivery speed.")
        self.assertTrue(payload["data"]["apk_url"].startswith("http://testserver/media/downloads/zaygo_driver/"))
        self.assertIn("zaygo_delivery_v1.0.5", payload["data"]["apk_url"])
