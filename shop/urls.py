from django.urls import path
from . import views

app_name = 'shop'

urlpatterns = [
    # Shop Status
    path('shop/status/', views.shop_status_view, name='shop_status'),
    
    # Customers
    path('shop/customers/', views.customer_list_view, name='customer_list'),
    path('shop/customers/<int:customer_id>/', views.customer_detail_view, name='customer_detail'),
    
    # Drivers
    path('shop/drivers/', views.driver_list_view, name='driver_list'),
    path('shop/drivers/<int:driver_id>/', views.driver_detail_view, name='driver_detail'),
    
    # Employees
    path('shop/employees/', views.employee_list_view, name='employee_list'),
    path('shop/employees/<int:employee_id>/', views.employee_detail_view, name='employee_detail'),
    path('shop/employees/statistics/', views.employee_statistics_view, name='employee_statistics'),
    
    # Orders
    path('shop/orders/', views.order_list_view, name='order_list'),
    path('shop/orders/<int:order_id>/', views.order_detail_view, name='order_detail'),
    path('shop/orders/<int:order_id>/messages/', views.order_messages_view, name='order_messages'),
    path('shop/orders/<int:order_id>/messages/read/', views.mark_messages_read_view, name='mark_messages_read'),
    
    # Invoices
    path('shop/invoices/', views.invoice_list_view, name='invoice_list'),
    path('shop/invoices/<int:invoice_id>/', views.invoice_detail_view, name='invoice_detail'),
    
    # Dashboard Statistics
    path('shop/dashboard/statistics/', views.shop_dashboard_statistics_view, name='dashboard_statistics'),
    
    # Login APIs
    path('employee/login/', views.employee_login_view, name='employee_login'),
    path('driver/login/', views.driver_login_view, name='driver_login'),
]
