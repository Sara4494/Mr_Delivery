from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from shop.models import Customer, Driver, Notification, Order
from shop.views import (
    _attach_notification_to_shop_users,
    _notify_shop_about_driver_order_action,
)
from user.models import Employee, ShopCategory, ShopOwner


class NotificationsApiTests(TestCase):
    def setUp(self):
        super().setUp()
        self.client = APIClient()
        self.customer = Customer.objects.create(
            name="Notification Customer",
            phone_number="+201099990001",
            password="secret123",
            is_verified=True,
        )
        self.other_customer = Customer.objects.create(
            name="Other Customer",
            phone_number="+201099990002",
            password="secret123",
            is_verified=True,
        )

        Notification.objects.create(
            customer=self.customer,
            notification_type="system",
            title="System",
            message="Visible notification",
            reference_id="order-1",
        )
        Notification.objects.create(
            customer=self.customer,
            notification_type="chat_message",
            title="Chat",
            message="Hidden chat notification",
            reference_id="chat-1",
        )
        Notification.objects.create(
            customer=self.other_customer,
            notification_type="system",
            title="Other",
            message="Other customer notification",
        )

        self.client.force_authenticate(user=self.customer)

    def test_list_excludes_chat_notifications_and_returns_pagination(self):
        response = self.client.get("/api/notifications/", {"page": 1, "limit": 20})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data["data"]["notifications"]), 1)
        row = response.data["data"]["notifications"][0]
        self.assertEqual(row["type"], "system")
        self.assertEqual(row["body"], "Visible notification")
        self.assertEqual(row["reference_id"], "order-1")
        self.assertEqual(response.data["data"]["pagination"]["page"], 1)
        self.assertEqual(response.data["data"]["pagination"]["limit"], 20)
        self.assertFalse(response.data["data"]["pagination"]["has_more"])

    def test_mark_read_only_updates_owned_notification(self):
        notification = Notification.objects.filter(customer=self.customer, notification_type="system").first()
        response = self.client.patch(f"/api/notifications/{notification.id}/read/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["data"]["id"], notification.id)
        self.assertTrue(response.data["data"]["is_read"])
        notification.refresh_from_db()
        self.assertTrue(notification.is_read)

    def test_mark_read_rejects_foreign_notification(self):
        foreign = Notification.objects.filter(customer=self.other_customer).first()
        response = self.client.patch(f"/api/notifications/{foreign.id}/read/")

        self.assertEqual(response.status_code, 404)

    def test_mark_all_read_skips_chat_notifications(self):
        response = self.client.patch("/api/notifications/read-all/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["data"]["unread_count"], 0)
        visible = Notification.objects.get(customer=self.customer, notification_type="system")
        hidden_chat = Notification.objects.get(customer=self.customer, notification_type="chat_message")
        self.assertTrue(visible.is_read)
        self.assertFalse(hidden_chat.is_read)

    def test_delete_notification_only_for_owner(self):
        notification = Notification.objects.filter(customer=self.customer, notification_type="system").first()
        response = self.client.delete(f"/api/notifications/{notification.id}/")

        self.assertEqual(response.status_code, 200)
        self.assertFalse(Notification.objects.filter(id=notification.id).exists())

    def test_delete_notification_rejects_foreign_notification(self):
        foreign = Notification.objects.filter(customer=self.other_customer).first()
        response = self.client.delete(f"/api/notifications/{foreign.id}/")

        self.assertEqual(response.status_code, 404)

    def test_delete_all_notifications_only_clears_current_users_inbox(self):
        response = self.client.delete("/api/notifications/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["message"], "All notifications deleted successfully")
        self.assertFalse(
            Notification.objects.filter(customer=self.customer, notification_type="system").exists()
        )
        self.assertTrue(
            Notification.objects.filter(customer=self.customer, notification_type="chat_message").exists()
        )
        self.assertTrue(Notification.objects.filter(customer=self.other_customer).exists())


class DriverNotificationsApiTests(TestCase):
    def setUp(self):
        super().setUp()
        self.client = APIClient()
        self.driver = Driver.objects.create(
            name="Driver Notification",
            phone_number="+201099991001",
            password="secret123",
            is_verified=True,
        )
        self.other_driver = Driver.objects.create(
            name="Other Driver",
            phone_number="+201099991002",
            password="secret123",
            is_verified=True,
        )

        Notification.objects.create(
            driver=self.driver,
            notification_type="general_notification",
            title="Important",
            message="Message from admin",
            data={"screen": "notifications"},
        )
        Notification.objects.create(
            driver=self.driver,
            notification_type="system",
            title="System",
            message="System notice",
            data={"screen": "notifications"},
        )
        Notification.objects.create(
            driver=self.other_driver,
            notification_type="general_notification",
            title="Foreign",
            message="Other driver notification",
        )

        self.client.force_authenticate(user=self.driver)

    def test_driver_list_returns_only_current_driver_system_notifications(self):
        response = self.client.get("/api/notifications/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["data"]["unread_count"], 2)
        self.assertEqual(len(response.data["data"]["notifications"]), 2)
        row = response.data["data"]["notifications"][0]
        self.assertIn(row["type"], {"general_notification", "system"})
        self.assertIn("title", row)
        self.assertIn("message", row)
        self.assertIn("data", row)

    def test_driver_mark_read_accepts_post(self):
        notification = Notification.objects.filter(driver=self.driver, notification_type="general_notification").first()
        response = self.client.post(f"/api/notifications/{notification.id}/read/")

        self.assertEqual(response.status_code, 200)
        notification.refresh_from_db()
        self.assertTrue(notification.is_read)

    def test_driver_mark_all_read_accepts_post(self):
        response = self.client.post("/api/notifications/read-all/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["data"]["unread_count"], 0)
        self.assertFalse(Notification.objects.filter(driver=self.driver, is_read=False).exists())


class ShopNotificationsApiTests(TestCase):
    def setUp(self):
        super().setUp()
        self.client = APIClient()
        self.category = ShopCategory.objects.create(name="Groceries")
        self.shop = ShopOwner.objects.create(
            owner_name="Shop Owner",
            shop_name="Notification Store",
            shop_number="SHOP-NOTIFY-001",
            phone_number="01010019991",
            password="secret123",
            shop_category=self.category,
        )
        self.employee = Employee.objects.create(
            shop_owner=self.shop,
            name="Store Employee",
            phone_number="01010019992",
            password="secret123",
            role="manager",
            is_active=True,
        )
        self.customer = Customer.objects.create(
            shop_owner=self.shop,
            name="Store Customer",
            phone_number="01010019993",
            password="secret123",
            is_verified=True,
        )
        self.driver = Driver.objects.create(
            name="Store Driver",
            phone_number="01010019994",
            password="secret123",
            is_verified=True,
        )
        self.order = Order.objects.create(
            shop_owner=self.shop,
            customer=self.customer,
            driver=self.driver,
            order_number="ON000001",
            status="confirmed",
            items='["meal"]',
            total_amount="120.00",
            delivery_fee="15.00",
            address="Tahrir Street",
            notes="",
            driver_assigned_at=timezone.now(),
        )

    def test_shop_notification_helper_creates_inbox_rows_for_owner_and_employee(self):
        _attach_notification_to_shop_users(
            self.shop,
            notification_type="order_update",
            title="New order",
            message="A new order was created.",
            reference_id=self.order.id,
            idempotency_key=f"shop-order-created:{self.order.id}",
            data={"event": "order_created", "order_id": self.order.id},
        )

        self.assertEqual(Notification.objects.filter(shop_owner=self.shop).count(), 1)
        self.assertEqual(Notification.objects.filter(employee=self.employee).count(), 1)

        self.client.force_authenticate(user=self.employee)
        response = self.client.get("/api/notifications/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data["data"]["notifications"]), 1)
        self.assertEqual(response.data["data"]["notifications"][0]["type"], "order_update")

    def test_shop_notifications_keep_separate_events_for_same_order(self):
        _attach_notification_to_shop_users(
            self.shop,
            notification_type="order_status",
            title="Driver accepted",
            message="Driver accepted the order.",
            reference_id=self.order.id,
            idempotency_key=f"driver-accepted:{self.order.id}",
            data={"event": "driver_accepted_order", "order_id": self.order.id},
        )
        _attach_notification_to_shop_users(
            self.shop,
            notification_type="order_status",
            title="Driver delivered",
            message="Driver delivered the order.",
            reference_id=self.order.id,
            idempotency_key=f"driver-delivered:{self.order.id}",
            data={"event": "driver_delivered_order", "order_id": self.order.id},
        )

        self.assertEqual(Notification.objects.filter(shop_owner=self.shop).count(), 2)
        self.assertEqual(Notification.objects.filter(employee=self.employee).count(), 2)

    def test_driver_action_notification_reaches_employee_inbox(self):
        _notify_shop_about_driver_order_action(self.order, self.driver, "accepted")

        self.client.force_authenticate(user=self.employee)
        response = self.client.get("/api/notifications/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["data"]["unread_count"], 1)
        self.assertEqual(len(response.data["data"]["notifications"]), 1)
        row = response.data["data"]["notifications"][0]
        self.assertEqual(row["type"], "order_status")
        self.assertEqual(row["reference_id"], str(self.order.id))
