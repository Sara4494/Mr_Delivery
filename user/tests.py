from django.test import SimpleTestCase, TestCase
from rest_framework.test import APIClient
from unittest.mock import patch

from user.models import (
    ADMIN_DESKTOP_FULL_ADMIN_ROLE,
    AdminApprovalRequest,
    AdminDesktopActivityLog,
    AdminDesktopUser,
    ShopCategory,
    ShopOwner,
    get_admin_desktop_role_permissions,
)
from shop.models import AbuseReport, AccountModerationStatus, Customer, Driver, Order
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
        customer.refresh_from_db()
        self.assertEqual(customer.name, "Existing Customer Updated")

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
