from unittest.mock import patch

from django.core.cache import cache
from django.test import TestCase
from rest_framework.test import APIClient

from shop.models import Customer


class CustomerProfilePhoneOtpTests(TestCase):
    def setUp(self):
        super().setUp()
        cache.clear()
        self.client = APIClient()
        self.customer = Customer.objects.create(
            name="Customer One",
            phone_number="+201099990101",
            email="customer.one@example.com",
            password="secret123",
            is_verified=True,
        )
        self.client.force_authenticate(user=self.customer)

    @patch("shop.views.otp_send", return_value=(True, "sent"))
    def test_send_otp_uses_customer_email_not_phone(self, mock_otp_send):
        response = self.client.post(
            "/api/customer/profile/phone/send-otp/",
            {"new_phone_number": "01012345678"},
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        mock_otp_send.assert_called_once_with("customer.one@example.com")
        self.assertEqual(response.data["message"], "OTP sent successfully to your email")
        self.assertEqual(response.data["data"]["email"], "customer.one@example.com")
        self.assertEqual(response.data["data"]["new_phone_number"], "+201012345678")

    def test_send_otp_rejects_customer_without_email(self):
        self.customer.email = None
        self.customer.save(update_fields=["email", "updated_at"])

        response = self.client.post(
            "/api/customer/profile/phone/send-otp/",
            {"new_phone_number": "01012345678"},
            format="json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data["message"], "Customer email is required for OTP verification")
        self.assertIn("email", response.data["errors"])

    @patch("shop.views.otp_verify", return_value=True)
    @patch("shop.views.otp_send", return_value=(True, "sent"))
    def test_verify_otp_uses_email_and_updates_phone(self, mock_otp_send, mock_otp_verify):
        send_response = self.client.post(
            "/api/customer/profile/phone/send-otp/",
            {"new_phone_number": "01012345678"},
            format="json",
        )
        self.assertEqual(send_response.status_code, 200)

        verify_response = self.client.post(
            "/api/customer/profile/phone/verify-otp/",
            {
                "new_phone_number": "01012345678",
                "otp": "123456",
            },
            format="json",
        )

        self.assertEqual(verify_response.status_code, 200)
        mock_otp_send.assert_called_once_with("customer.one@example.com")
        mock_otp_verify.assert_called_once_with("customer.one@example.com", "123456")
        self.customer.refresh_from_db()
        self.assertEqual(self.customer.phone_number, "+201012345678")

