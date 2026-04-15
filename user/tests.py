from django.test import SimpleTestCase, TestCase
from rest_framework.test import APIClient

from user.models import (
    ADMIN_DESKTOP_FULL_ADMIN_ROLE,
    AdminApprovalRequest,
    AdminDesktopUser,
    ShopCategory,
    ShopOwner,
    get_admin_desktop_role_permissions,
)
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
            ["support_center", "abuse_reports"],
        )

    def test_normalize_permissions_caps_to_role_permissions(self):
        self.assertEqual(
            _normalize_admin_desktop_permissions(
                "technical_support",
                ["support_center", "app_updates", "dashboard", "abuse_reports"],
            ),
            ["support_center", "abuse_reports"],
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
