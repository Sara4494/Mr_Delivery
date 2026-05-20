from django.test import TestCase

from .store_monitoring import get_store_monitoring_snapshot
from user.models import ShopOwner


class StoreMonitoringSnapshotTests(TestCase):
    def test_snapshot_includes_absolute_image_url(self):
        shop = ShopOwner.objects.create(
            owner_name="Store Owner",
            shop_name="Demo Store",
            shop_number="SHOP-MON-1",
            phone_number="01000000000",
            password="secret123",
            profile_image="shop_profiles/demo-store.jpg",
        )

        snapshot = get_store_monitoring_snapshot(base_url="https://api.example.com")

        self.assertEqual(len(snapshot["stores"]), 1)
        self.assertEqual(snapshot["stores"][0]["store_id"], shop.id)
        self.assertEqual(
            snapshot["stores"][0]["image_url"],
            "https://api.example.com/media/shop_profiles/demo-store.jpg",
        )
