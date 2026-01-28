from django.urls import path
from . import views

app_name = 'user'

urlpatterns = [
    path('shop/login/', views.ShopOwnerTokenObtainPairView.as_view(), name='shop_login'),
    path('shop/token/refresh/', views.ShopOwnerTokenRefreshView.as_view(), name='token_refresh'),
]