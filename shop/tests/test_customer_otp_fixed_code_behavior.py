from django.core.cache import cache
from django.test import TestCase, override_settings

from user.otp_service import send_otp, verify_otp


class CustomerOtpFixedCodeBehaviorTests(TestCase):
    def setUp(self):
        super().setUp()
        cache.clear()

    @override_settings(FIXED_OTP_CODE="123456")
    def test_fixed_code_can_be_disabled_for_customer_email_targets(self):
        success, _message = send_otp("customer@example.com", allow_fixed_code=False)

        self.assertFalse(success)
        self.assertFalse(verify_otp("customer@example.com", "123456", allow_fixed_code=False))

    @override_settings(FIXED_OTP_CODE="123456")
    def test_fixed_code_still_works_for_other_flows(self):
        success, _message = send_otp("+201012345678", allow_fixed_code=True)

        self.assertTrue(success)
        self.assertTrue(verify_otp("+201012345678", "123456", allow_fixed_code=True))

