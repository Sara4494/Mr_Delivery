from django.urls import path
from . import views

app_name = 'user'

urlpatterns = [
    # Legacy endpoints (للتوافق مع الكود القديم)
    path('shop/login/', views.ShopOwnerTokenObtainPairView.as_view(), name='shop_login'),
    path('shop/token/refresh/', views.ShopOwnerTokenRefreshView.as_view(), name='token_refresh'),
    
    # ==================== Unified Auth ====================
    # تسجيل دخول موحد لجميع المستخدمين
    path('auth/login/', views.unified_login_view, name='unified_login'),
    # تسجيل مستخدم جديد
    path('auth/register/', views.unified_register_view, name='unified_register'),
]
