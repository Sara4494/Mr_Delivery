from django.urls import path
from . import views

app_name = 'user'

urlpatterns = [
<<<<<<< HEAD
    # Legacy endpoints (للتوافق مع الكود القديم)
    path('shop/login/', views.ShopOwnerTokenObtainPairView.as_view(), name='shop_login'),
    path('shop/token/refresh/', views.ShopOwnerTokenRefreshView.as_view(), name='token_refresh'),
    
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
]
=======
    path('shop/login/', views.ShopOwnerTokenObtainPairView.as_view(), name='shop_login'),
    path('shop/token/refresh/', views.ShopOwnerTokenRefreshView.as_view(), name='token_refresh'),
]
>>>>>>> 4e65025 (feat: Implement gallery management features for shop owners)
