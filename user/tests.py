import asyncio
from datetime import timedelta

from channels.db import database_sync_to_async
from channels.routing import ProtocolTypeRouter, URLRouter
from channels.testing import WebsocketCommunicator
from django.test import SimpleTestCase, TestCase, TransactionTestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken
from unittest.mock import patch

from mr_delivery.websocket_urls import websocket_urlpatterns
from shop.middleware import JWTAuthMiddleware
from user.authentication import notify_session_revoked, rotate_user_session
from user.models import (
    ADMIN_DESKTOP_FULL_ADMIN_ROLE,
    AdminApprovalRequest,
    AdminDesktopActivityLog,
    AdminDesktopUser,
    Employee,
    ShopCategory,
    ShopOwner,
    get_admin_desktop_role_permissions,
)
from shop.models import AbuseReport, AccountModerationStatus, ChatMessage, Customer, Driver, FCMDeviceToken, Notification, Order, ShopStatus
from user.views import (
    _admin_desktop_role_catalog,
    _can_manage_admin_desktop_users,
    _can_view_admin_desktop_users,
    _normalize_admin_desktop_permissions,
)


class AdminDesktopPermissionsTests(SimpleTestCase):
    def test_dashboard_manager_permissions_exclude_app_updates_and_include_admin_management(self):
        permissions = get_admin_desktop_role_permissions("dashboard_manager")
        self.assertIn("admin_management", permissions)
        self.assertIn("activity_logs", permissions)
        self.assertNotIn("app_updates", permissions)

    def test_store_supervisor_permissions_are_limited(self):
        self.assertEqual(
            get_admin_desktop_role_permissions("store_supervisor"),
            ["store_management", "approvals"],
        )

    def test_accounts_manager_permissions_are_limited(self):
        self.assertEqual(
            get_admin_desktop_role_permissions("accounts_manager"),
            ["dashboard", "reports", "invoices_payments"],
        )

    def test_technical_support_permissions_are_limited(self):
        self.assertEqual(
            get_admin_desktop_role_permissions("technical_support"),
            ["support_actions", "support_center", "abuse_reports"],
        )

    def test_normalize_permissions_caps_to_role_permissions(self):
        self.assertEqual(
            _normalize_admin_desktop_permissions(
                "technical_support",
                ["support_actions", "support_center", "app_updates", "dashboard", "abuse_reports"],
            ),
            ["support_actions", "support_center", "abuse_reports"],
        )

    def test_role_catalog_exposes_admin_user_capabilities(self):
        roles = {item["code"]: item for item in _admin_desktop_role_catalog()}
        self.assertTrue(roles["dashboard_manager"]["capabilities"]["can_view_admin_users"])
        self.assertFalse(roles["dashboard_manager"]["capabilities"]["can_manage_admin_users"])
        self.assertTrue(roles[ADMIN_DESKTOP_FULL_ADMIN_ROLE]["capabilities"]["can_manage_admin_users"])

    def test_admin_user_management_helpers(self):
        class DummyUser:
            def __init__(self, role, permissions):
                self.role = role
                self.permissions = permissions

        dashboard_manager = DummyUser("dashboard_manager", ["admin_management"])
        developer = DummyUser(ADMIN_DESKTOP_FULL_ADMIN_ROLE, ["admin_management"])
        support = DummyUser("technical_support", ["support_center"])

        self.assertTrue(_can_view_admin_desktop_users(dashboard_manager))
        self.assertFalse(_can_manage_admin_desktop_users(dashboard_manager))
        self.assertTrue(_can_manage_admin_desktop_users(developer))
        self.assertFalse(_can_view_admin_desktop_users(support))

    def test_existing_dashboard_manager_gets_updated_permissions(self):
        class DummyUser:
            role = "dashboard_manager"
            permissions = [
                "dashboard",
                "store_management",
                "approvals",
                "invoices_payments",
                "reports",
                "abuse_reports",
                "support_center",
                "notifications",
            ]

            def get_resolved_permissions(self):
                return get_admin_desktop_role_permissions(self.role)

        resolved = DummyUser().get_resolved_permissions()
        self.assertIn("admin_management", resolved)


class AdminDesktopStoreCategoriesEndpointTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.admin_user = AdminDesktopUser.objects.create(
            name="Store Supervisor",
            phone_number="+201000000001",
            email="stores@example.com",
            password="secret123",
            role="store_supervisor",
        )
        self.client.force_authenticate(user=self.admin_user)

    def test_store_supervisor_can_create_store_category(self):
        response = self.client.post(
            "/api/admin-desktop/stores/categories/",
            {"name": "مطعم"},
            format="json",
        )

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data["data"]["name"], "مطعم")
        self.assertTrue(ShopCategory.objects.filter(name="مطعم").exists())

    def test_store_category_name_is_required(self):
        response = self.client.post(
            "/api/admin-desktop/stores/categories/",
            {"name": "   "},
            format="json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("name", response.data["errors"])


class AdminDesktopApprovalsEndpointTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.admin_user = AdminDesktopUser.objects.create(
            name="Approvals Supervisor",
            phone_number="+201000000002",
            email="approvals@example.com",
            password="secret123",
            role="store_supervisor",
        )
        self.shop_owner = ShopOwner.objects.create(
            owner_name="Shop Owner",
            shop_name="مطعم الشام",
            shop_number="S1001",
            phone_number="+201000000099",
            password="secret123",
        )
        self.approval_request = AdminApprovalRequest.objects.create(
            shop_owner=self.shop_owner,
            request_type="shop_edit",
            payload={
                "owner_name": "Owner Updated",
                "shop_name": "مطعم الشام الجديد",
                "phone_number": "+201000000199",
                "description": "بيانات جديدة",
            },
        )
        self.client.force_authenticate(user=self.admin_user)

    def test_store_supervisor_can_list_approval_requests(self):
        response = self.client.get("/api/admin-desktop/approvals/requests/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data["data"]["requests"]), 1)
        self.assertEqual(response.data["data"]["requests"][0]["id"], self.approval_request.id)
        self.assertEqual(response.data["data"]["requests"][0]["request_type"], "shop_edit")
        self.assertEqual(response.data["data"]["requests"][0]["change_scope"], "shop_profile")
        self.assertIn("shop_name", response.data["data"]["requests"][0]["changed_fields"])

    def test_store_supervisor_can_approve_approval_request(self):
        response = self.client.post(
            f"/api/admin-desktop/approvals/requests/{self.approval_request.id}/approve/",
            {},
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        self.approval_request.refresh_from_db()
        self.shop_owner.refresh_from_db()
        self.assertEqual(self.approval_request.status, "approved")
        self.assertEqual(self.shop_owner.shop_name, "مطعم الشام الجديد")


class AdminDesktopStoreDeletionEndpointTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.admin_user = AdminDesktopUser.objects.create(
            name="Store Manager",
            phone_number="+201000000003",
            email="store-manager@example.com",
            password="secret123",
            role="store_supervisor",
        )
        self.shop_owner = ShopOwner.objects.create(
            owner_name="Delete Owner",
            shop_name="متجر للحذف",
            shop_number="S1002",
            phone_number="+201000000088",
            password="secret123",
        )
        self.client.force_authenticate(user=self.admin_user)

    def test_store_supervisor_can_delete_store(self):
        response = self.client.delete(f"/api/admin-desktop/stores/{self.shop_owner.id}/")

        self.assertEqual(response.status_code, 200)
        self.assertFalse(ShopOwner.objects.filter(id=self.shop_owner.id).exists())


class AbuseReportsFlowTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.admin_user = AdminDesktopUser.objects.create(
            name="Support Admin",
            phone_number="+201000000010",
            email="support@example.com",
            password="secret123",
            role="technical_support",
        )
        self.shop_owner = ShopOwner.objects.create(
            owner_name="Shop Owner",
            shop_name="سوبر المندي",
            shop_number="S5001",
            phone_number="+201000000020",
            password="secret123",
        )
        self.employee = Employee.objects.create(
            shop_owner=self.shop_owner,
            name="Shop Employee",
            phone_number="+201000000023",
            password="secret123",
            role="manager",
            is_active=True,
        )
        self.customer = Customer.objects.create(
            name="أحمد العميل",
            phone_number="+201000000021",
            password="secret123",
            is_verified=True,
        )
        self.driver = Driver.objects.create(
            name="كريم السائق",
            phone_number="+201000000022",
            password="secret123",
            is_verified=True,
            status="available",
        )
        self.order = Order.objects.create(
            shop_owner=self.shop_owner,
            customer=self.customer,
            driver=self.driver,
            order_number="ORD-5001",
            status="on_way",
            items='["وجبة"]',
            total_amount="120.00",
            delivery_fee="20.00",
            address="Nasr City",
            payment_method="cash",
        )

    def test_customer_can_create_abuse_report_against_driver(self):
        self.client.force_authenticate(user=self.customer)

        response = self.client.post(
            "/api/reports/",
            {
                "order_id": self.order.id,
                "target_type": "driver",
                "target_id": self.driver.id,
                "reason": "delay",
                "details": "تأخير أكتر من المتوقع",
            },
            format="json",
        )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(AbuseReport.objects.count(), 1)
        report = AbuseReport.objects.first()
        self.assertEqual(report.reporter_customer, self.customer)
        self.assertEqual(report.target_driver, self.driver)
        self.assertEqual(response.data["data"], {})

    def test_three_warnings_suspend_target_account(self):
        report = AbuseReport.objects.create(
            order=self.order,
            reporter_customer=self.customer,
            reporter_type="customer",
            target_driver=self.driver,
            target_type="driver",
            reason="abusive_language",
            details="test",
        )
        moderation = AccountModerationStatus.objects.create(
            driver=self.driver,
            warnings_count=2,
        )

        self.client.force_authenticate(user=self.admin_user)
        response = self.client.post(
            f"/api/admin-desktop/abuse-reports/{report.id}/resolve/",
            {
                "action": "warning",
                "admin_notes": "آخر تحذير",
            },
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        moderation.refresh_from_db()
        report.refresh_from_db()
        self.assertEqual(moderation.warnings_count, 3)
        self.assertTrue(moderation.is_suspended)
        self.assertEqual(report.status, "closed")
        self.assertEqual(report.resolution_action, "warning")
        self.assertTrue(response.data["data"]["auto_suspended"])

    def test_shop_reporter_gets_notification_when_admin_warns_customer(self):
        report = AbuseReport.objects.create(
            order=self.order,
            reporter_shop_owner=self.shop_owner,
            reporter_type="shop_owner",
            target_customer=self.customer,
            target_type="customer",
            reason="abusive_language",
            details="customer insulted staff",
        )

        self.client.force_authenticate(user=self.admin_user)
        response = self.client.post(
            f"/api/admin-desktop/abuse-reports/{report.id}/resolve/",
            {
                "action": "warning",
                "admin_notes": "first warning",
            },
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        owner_notification = Notification.objects.filter(
            shop_owner=self.shop_owner,
            reference_id=report.public_id,
        ).order_by("-created_at").first()
        employee_notification = Notification.objects.filter(
            employee=self.employee,
            reference_id=report.public_id,
        ).order_by("-created_at").first()

        self.assertIsNotNone(owner_notification)
        self.assertIsNotNone(employee_notification)
        self.assertEqual(owner_notification.data["action"], "warning")
        self.assertEqual(owner_notification.data["target_type"], "customer")
        self.assertEqual(owner_notification.data["warnings_count"], 1)
        self.assertIn("الدعم الفني", owner_notification.title)
        self.assertIn(report.public_id, owner_notification.message)


class AdminDesktopDashboardPendingActionsTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.admin_user = AdminDesktopUser.objects.create(
            name="Dashboard Admin",
            phone_number="+201000000030",
            email="dashboard@example.com",
            password="secret123",
            role="dashboard_manager",
        )
        self.shop_owner = ShopOwner.objects.create(
            owner_name="Pending Shop Owner",
            shop_name="متجر المتابعة",
            shop_number="S7001",
            phone_number="+201000000031",
            password="secret123",
        )
        self.customer = Customer.objects.create(
            shop_owner=self.shop_owner,
            name="عميل متابعة",
            phone_number="+201000000032",
            password="secret123",
            is_verified=True,
        )
        self.order = Order.objects.create(
            shop_owner=self.shop_owner,
            customer=self.customer,
            order_number="ORD-PENDING-1",
            status="confirmed",
            items='["وجبة"]',
            total_amount="50.00",
            delivery_fee="10.00",
            address="Nasr City",
            payment_method="cash",
        )
        AbuseReport.objects.create(
            order=self.order,
            reporter_shop_owner=self.shop_owner,
            reporter_type="shop_owner",
            target_customer=self.customer,
            target_type="customer",
            reason="abusive_language",
            details="pending review",
            status="pending_review",
        )
        self.client.force_authenticate(user=self.admin_user)

    def test_pending_actions_endpoint_returns_grouped_company_and_support_items(self):
        response = self.client.get("/api/admin-desktop/dashboard/pending-actions/")

        self.assertEqual(response.status_code, 200)
        groups = {item["key"]: item for item in response.data["data"]["pending_action_groups"]}
        self.assertIn("company", groups)
        self.assertIn("support_reports", groups)

        actions = {item["key"]: item for item in response.data["data"]["pending_actions"]}
        self.assertIn("non_invoiced_orders", actions)
        self.assertIn("abuse_reports_pending", actions)
        self.assertEqual(actions["non_invoiced_orders"]["category_key"], "orders")
        self.assertEqual(actions["abuse_reports_pending"]["category_key"], "support_reports")


class GoogleCustomerAuthTests(TestCase):
    def setUp(self):
        super().setUp()
        self.client = APIClient()

    @patch("user.views._verify_google_identity_token")
    def test_existing_customer_can_login_via_google(self, mock_verify):
        customer = Customer.objects.create(
            name="Existing Customer",
            email="existing@example.com",
            phone_number="+201011111111",
            password="secret123",
            is_verified=True,
        )
        mock_verify.return_value = {
            "email": "existing@example.com",
            "email_verified": True,
            "name": "Existing Customer Updated",
            "picture": "https://example.com/pic.jpg",
        }

        response = self.client.post(
            "/api/auth/google/",
            {
                "idToken": "mock-google-token",
                "email": "existing@example.com",
                "name": "Existing Customer Updated",
            },
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["data"]["role"], "customer")
        self.assertIn("access", response.data["data"])
        self.assertEqual(
            response.data["data"]["user"]["profile_image_url"],
            "https://example.com/pic.jpg",
        )
        customer.refresh_from_db()
        self.assertEqual(customer.name, "Existing Customer Updated")
        self.assertEqual(customer.google_profile_image_url, "https://example.com/pic.jpg")

    @patch("user.views._verify_google_identity_token")
    def test_new_google_user_without_phone_gets_completion_payload(self, mock_verify):
        mock_verify.return_value = {
            "email": "new@example.com",
            "email_verified": True,
            "name": "New Customer",
            "picture": "https://example.com/pic.jpg",
        }

        response = self.client.post(
            "/api/auth/google/",
            {
                "idToken": "mock-google-token",
                "email": "new@example.com",
                "name": "New Customer",
                "photoUrl": "https://example.com/pic.jpg",
            },
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.data["data"]["registration_completed"])
        self.assertTrue(response.data["data"]["requires_phone_number"])
        self.assertEqual(response.data["data"]["google_user"]["email"], "new@example.com")

    @patch("user.views._verify_google_identity_token")
    def test_new_google_user_with_phone_creates_customer(self, mock_verify):
        mock_verify.return_value = {
            "email": "signup@example.com",
            "email_verified": True,
            "name": "Signup Customer",
            "picture": "",
        }

        response = self.client.post(
            "/api/auth/google/",
            {
                "idToken": "mock-google-token",
                "email": "signup@example.com",
                "name": "Signup Customer",
                "phone_number": "01012345678",
            },
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data["data"]["registration_completed"])
        self.assertEqual(response.data["data"]["role"], "customer")
        created_customer = Customer.objects.get(email="signup@example.com")
        self.assertEqual(created_customer.phone_number, "+201012345678")
        self.assertTrue(created_customer.is_verified)

    @patch("user.views._verify_google_identity_token")
    def test_new_google_user_with_phone_returns_google_profile_image_url(self, mock_verify):
        mock_verify.return_value = {
            "email": "signup2@example.com",
            "email_verified": True,
            "name": "Signup Customer 2",
            "picture": "https://lh3.googleusercontent.com/signup2-photo",
        }

        response = self.client.post(
            "/api/auth/google/",
            {
                "idToken": "mock-google-token",
                "email": "signup2@example.com",
                "name": "Signup Customer 2",
                "phone_number": "01012345679",
            },
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.data["data"]["user"]["profile_image_url"],
            "https://lh3.googleusercontent.com/signup2-photo",
        )
        created_customer = Customer.objects.get(email="signup2@example.com")
        self.assertEqual(
            created_customer.google_profile_image_url,
            "https://lh3.googleusercontent.com/signup2-photo",
        )


class CustomerAuthFcmRegistrationTests(TestCase):
    def setUp(self):
        super().setUp()
        self.client = APIClient()

    def test_email_password_customer_login_registers_fcm_device_when_payload_present(self):
        customer = Customer.objects.create(
            name="Email Customer",
            email="email@example.com",
            phone_number="+201055555555",
            password="",
            is_verified=True,
        )
        customer.set_password("secret123")
        customer.save(update_fields=["password", "updated_at"])

        response = self.client.post(
            "/api/auth/login/",
            {
                "role": "customer",
                "email": "email@example.com",
                "password": "secret123",
                "fcm_token": "customer-token-1",
                "device_id": "customer-device-1",
                "platform": "android",
            },
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["data"]["role"], "customer")
        self.assertEqual(response.data["data"]["fcm_device"]["device_id"], "customer-device-1")
        token = FCMDeviceToken.objects.get(user_type="customer", user_id=customer.id, device_id="customer-device-1")
        self.assertEqual(token.fcm_token, "customer-token-1")
        self.assertTrue(token.is_active)


class SupportActionsEndpointsTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.admin_user = AdminDesktopUser.objects.create(
            name="Support Actions Admin",
            phone_number="+201000000030",
            email="support-actions@example.com",
            password="secret123",
            role="technical_support",
        )
        self.customer = Customer.objects.create(
            name="عميل الدعم",
            phone_number="+201000000031",
            password="secret123",
            is_verified=True,
        )
        self.driver = Driver.objects.create(
            name="دليفري الدعم",
            phone_number="+201000000032",
            password="secret123",
            is_verified=True,
            status="available",
        )
        self.shop_owner = ShopOwner.objects.create(
            owner_name="صاحب المتجر",
            shop_name="متجر الدعم",
            shop_number="S7001",
            phone_number="+201000000033",
            password="secret123",
        )
        self.client.force_authenticate(user=self.admin_user)

    def test_support_actions_list_returns_tab_metadata(self):
        response = self.client.get("/api/admin-desktop/support-actions/accounts/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["data"]["tab"]["key"], "support-actions")
        self.assertEqual(response.data["data"]["tab"]["label"], "إدارة الحسابات")
        self.assertGreaterEqual(len(response.data["data"]["accounts"]), 3)

    def test_support_admin_can_suspend_and_activate_driver(self):
        suspend_response = self.client.post(
            f"/api/admin-desktop/support-actions/accounts/driver/{self.driver.id}/action/",
            {
                "action": "suspend",
                "admin_notes": "مراجعة من الدعم الفني",
            },
            format="json",
        )

        self.assertEqual(suspend_response.status_code, 200)
        moderation = AccountModerationStatus.objects.get(driver=self.driver)
        self.assertTrue(moderation.is_suspended)
        self.assertEqual(suspend_response.data["data"]["action"], "suspend")
        self.assertEqual(suspend_response.data["data"]["account"]["status"], "suspended")

        activate_response = self.client.post(
            f"/api/admin-desktop/support-actions/accounts/driver/{self.driver.id}/action/",
            {
                "action": "activate",
                "admin_notes": "تمت المراجعة",
            },
            format="json",
        )

        self.assertEqual(activate_response.status_code, 200)
        moderation.refresh_from_db()
        self.assertFalse(moderation.is_suspended)
        self.assertEqual(activate_response.data["data"]["action"], "activate")
        self.assertEqual(activate_response.data["data"]["account"]["status"], "active")


class AdminDesktopActivityLogsTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.dashboard_manager = AdminDesktopUser.objects.create(
            name="Dashboard Manager",
            phone_number="+201000000040",
            email="dashboard-manager@example.com",
            password="secret123",
            role="dashboard_manager",
        )
        self.support_user = AdminDesktopUser.objects.create(
            name="Support User",
            phone_number="+201000000041",
            email="support-user@example.com",
            password="secret123",
            role="technical_support",
        )
        AdminDesktopActivityLog.objects.create(
            actor=self.dashboard_manager,
            actor_name=self.dashboard_manager.name,
            actor_role=self.dashboard_manager.role,
            section_key="support_actions",
            section_label="إدارة الحسابات",
            action_key="suspend",
            action_label="تعليق",
            action_category="suspension_actions",
            target_name="حساب تجريبي",
            details="تم تعليق حساب تجريبي",
        )

    def test_dashboard_manager_can_list_activity_logs(self):
        self.client.force_authenticate(user=self.dashboard_manager)
        response = self.client.get("/api/admin-desktop/activity-logs/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["data"]["tab"]["key"], "activity-logs")
        self.assertEqual(response.data["data"]["tab"]["label"], "سجل النشاطات")
        self.assertEqual(len(response.data["data"]["logs"]), 1)

    def test_technical_support_cannot_access_activity_logs(self):
        self.client.force_authenticate(user=self.support_user)
        response = self.client.get("/api/admin-desktop/activity-logs/")

        self.assertEqual(response.status_code, 403)


class LoginOptionalTrailingSlashTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.admin_user = AdminDesktopUser.objects.create(
            name="Admin Login User",
            phone_number="+201000000051",
            email="admin-login@example.com",
            password="secret123",
            role="dashboard_manager",
        )
        self.customer = Customer.objects.create(
            name="Customer Login User",
            phone_number="+201000000052",
            email="customer-login@example.com",
            password="secret123",
            is_verified=True,
        )
        self.driver = Driver.objects.create(
            name="Driver Login User",
            phone_number="+201000000053",
            password="secret123",
            is_verified=True,
            status="available",
        )
        self.shop_owner = ShopOwner.objects.create(
            owner_name="Shop Owner Login User",
            shop_name="Login Test Shop",
            shop_number="S9051",
            phone_number="+201000000054",
            password="secret123",
        )

    def test_unified_login_without_trailing_slash_does_not_redirect(self):
        response = self.client.post(
            "/api/auth/login",
            {
                "role": "shop_owner",
                "shop_number": self.shop_owner.shop_number,
                "password": "secret123",
            },
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn("access", response.data["data"])

    def test_suspended_shop_owner_login_returns_clear_company_suspension_message(self):
        self.shop_owner.admin_status = "suspended"
        self.shop_owner.suspension_reason = "مخالفة سياسة الاستخدام"
        self.shop_owner.save(update_fields=["admin_status", "suspension_reason", "updated_at"])

        response = self.client.post(
            "/api/auth/login",
            {
                "role": "shop_owner",
                "shop_number": self.shop_owner.shop_number,
                "password": "secret123",
            },
            format="json",
        )

        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.data["errors"]["code"], "SHOP_OWNER_ACCOUNT_SUSPENDED")
        self.assertEqual(response.data["errors"]["title"], "الحساب موقوف")
        self.assertEqual(response.data["errors"]["reason"], "مخالفة سياسة الاستخدام")
        self.assertIn("تم تعليق حسابك من قبل الشركة", response.data["message"])
        self.assertIn("سبب التعليق", response.data["message"])

    def test_customer_login_without_trailing_slash_does_not_redirect(self):
        response = self.client.post(
            "/api/customer/login",
            {
                "phone_number": self.customer.phone_number,
                "password": "secret123",
            },
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn("access", response.data["data"])

    def test_driver_login_without_trailing_slash_does_not_redirect(self):
        response = self.client.post(
            "/api/driver/login",
            {
                "phone_number": self.driver.phone_number,
                "password": "secret123",
            },
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn("access", response.data["data"])

    def test_admin_desktop_login_without_trailing_slash_does_not_redirect(self):
        response = self.client.post(
            "/api/admin-desktop/auth/login",
            {
                "phone_number": self.admin_user.phone_number,
                "password": "secret123",
            },
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn("access", response.data["data"])

    def test_admin_desktop_old_access_token_is_rejected_after_second_login(self):
        first_login = self.client.post(
            "/api/admin-desktop/auth/login",
            {
                "phone_number": self.admin_user.phone_number,
                "password": "secret123",
            },
            format="json",
        )
        self.assertEqual(first_login.status_code, 200)
        first_access = first_login.data["data"]["access"]

        second_login = self.client.post(
            "/api/admin-desktop/auth/login",
            {
                "phone_number": self.admin_user.phone_number,
                "password": "secret123",
            },
            format="json",
        )
        self.assertEqual(second_login.status_code, 200)

        old_session_client = APIClient()
        old_session_client.credentials(HTTP_AUTHORIZATION=f"Bearer {first_access}")
        me_response = old_session_client.get("/api/admin-desktop/auth/me/")

        self.assertEqual(me_response.status_code, 401)

    def test_admin_desktop_old_refresh_token_is_rejected_after_second_login(self):
        first_login = self.client.post(
            "/api/admin-desktop/auth/login",
            {
                "phone_number": self.admin_user.phone_number,
                "password": "secret123",
            },
            format="json",
        )
        self.assertEqual(first_login.status_code, 200)
        first_refresh = first_login.data["data"]["refresh"]

        second_login = self.client.post(
            "/api/admin-desktop/auth/login",
            {
                "phone_number": self.admin_user.phone_number,
                "password": "secret123",
            },
            format="json",
        )
        self.assertEqual(second_login.status_code, 200)

        refresh_response = self.client.post(
            "/api/admin-desktop/auth/token/refresh/",
            {
                "refresh": first_refresh,
            },
            format="json",
        )

        self.assertEqual(refresh_response.status_code, 400)


class AdminDesktopStoreMonitoringEndpointTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.admin_user = AdminDesktopUser.objects.create(
            name="Monitor Admin",
            phone_number="+201000000061",
            email="monitor@example.com",
            password="secret123",
            role="store_supervisor",
        )
        self.client.force_authenticate(user=self.admin_user)

        self.shop_one = ShopOwner.objects.create(
            owner_name="Owner One",
            shop_name="Store One",
            shop_number="SM-1001",
            phone_number="+201000000062",
            password="secret123",
        )
        self.shop_two = ShopOwner.objects.create(
            owner_name="Owner Two",
            shop_name="Store Two",
            shop_number="SM-1002",
            phone_number="+201000000063",
            password="secret123",
        )
        ShopStatus.objects.create(shop_owner=self.shop_one, status="open")
        ShopStatus.objects.create(shop_owner=self.shop_two, status="closed")

        self.customer = Customer.objects.create(
            name="Monitoring Customer",
            phone_number="+201000000064",
            email="monitor.customer@example.com",
        )

        now = timezone.now()
        self.order_one = Order.objects.create(
            shop_owner=self.shop_one,
            customer=self.customer,
            order_number="MON-1",
            status="new",
            items="[]",
            total_amount=100,
            delivery_fee=10,
            address="Address 1",
        )
        self.order_two = Order.objects.create(
            shop_owner=self.shop_one,
            customer=self.customer,
            order_number="MON-2",
            status="confirmed",
            items="[]",
            total_amount=120,
            delivery_fee=12,
            address="Address 2",
        )
        self.order_three = Order.objects.create(
            shop_owner=self.shop_two,
            customer=self.customer,
            order_number="MON-3",
            status="confirmed",
            items="[]",
            total_amount=130,
            delivery_fee=13,
            address="Address 3",
        )

        Order.objects.filter(id=self.order_one.id).update(
            created_at=now - timedelta(hours=3),
            updated_at=now - timedelta(minutes=40),
        )
        Order.objects.filter(id=self.order_two.id).update(
            created_at=now - timedelta(hours=2),
            updated_at=now - timedelta(minutes=5),
        )
        Order.objects.filter(id=self.order_three.id).update(
            created_at=now - timedelta(hours=4),
            updated_at=now - timedelta(hours=1),
        )

        msg_1 = ChatMessage.objects.create(
            order=self.order_one,
            chat_type="shop_customer",
            sender_type="customer",
            sender_customer=self.customer,
            message_type="text",
            content="Need help 1",
        )
        msg_2 = ChatMessage.objects.create(
            order=self.order_one,
            chat_type="shop_customer",
            sender_type="customer",
            sender_customer=self.customer,
            message_type="text",
            content="Need help 2",
        )
        msg_3 = ChatMessage.objects.create(
            order=self.order_two,
            chat_type="shop_customer",
            sender_type="customer",
            sender_customer=self.customer,
            message_type="text",
            content="Need help 3",
        )
        msg_4 = ChatMessage.objects.create(
            order=self.order_two,
            chat_type="shop_customer",
            sender_type="shop_owner",
            sender_shop_owner=self.shop_one,
            message_type="text",
            content="Reply",
        )
        msg_5 = ChatMessage.objects.create(
            order=self.order_two,
            chat_type="shop_customer",
            sender_type="customer",
            sender_customer=self.customer,
            message_type="text",
            content="Need help again",
        )
        msg_6 = ChatMessage.objects.create(
            order=self.order_three,
            chat_type="shop_customer",
            sender_type="customer",
            sender_customer=self.customer,
            message_type="text",
            content="Resolved soon?",
        )
        msg_7 = ChatMessage.objects.create(
            order=self.order_three,
            chat_type="shop_customer",
            sender_type="shop_owner",
            sender_shop_owner=self.shop_two,
            message_type="text",
            content="Resolved",
        )

        ChatMessage.objects.filter(id=msg_1.id).update(created_at=now - timedelta(hours=2, minutes=30))
        ChatMessage.objects.filter(id=msg_2.id).update(created_at=now - timedelta(hours=2))
        ChatMessage.objects.filter(id=msg_3.id).update(created_at=now - timedelta(hours=1, minutes=30))
        ChatMessage.objects.filter(id=msg_4.id).update(created_at=now - timedelta(hours=1, minutes=20))
        ChatMessage.objects.filter(id=msg_5.id).update(created_at=now - timedelta(minutes=50))
        ChatMessage.objects.filter(id=msg_6.id).update(created_at=now - timedelta(hours=3, minutes=30))
        ChatMessage.objects.filter(id=msg_7.id).update(created_at=now - timedelta(hours=3, minutes=20))

        ShopStatus.objects.filter(shop_owner=self.shop_one).update(updated_at=now - timedelta(minutes=10))
        ShopStatus.objects.filter(shop_owner=self.shop_two).update(updated_at=now - timedelta(hours=2))

    def test_store_monitoring_endpoint_returns_expected_snapshot(self):
        response = self.client.get("/api/admin-desktop/store-monitoring/")

        self.assertEqual(response.status_code, 200)
        stores = response.data["data"]["stores"]
        self.assertEqual(len(stores), 2)

        first_store = stores[0]
        self.assertEqual(first_store["store_id"], self.shop_one.id)
        self.assertEqual(first_store["store_name"], "Store One")
        self.assertEqual(first_store["owner_name"], "Owner One")
        self.assertEqual(first_store["phone"], self.shop_one.phone_number)
        self.assertTrue(first_store["is_online"])
        self.assertEqual(first_store["unanswered_messages"], 3)
        self.assertEqual(first_store["unanswered_orders"], 1)
        self.assertEqual(first_store["total_pending"], 4)
        self.assertIsNotNone(first_store["oldest_pending_at"])
        self.assertIsNotNone(first_store["last_activity_at"])

        second_store = next(item for item in stores if item["store_id"] == self.shop_two.id)
        self.assertFalse(second_store["is_online"])
        self.assertEqual(second_store["unanswered_messages"], 0)
        self.assertEqual(second_store["unanswered_orders"], 0)
        self.assertEqual(second_store["total_pending"], 0)
        self.assertIsNone(second_store["oldest_pending_at"])


@override_settings(
    CHANNEL_LAYERS={"default": {"BACKEND": "channels.layers.InMemoryChannelLayer"}},
    ALLOWED_HOSTS=["testserver", "localhost", "127.0.0.1"],
)
class AdminDesktopStoreMonitoringWebSocketTests(TransactionTestCase):
    reset_sequences = True

    def setUp(self):
        super().setUp()
        self.application = ProtocolTypeRouter(
            {
                "websocket": JWTAuthMiddleware(URLRouter(websocket_urlpatterns)),
            }
        )
        self.admin_user = AdminDesktopUser.objects.create(
            name="WS Monitor Admin",
            phone_number="+201000000071",
            password="secret123",
            role="store_supervisor",
        )
        self.shop = ShopOwner.objects.create(
            owner_name="WS Owner",
            shop_name="WS Store",
            shop_number="SM-WS-1",
            phone_number="+201000000072",
            password="secret123",
        )

    def _admin_token(self):
        if not self.admin_user.active_session_key:
            rotate_user_session(self.admin_user)
            self.admin_user.save(update_fields=["active_session_key"])
        refresh = RefreshToken()
        refresh["admin_desktop_user_id"] = self.admin_user.id
        refresh["permissions"] = self.admin_user.get_resolved_permissions()
        refresh["user_type"] = "admin_desktop"
        refresh["session_key"] = self.admin_user.active_session_key
        return str(refresh.access_token)

    def test_store_monitor_sync_returns_snapshot(self):
        async def scenario():
            communicator = WebsocketCommunicator(
                self.application,
                f"/ws/admin-desktop/store-monitoring/?token={self._admin_token()}&lang=ar",
            )
            connected, _ = await communicator.connect()
            self.assertTrue(connected)

            await communicator.send_json_to(
                {
                    "action": "store_monitor.sync",
                    "request_id": "req-sync-1",
                }
            )
            payload = await communicator.receive_json_from()
            self.assertEqual(payload["type"], "store_monitor.snapshot")
            self.assertEqual(payload["request_id"], "req-sync-1")
            self.assertIn("stores", payload["data"])
            await communicator.disconnect()

        asyncio.run(scenario())

    def test_store_update_event_is_broadcast_when_status_changes(self):
        def create_status():
            ShopStatus.objects.create(shop_owner=self.shop, status="open")

        async def scenario():
            communicator = WebsocketCommunicator(
                self.application,
                f"/ws/admin-desktop/store-monitoring/?token={self._admin_token()}&lang=ar",
            )
            connected, _ = await communicator.connect()
            self.assertTrue(connected)

            await communicator.send_json_to(
                {
                    "action": "store_monitor.sync",
                    "request_id": "req-sync-2",
                }
            )
            initial_snapshot = await communicator.receive_json_from()
            self.assertEqual(initial_snapshot["type"], "store_monitor.snapshot")

            await database_sync_to_async(create_status)()
            update_event = await communicator.receive_json_from()
            self.assertEqual(update_event["type"], "store_monitor.store_updated")
            self.assertEqual(update_event["data"]["store"]["store_id"], self.shop.id)
            self.assertTrue(update_event["data"]["store"]["is_online"])
            await communicator.disconnect()

        asyncio.run(scenario())

    def test_existing_store_monitor_socket_is_revoked_after_new_session(self):
        def rotate_session_and_notify():
            self.admin_user.refresh_from_db()
            rotate_user_session(self.admin_user)
            self.admin_user.save(update_fields=["active_session_key"])
            notify_session_revoked(self.admin_user, "admin_desktop")

        async def scenario():
            communicator = WebsocketCommunicator(
                self.application,
                f"/ws/admin-desktop/store-monitoring/?token={self._admin_token()}&lang=ar",
            )
            connected, _ = await communicator.connect()
            self.assertTrue(connected)

            await database_sync_to_async(rotate_session_and_notify)()
            payload = await communicator.receive_json_from()
            self.assertEqual(payload["type"], "auth.session_revoked")

        asyncio.run(scenario())
