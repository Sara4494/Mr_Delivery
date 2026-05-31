from unittest.mock import Mock, patch

from django.core.cache import cache
from django.test import TestCase, override_settings

from user.otp_service import send_otp, verify_otp


class TwilioWhatsappOtpTests(TestCase):
    def setUp(self):
        super().setUp()
        cache.clear()

    @override_settings(
        FIXED_OTP_CODE="",
        TWILIO_ACCOUNT_SID="ACxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx",
        TWILIO_AUTH_TOKEN="secret",
        TWILIO_WHATSAPP_FROM="whatsapp:+14155238886",
        TWILIO_WHATSAPP_OTP_CONTENT_SID="HX1234567890",
    )
    @patch("twilio.rest.Client")
    def test_send_otp_uses_twilio_whatsapp_template(self, mock_client_class):
        mock_client = Mock()
        mock_client.messages.create.return_value = Mock(sid="SM123")
        mock_client_class.return_value = mock_client

        success, _message = send_otp("+201012345678", allow_fixed_code=False)

        self.assertTrue(success)
        create_kwargs = mock_client.messages.create.call_args.kwargs
        self.assertEqual(create_kwargs["from_"], "whatsapp:+14155238886")
        self.assertEqual(create_kwargs["to"], "whatsapp:+201012345678")
        self.assertEqual(create_kwargs["content_sid"], "HX1234567890")
        self.assertIn('"1"', create_kwargs["content_variables"])
        sent_code = cache.get("otp:+201012345678")
        self.assertTrue(sent_code)
        self.assertTrue(verify_otp("+201012345678", sent_code, allow_fixed_code=False))

    @override_settings(
        FIXED_OTP_CODE="",
        TWILIO_ACCOUNT_SID="ACxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx",
        TWILIO_AUTH_TOKEN="secret",
        TWILIO_WHATSAPP_FROM="whatsapp:+14155238886",
        TWILIO_VERIFY_SERVICE_SID="VA1234567890",
    )
    @patch("twilio.rest.Client")
    def test_send_and_verify_otp_can_use_twilio_verify(self, mock_client_class):
        mock_client = Mock()
        mock_client.verify.v2.services.return_value.verifications.create.return_value = Mock(
            sid="VE123"
        )
        mock_client.verify.v2.services.return_value.verification_checks.create.return_value = Mock(
            status="approved"
        )
        mock_client_class.return_value = mock_client

        success, _message = send_otp("+201055555555", allow_fixed_code=False)

        self.assertTrue(success)
        mock_client.verify.v2.services.return_value.verifications.create.assert_called_once_with(
            to="whatsapp:+201055555555",
            channel="whatsapp",
        )
        self.assertIsNone(cache.get("otp:+201055555555"))
        self.assertTrue(verify_otp("+201055555555", "654321", allow_fixed_code=False))
