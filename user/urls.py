from django.urls import path
from . import views

app_name = 'user'

urlpatterns = [
    # Legacy endpoints (للتوافق مع الكود القديم)
    path('shop/login/', views.ShopOwnerTokenObtainPairView.as_view(), name='shop_login'),
    path('shop/token/refresh/', views.ShopOwnerTokenRefreshView.as_view(), name='token_refresh'),
    path('admin-desktop/auth/login/', views.admin_desktop_login_view, name='admin_desktop_login'),
    path('admin-desktop/auth/token/refresh/', views.ShopOwnerTokenRefreshView.as_view(), name='admin_desktop_token_refresh'),
    path('admin-desktop/auth/me/', views.admin_desktop_me_view, name='admin_desktop_me'),
    path('admin-desktop/roles-permissions/', views.admin_desktop_roles_permissions_view, name='admin_desktop_roles_permissions'),
    path('admin-desktop/users/', views.admin_desktop_users_view, name='admin_desktop_users'),
    path('admin-desktop/users/<int:user_id>/', views.admin_desktop_user_detail_view, name='admin_desktop_user_detail'),
    
    # ==================== Unified Auth ====================
    # تسجيل دخول موحد لجميع المستخدمين
    path('auth/login/', views.unified_login_view, name='unified_login'),
    # تسجيل مستخدم جديد
    path('auth/register/', views.unified_register_view, name='unified_register'),
    # ==================== OTP (UltraMsg WhatsApp) ====================
    path('auth/otp/send/', views.send_otp_view, name='send_otp'),
    path('auth/otp/verify/', views.verify_otp_login_view, name='verify_otp'),
    # استعادة كلمة المرور
    path('auth/password-reset/', views.reset_password_view, name='reset_password'),
    # تغيير كلمة المرور للمستخدم الحالي
    path('auth/password-change/', views.change_password_view, name='change_password'),
]
