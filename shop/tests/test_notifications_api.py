from django.test import TestCase
from rest_framework.test import APIClient

from shop.models import Customer, Notification


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
        notification.refresh_from_db()
        self.assertTrue(notification.is_read)

    def test_mark_read_rejects_foreign_notification(self):
        foreign = Notification.objects.filter(customer=self.other_customer).first()
        response = self.client.patch(f"/api/notifications/{foreign.id}/read/")

        self.assertEqual(response.status_code, 404)

    def test_mark_all_read_skips_chat_notifications(self):
        response = self.client.patch("/api/notifications/read-all/")

        self.assertEqual(response.status_code, 200)
        visible = Notification.objects.get(customer=self.customer, notification_type="system")
        hidden_chat = Notification.objects.get(customer=self.customer, notification_type="chat_message")
        self.assertTrue(visible.is_read)
        self.assertFalse(hidden_chat.is_read)

    def test_delete_notification_only_for_owner(self):
        notification = Notification.objects.filter(customer=self.customer, notification_type="system").first()
        response = self.client.delete(f"/api/notifications/{notification.id}/")

        self.assertEqual(response.status_code, 200)
        self.assertFalse(Notification.objects.filter(id=notification.id).exists())
