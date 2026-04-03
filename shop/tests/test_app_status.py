from django.test import SimpleTestCase, override_settings
from rest_framework.test import APIClient


class AppStatusEndpointTests(SimpleTestCase):
    def setUp(self):
        super().setUp()
        self.client = APIClient()

    @override_settings(
        APP_STATUS_MAINTENANCE_MODE=True,
        APP_STATUS_MAINTENANCE_TITLE_AR='التطبيق تحت الصيانة حاليًا',
        APP_STATUS_MAINTENANCE_TITLE_EN='The app is currently under maintenance',
        APP_STATUS_MAINTENANCE_MESSAGE_AR='نقوم الآن بتنفيذ تحديثات وتحسينات مهمة. نعتذر عن الإزعاج وسيعود التطبيق قريبًا.',
        APP_STATUS_MAINTENANCE_MESSAGE_EN='We are applying important updates and improvements. Sorry for the interruption.',
        APP_STATUS_MAINTENANCE_WINDOW_LABEL_AR='اليوم 11:30 مساءً',
        APP_STATUS_MAINTENANCE_WINDOW_LABEL_EN='Today 11:30 PM',
        APP_STATUS_SHOW_CONTACT_SUPPORT=True,
        APP_STATUS_SUPPORT_WHATSAPP='201000000000',
        APP_STATUS_ESTIMATED_MINUTES=90,
        APP_STATUS_FORCE_UPDATE_ENABLED=False,
        APP_STATUS_FORCE_UPDATE_CURRENT_VERSION='1.0.0',
        APP_STATUS_FORCE_UPDATE_REQUIRED_VERSION='1.0.0',
    )
    def test_app_status_returns_public_contract(self):
        response = self.client.get('/api/app/status')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Cache-Control'], 'no-store')

        payload = response.json()
        self.assertTrue(payload['success'])
        self.assertTrue(payload['data']['maintenance_mode'])
        self.assertEqual(payload['data']['maintenance']['title_ar'], 'التطبيق تحت الصيانة حاليًا')
        self.assertEqual(payload['data']['maintenance']['title_en'], 'The app is currently under maintenance')
        self.assertEqual(payload['data']['maintenance']['window_label_ar'], 'اليوم 11:30 مساءً')
        self.assertEqual(payload['data']['maintenance']['window_label_en'], 'Today 11:30 PM')
        self.assertTrue(payload['data']['maintenance']['show_contact_support'])
        self.assertEqual(payload['data']['maintenance']['support_whatsapp'], '201000000000')
        self.assertEqual(payload['data']['maintenance']['estimated_minutes'], 90)
        self.assertFalse(payload['data']['force_update']['enabled'])
        self.assertEqual(payload['data']['force_update']['current_version'], '1.0.0')
        self.assertEqual(payload['data']['force_update']['required_version'], '1.0.0')

    @override_settings(APP_STATUS_MAINTENANCE_MODE=False)
    def test_app_status_supports_trailing_slash_and_defaults(self):
        response = self.client.get('/api/app/status/')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Cache-Control'], 'no-store')

        payload = response.json()
        self.assertTrue(payload['success'])
        self.assertFalse(payload['data']['maintenance_mode'])
        self.assertIn('maintenance', payload['data'])
        self.assertIn('force_update', payload['data'])
        self.assertIn('message_ar', payload['data']['maintenance'])
        self.assertIn('message_en', payload['data']['maintenance'])

    @override_settings(
        APP_STATUS_FORCE_UPDATE_ENABLED=True,
        APP_STATUS_FORCE_UPDATE_CURRENT_VERSION='2.3.0',
        APP_STATUS_FORCE_UPDATE_REQUIRED_VERSION='',
    )
    def test_app_status_uses_current_version_when_required_version_missing(self):
        response = self.client.get('/api/app/status')

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload['data']['force_update']['enabled'])
        self.assertEqual(payload['data']['force_update']['current_version'], '2.3.0')
        self.assertEqual(payload['data']['force_update']['required_version'], '2.3.0')
