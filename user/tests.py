from django.test import SimpleTestCase

from user.models import (
    ADMIN_DESKTOP_FULL_ADMIN_ROLE,
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
