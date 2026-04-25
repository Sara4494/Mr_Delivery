from django.test import TestCase
from rest_framework.test import APIRequestFactory, force_authenticate

from shop.models import AccountModerationStatus, Customer, Driver, Offer
from shop.views import customer_profile_view, public_offers_view, public_shop_categories_list_view
from user.models import ShopCategory, ShopOwner


class SuspendedAccountApiTests(TestCase):
    def setUp(self):
        super().setUp()
        self.factory = APIRequestFactory()
        self.category = ShopCategory.objects.create(name="Groceries")
        self.shop = ShopOwner.objects.create(
            owner_name="Shop Owner",
            shop_name="Fresh Shop",
            shop_number="SHOP-SUSP-1",
            phone_number="01010000111",
            password="secret123",
            shop_category=self.category,
        )
        self.customer = Customer.objects.create(
            shop_owner=self.shop,
            name="Suspended Customer",
            phone_number="01010000112",
            password="secret123",
        )
        self.driver = Driver.objects.create(
            name="Driver User",
            phone_number="01010000113",
            password="secret123",
        )
        self.offer = Offer.objects.create(
            shop_owner=self.shop,
            title="Weekend Offer",
            description="Discount",
            discount_percentage="15.00",
            start_date="2026-01-01",
            end_date="2026-12-31",
            is_active=True,
        )
        AccountModerationStatus.objects.create(
            customer=self.customer,
            is_suspended=True,
            suspension_reason="Too many violations",
        )

    def _assert_suspended_response(self, response):
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.data["code"], "account_suspended")
        self.assertEqual(
            response.data["detail"],
            "تم تعطيل حسابك مؤقتًا. يرجى التواصل مع الدعم.",
        )
        self.assertEqual(response.data["reason"], "Too many violations")

    def test_customer_profile_returns_account_suspended_payload(self):
        request = self.factory.get("/api/customer/profile/", HTTP_ACCEPT_LANGUAGE="ar")
        force_authenticate(request, user=self.customer)

        response = customer_profile_view(request)

        self._assert_suspended_response(response)

    def test_shop_categories_returns_account_suspended_payload_before_customer_only_message(self):
        request = self.factory.get("/api/shops/shop-categories/", HTTP_ACCEPT_LANGUAGE="ar")
        force_authenticate(request, user=self.customer)

        response = public_shop_categories_list_view(request)

        self._assert_suspended_response(response)

    def test_offers_returns_account_suspended_payload_for_suspended_customer(self):
        request = self.factory.get("/api/shops/offers/", HTTP_ACCEPT_LANGUAGE="ar")
        force_authenticate(request, user=self.customer)

        response = public_offers_view(request)

        self._assert_suspended_response(response)
