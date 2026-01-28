from django.urls import path
from . import views

app_name = 'gallery'

urlpatterns = [
    # Profile
    path('shop/profile/', views.shop_profile_view, name='shop_profile'),
    path('shop/profile/image/', views.shop_profile_image_view, name='shop_profile_image'),
    
    # Work Schedule
    path('shop/schedule/', views.work_schedule_view, name='work_schedule'),
    
    # Gallery
    path('shop/gallery/', views.gallery_list_view, name='gallery_list'),
    path('shop/gallery/<int:image_id>/', views.gallery_detail_view, name='gallery_detail'),
    path('shop/gallery/<int:image_id>/like/', views.image_like_view, name='image_like'),
    
    # Statistics
    path('shop/statistics/', views.shop_statistics_view, name='shop_statistics'),
]
