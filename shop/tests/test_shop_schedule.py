from datetime import datetime
from zoneinfo import ZoneInfo
from unittest.mock import patch

from django.test import TestCase

from shop.models import Customer, ShopStatus, sync_shop_status_with_work_schedule
from shop.serializers import CustomerOrderCreateSerializer
from user.models import ShopCategory, ShopOwner, default_work_schedule


CAIRO = ZoneInfo("Africa/Cairo")


class ShopScheduleAutoStatusTests(TestCase):
    def setUp(self):
        super().setUp()
        self.category = ShopCategory.objects.create(name="Fast Food")
        self.shop_owner = ShopOwner.objects.create(
            owner_name="Shop Owner",
            shop_name="Demo Shop",
            shop_number="SHOP-200",
            phone_number="01000000011",
            password="secret123",
            shop_category=self.category,
            work_schedule=default_work_schedule(),
        )
        self.customer = Customer.objects.create(
            shop_owner=self.shop_owner,
            name="Customer One",
            phone_number="01000000012",
            is_verified=True,
        )

    def _cairo_dt(self, hour, minute=0):
        return datetime(2026, 6, 27, hour, minute, tzinfo=CAIRO)

    def test_shop_status_becomes_open_during_working_hours(self):
        schedule = default_work_schedule()
        schedule["saturday"] = {"is_working": True, "start_time": "09:00", "end_time": "17:00"}
        self.shop_owner.work_schedule = schedule
        self.shop_owner.save(update_fields=["work_schedule"])
        ShopStatus.objects.create(shop_owner=self.shop_owner, status="closed")

        with patch("shop.models._shop_schedule_localtime", return_value=self._cairo_dt(10)):
            status_obj, _, state, changed = sync_shop_status_with_work_schedule(self.shop_owner)

        self.assertTrue(state["is_open_now"])
        self.assertTrue(changed)
        self.assertEqual(status_obj.status, "open")

    def test_shop_status_becomes_closed_outside_working_hours(self):
        schedule = default_work_schedule()
        schedule["saturday"] = {"is_working": True, "start_time": "09:00", "end_time": "17:00"}
        self.shop_owner.work_schedule = schedule
        self.shop_owner.save(update_fields=["work_schedule"])
        ShopStatus.objects.create(shop_owner=self.shop_owner, status="open")

        with patch("shop.models._shop_schedule_localtime", return_value=self._cairo_dt(20)):
            status_obj, _, state, changed = sync_shop_status_with_work_schedule(self.shop_owner)

        self.assertFalse(state["is_open_now"])
        self.assertTrue(changed)
        self.assertEqual(status_obj.status, "closed")

    def test_customer_order_is_rejected_when_shop_is_closed(self):
        schedule = default_work_schedule()
        schedule["saturday"] = {"is_working": True, "start_time": "09:00", "end_time": "17:00"}
        self.shop_owner.work_schedule = schedule
        self.shop_owner.save(update_fields=["work_schedule"])
        ShopStatus.objects.create(shop_owner=self.shop_owner, status="open")

        serializer = CustomerOrderCreateSerializer(
            data={
                "address": "Cairo",
                "items": ["Burger"],
                "shop_owner_id": self.shop_owner.id,
            },
            context={"customer": self.customer},
        )

        with patch("shop.models._shop_schedule_localtime", return_value=self._cairo_dt(20)):
            self.assertFalse(serializer.is_valid())

        self.assertIn("shop", serializer.errors)
