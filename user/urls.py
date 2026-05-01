from django.urls import path
from . import views

app_name = 'user'

urlpatterns = [
    # ==================== Unified Auth ====================
    path('auth/login/', views.unified_login_view, name='unified_login'),
    path('auth/google/', views.google_customer_auth_view, name='google_customer_auth'),
    path('auth/register/', views.unified_register_view, name='unified_register'),
    path('auth/otp/send/', views.send_otp_view, name='send_otp'),
    path('auth/otp/verify/', views.verify_otp_login_view, name='verify_otp'),
    path('auth/password-reset/', views.reset_password_view, name='reset_password'),
    path('auth/password-change/', views.change_password_view, name='change_password'),
]
