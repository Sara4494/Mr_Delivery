from django.urls import path

from user import views


app_name = 'admin_desktop_app'

urlpatterns = [
    path('admin-desktop/auth/login/', views.admin_desktop_login_view, name='admin_desktop_login'),
    path('admin-desktop/auth/token/refresh/', views.ShopOwnerTokenRefreshView.as_view(), name='admin_desktop_token_refresh'),
    path('admin-desktop/auth/me/', views.admin_desktop_me_view, name='admin_desktop_me'),
    path('admin-desktop/roles-permissions/', views.admin_desktop_roles_permissions_view, name='admin_desktop_roles_permissions'),
    path('admin-desktop/users/', views.admin_desktop_users_view, name='admin_desktop_users'),
    path('admin-desktop/users/<int:user_id>/', views.admin_desktop_user_detail_view, name='admin_desktop_user_detail'),
    path('admin-desktop/activity-logs/', views.admin_desktop_activity_logs_view, name='admin_desktop_activity_logs'),
    path('admin-desktop/approvals/requests/', views.admin_desktop_approval_requests_view, name='admin_desktop_approval_requests'),
    path('admin-desktop/approvals/image-publish-requests/', views.admin_desktop_image_publish_requests_view, name='admin_desktop_image_publish_requests'),
    path('admin-desktop/approvals/shop-edit-requests/', views.admin_desktop_shop_edit_requests_view, name='admin_desktop_shop_edit_requests'),
    path('admin-desktop/approvals/offer-requests/', views.admin_desktop_offer_requests_view, name='admin_desktop_offer_requests'),
    path('admin-desktop/approvals/requests/<int:approval_request_id>/', views.admin_desktop_approval_request_detail_view, name='admin_desktop_approval_request_detail'),
    path('admin-desktop/approvals/requests/<int:approval_request_id>/approve/', views.admin_desktop_approval_request_approve_view, name='admin_desktop_approval_request_approve'),
    path('admin-desktop/approvals/requests/<int:approval_request_id>/reject/', views.admin_desktop_approval_request_reject_view, name='admin_desktop_approval_request_reject'),
    path('admin-desktop/stores/categories/', views.admin_desktop_store_categories_view, name='admin_desktop_store_categories'),
    path('admin-desktop/stores/', views.admin_desktop_stores_view, name='admin_desktop_stores'),
    path('admin-desktop/stores/<int:shop_id>/', views.admin_desktop_store_detail_view, name='admin_desktop_store_detail'),
    path('admin-desktop/stores/<int:shop_id>/suspend/', views.admin_desktop_store_suspend_view, name='admin_desktop_store_suspend'),
    path('admin-desktop/stores/<int:shop_id>/activate/', views.admin_desktop_store_activate_view, name='admin_desktop_store_activate'),
    path('admin-desktop/dashboard/', views.admin_desktop_dashboard_view, name='admin_desktop_dashboard'),
    path('admin-desktop/dashboard/recent-activities/', views.admin_desktop_dashboard_recent_activities_view, name='admin_desktop_dashboard_recent_activities'),
    path('admin-desktop/dashboard/pending-actions/', views.admin_desktop_dashboard_pending_actions_view, name='admin_desktop_dashboard_pending_actions'),
    path('admin-desktop/reports/filters/', views.admin_desktop_reports_filters_view, name='admin_desktop_reports_filters'),
    path('admin-desktop/reports/analytics/', views.admin_desktop_reports_analytics_view, name='admin_desktop_reports_analytics'),
    path('admin-desktop/reports/stores/<int:shop_id>/preview/', views.admin_desktop_reports_store_preview_view, name='admin_desktop_reports_store_preview'),
    path('admin-desktop/reports/export/', views.admin_desktop_reports_export_view, name='admin_desktop_reports_export'),
    path('admin-desktop/abuse-reports/', views.admin_desktop_abuse_reports_view, name='admin_desktop_abuse_reports'),
    path('admin-desktop/abuse-reports/<int:report_id>/', views.admin_desktop_abuse_report_detail_view, name='admin_desktop_abuse_report_detail'),
    path('admin-desktop/abuse-reports/<int:report_id>/resolve/', views.admin_desktop_abuse_report_resolve_view, name='admin_desktop_abuse_report_resolve'),
    path('admin-desktop/support-actions/accounts/', views.admin_desktop_support_actions_accounts_view, name='admin_desktop_support_actions_accounts'),
    path('admin-desktop/support-actions/accounts/<str:account_type>/<int:account_id>/action/', views.admin_desktop_support_actions_account_action_view, name='admin_desktop_support_actions_account_action'),
    path('admin-desktop/app-status/maintenance/', views.admin_desktop_app_maintenance_settings_view, name='admin_desktop_app_maintenance_settings'),
]
