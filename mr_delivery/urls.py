"""
URL configuration for mr_delivery project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/6.0/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from django.views.generic import TemplateView
from user import views as user_views

urlpatterns = [
    path('admin/', admin.site.urls),
    path(
        'privacy/',
        TemplateView.as_view(template_name='shop/customer_privacy.html'),
        name='customer_privacy',
    ),
    path(
        'terms/',
        TemplateView.as_view(template_name='shop/customer_terms.html'),
        name='customer_terms',
    ),
    path(
        'customer/privacy/',
        TemplateView.as_view(template_name='shop/customer_privacy.html'),
        name='customer_privacy_alias',
    ),
    path(
        'customer/terms/',
        TemplateView.as_view(template_name='shop/customer_terms.html'),
        name='customer_terms_alias',
    ),
    path(
        'driver/privacy/',
        TemplateView.as_view(template_name='shop/driver_privacy.html'),
        name='driver_privacy',
    ),
    path(
        'driver/terms/',
        TemplateView.as_view(template_name='shop/driver_terms.html'),
        name='driver_terms',
    ),
    path('admin-broadcast-test/', user_views.admin_broadcast_test_page_view, name='admin_broadcast_test_page'),
    path('api/', include('admin_desktop_app.urls')),
    path('api/', include('shop_app.urls')),
    path('api/', include('driver_app.urls')),
    path('api/', include('customer_app.urls')),
    path('api/', include('support_center.urls')),
    path('api/', include('platform_core.urls')),
    path('api/', include('user.urls')),
    path('api/', include('gallery.urls')),
]

# إضافة مسار الملفات الوسائط في وضع التطوير
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
