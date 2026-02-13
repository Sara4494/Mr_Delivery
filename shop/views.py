from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework.response import Response
from rest_framework.pagination import PageNumberPagination
from django.db.models import Q, Count, Sum, F, Avg
from django.utils import timezone
from datetime import timedelta
from .models import (
    ShopStatus, Customer, CustomerAddress, Driver, Order, ChatMessage, 
    Invoice, Employee, Product, Category, OrderRating, PaymentMethod, 
    Notification, Cart, CartItem
)
from .serializers import (
    ShopStatusSerializer,
    CustomerSerializer,
    CustomerCreateSerializer,
    CustomerAddressSerializer,
    DriverSerializer,
    DriverCreateSerializer,
    DriverLocationUpdateSerializer,
    OrderSerializer,
    OrderCreateSerializer,
    CustomerOrderCreateSerializer,
    InvoiceSerializer,
    InvoiceCreateSerializer,
    EmployeeSerializer,
    EmployeeCreateSerializer,
    EmployeeUpdateSerializer,
    EmployeeTokenObtainPairSerializer,
    DriverTokenObtainPairSerializer,
    CustomerTokenObtainPairSerializer,
    CustomerRegisterSerializer,
    ProductSerializer,
    ProductCreateSerializer,
    CategorySerializer,
    OrderRatingSerializer,
    OrderRatingCreateSerializer,
    PaymentMethodSerializer,
    PaymentMethodCreateSerializer,
    NotificationSerializer,
    CartSerializer,
    CartItemSerializer,
    AddToCartSerializer,
    UpdateCartItemSerializer,
)
from .permissions import IsShopOwner, IsCustomer, IsDriver, IsEmployee, IsShopOwnerOrEmployee
from user.models import ShopOwner
from user.utils import success_response, error_response, build_message_fields, t
from .websocket_utils import notify_order_update, notify_driver_assigned, notify_new_order, broadcast_chat_message_to_order


class OrderPagination(PageNumberPagination):
    """Pagination للطلبات"""
    page_size = 20
    page_size_query_param = 'page_size'
    max_page_size = 100
    
    def get_paginated_response(self, data):
        """تخصيص شكل الـ response للـ pagination"""
        from rest_framework.response import Response
        from rest_framework import status
        
        response_data = {
            "status": status.HTTP_200_OK,
            **build_message_fields(
                t(getattr(self, "request", None), "orders_retrieved_successfully"),
                request=getattr(self, "request", None)
            ),
            "data": {
                'count': self.page.paginator.count,
                'next': self.get_next_link(),
                'previous': self.get_previous_link(),
                'results': data
            }
        }
        
        return Response(response_data, status=status.HTTP_200_OK)


class CustomerPagination(PageNumberPagination):
    """Pagination للعملاء"""
    page_size = 20
    page_size_query_param = 'page_size'
    max_page_size = 100
    
    def get_paginated_response(self, data):
        """تخصيص شكل الـ response للـ pagination"""
        from rest_framework.response import Response
        from rest_framework import status
        
        response_data = {
            "status": status.HTTP_200_OK,
            **build_message_fields(
                t(getattr(self, "request", None), "customers_retrieved_successfully"),
                request=getattr(self, "request", None)
            ),
            "data": {
                'count': self.page.paginator.count,
                'next': self.get_next_link(),
                'previous': self.get_previous_link(),
                'results': data
            }
        }
        
        return Response(response_data, status=status.HTTP_200_OK)


# Shop Status APIs
@api_view(['GET', 'PUT'])
@permission_classes([IsShopOwner])
def shop_status_view(request):
    """
    عرض وتحديث حالة المتجر
    GET /api/shop/status/ - عرض حالة المتجر
    PUT /api/shop/status/ - تحديث حالة المتجر
    """
    shop_owner = request.user
    
    status_obj, created = ShopStatus.objects.get_or_create(shop_owner=shop_owner)
    
    if request.method == 'GET':
        serializer = ShopStatusSerializer(status_obj)
        return success_response(
            data=serializer.data,
            message=t(request, 'shop_status_retrieved_successfully'),
            status_code=status.HTTP_200_OK
        )
    
    elif request.method == 'PUT':
        serializer = ShopStatusSerializer(status_obj, data=request.data, partial=True)
        if serializer.is_valid():
            serializer.save()
            return success_response(
                data=serializer.data,
                message=t(request, 'shop_status_updated_successfully'),
                status_code=status.HTTP_200_OK
            )
        return error_response(
            message=t(request, 'invalid_data'),
            errors=serializer.errors,
            status_code=status.HTTP_400_BAD_REQUEST
        )


# Customer APIs
@api_view(['GET', 'POST'])
@permission_classes([IsShopOwner])
def customer_list_view(request):
    """
    عرض قائمة العملاء وإضافة عميل جديد
    GET /api/shop/customers/ - عرض قائمة العملاء
    POST /api/shop/customers/ - إضافة عميل جديد
    """
    shop_owner = request.user
    
    if request.method == 'GET':
        search_query = request.query_params.get('search', '')
        queryset = Customer.objects.filter(shop_owner=shop_owner)
        
        if search_query:
            queryset = queryset.filter(
                Q(name__icontains=search_query) |
                Q(phone_number__icontains=search_query)
            )
        
        # Pagination
        paginator = CustomerPagination()
        page = paginator.paginate_queryset(queryset, request)
        
        if page is not None:
            serializer = CustomerSerializer(page, many=True, context={'request': request})
            return paginator.get_paginated_response(serializer.data)
        
        serializer = CustomerSerializer(queryset, many=True, context={'request': request})
        return success_response(
            data=serializer.data,
            message=t(request, 'customers_retrieved_successfully'),
            status_code=status.HTTP_200_OK
        )
    
    elif request.method == 'POST':
        serializer = CustomerCreateSerializer(
            data=request.data,
            context={'shop_owner': shop_owner, 'request': request}
        )
        if serializer.is_valid():
            customer = serializer.save()
            response_serializer = CustomerSerializer(customer, context={'request': request})
            return success_response(
                data=response_serializer.data,
                message=t(request, 'customer_added_successfully'),
                status_code=status.HTTP_201_CREATED
            )
        return error_response(
            message=t(request, 'invalid_data'),
            errors=serializer.errors,
            status_code=status.HTTP_400_BAD_REQUEST
        )


@api_view(['GET', 'PUT', 'DELETE'])
@permission_classes([IsShopOwner])
def customer_detail_view(request, customer_id):
    """
    عرض، تحديث، أو حذف عميل
    GET /api/shop/customers/{id}/ - عرض عميل
    PUT /api/shop/customers/{id}/ - تحديث عميل
    DELETE /api/shop/customers/{id}/ - حذف عميل
    """
    shop_owner = request.user
    
    try:
        customer = Customer.objects.get(id=customer_id, shop_owner=shop_owner)
    except Customer.DoesNotExist:
        return error_response(
            message=t(request, 'customer_not_found'),
            status_code=status.HTTP_404_NOT_FOUND
        )
    
    if request.method == 'GET':
        serializer = CustomerSerializer(customer, context={'request': request})
        return success_response(
            data=serializer.data,
            message=t(request, 'customer_data_retrieved_successfully'),
            status_code=status.HTTP_200_OK
        )
    
    elif request.method == 'PUT':
        serializer = CustomerCreateSerializer(customer, data=request.data, partial=True)
        if serializer.is_valid():
            serializer.save()
            response_serializer = CustomerSerializer(customer, context={'request': request})
            return success_response(
                data=response_serializer.data,
                message=t(request, 'customer_data_updated_successfully'),
                status_code=status.HTTP_200_OK
            )
        return error_response(
            message=t(request, 'invalid_data'),
            errors=serializer.errors,
            status_code=status.HTTP_400_BAD_REQUEST
        )
    
    elif request.method == 'DELETE':
        customer.delete()
        return success_response(
            message=t(request, 'customer_deleted_successfully'),
            status_code=status.HTTP_200_OK
        )


# Driver APIs
@api_view(['GET', 'POST'])
@permission_classes([IsShopOwner])
def driver_list_view(request):
    """
    عرض قائمة السائقين وإضافة سائق جديد
    GET /api/shop/drivers/ - عرض قائمة السائقين
    POST /api/shop/drivers/ - إضافة سائق جديد
    """
    shop_owner = request.user
    
    if request.method == 'GET':
        status_filter = request.query_params.get('status')
        queryset = Driver.objects.filter(shop_owner=shop_owner)
        
        if status_filter:
            queryset = queryset.filter(status=status_filter)
        
        serializer = DriverSerializer(queryset, many=True, context={'request': request})
        return success_response(
            data=serializer.data,
            message=t(request, 'drivers_retrieved_successfully'),
            status_code=status.HTTP_200_OK
        )
    
    elif request.method == 'POST':
        serializer = DriverCreateSerializer(
            data=request.data,
            context={'shop_owner': shop_owner, 'request': request}
        )
        if serializer.is_valid():
            driver = serializer.save()
            response_serializer = DriverSerializer(driver, context={'request': request})
            return success_response(
                data=response_serializer.data,
                message=t(request, 'driver_added_successfully'),
                status_code=status.HTTP_201_CREATED
            )
        return error_response(
            message=t(request, 'invalid_data'),
            errors=serializer.errors,
            status_code=status.HTTP_400_BAD_REQUEST
        )


@api_view(['GET', 'PUT', 'DELETE'])
@permission_classes([IsShopOwner])
def driver_detail_view(request, driver_id):
    """
    عرض، تحديث، أو حذف سائق
    GET /api/shop/drivers/{id}/ - عرض سائق
    PUT /api/shop/drivers/{id}/ - تحديث سائق
    DELETE /api/shop/drivers/{id}/ - حذف سائق
    """
    shop_owner = request.user
    
    try:
        driver = Driver.objects.get(id=driver_id, shop_owner=shop_owner)
    except Driver.DoesNotExist:
        return error_response(
            message=t(request, 'driver_not_found'),
            status_code=status.HTTP_404_NOT_FOUND
        )
    
    if request.method == 'GET':
        serializer = DriverSerializer(driver, context={'request': request})
        return success_response(
            data=serializer.data,
            message=t(request, 'driver_data_retrieved_successfully'),
            status_code=status.HTTP_200_OK
        )
    
    elif request.method == 'PUT':
        serializer = DriverCreateSerializer(driver, data=request.data, partial=True)
        if serializer.is_valid():
            serializer.save()
            # تحديث عدد الطلبات الحالية
            driver.current_orders_count = driver.orders.filter(status__in=['new', 'preparing', 'on_way']).count()
            driver.save()
            response_serializer = DriverSerializer(driver, context={'request': request})
            return success_response(
                data=response_serializer.data,
                message=t(request, 'driver_data_updated_successfully'),
                status_code=status.HTTP_200_OK
            )
        return error_response(
            message=t(request, 'invalid_data'),
            errors=serializer.errors,
            status_code=status.HTTP_400_BAD_REQUEST
        )
    
    elif request.method == 'DELETE':
        driver.delete()
        return success_response(
            message=t(request, 'driver_deleted_successfully'),
            status_code=status.HTTP_200_OK
        )


@api_view(['POST'])
@permission_classes([IsShopOwner])
def driver_approve_view(request, driver_id):
    """
    الموافقة على طلب انضمام سائق (تغيير الحالة من pending إلى available)
    POST /api/shop/drivers/{id}/approve/
    """
    shop_owner = request.user
    try:
        driver = Driver.objects.get(id=driver_id, shop_owner=shop_owner)
    except Driver.DoesNotExist:
        return error_response(
            message=t(request, 'driver_not_found'),
            status_code=status.HTTP_404_NOT_FOUND
        )
    if driver.status != 'pending':
        return error_response(
            message=t(request, 'driver_is_not_pending_approval'),
            status_code=status.HTTP_400_BAD_REQUEST
        )
    driver.status = 'available'
    driver.save()
    serializer = DriverSerializer(driver, context={'request': request})
    return success_response(
        data=serializer.data,
        message=t(request, 'driver_approved_successfully'),
        status_code=status.HTTP_200_OK
    )


# Product APIs (قائمة المنتجات - بروفايل المحل)
@api_view(['GET', 'POST'])
@permission_classes([IsShopOwner])
def product_list_view(request):
    """
    عرض قائمة المنتجات وإضافة منتج
    GET /api/shop/products/ - عرض قائمة المنتجات
    POST /api/shop/products/ - إضافة منتج
    """
    shop_owner = request.user
    if request.method == 'GET':
        available_only = request.query_params.get('available')
        queryset = Product.objects.filter(shop_owner=shop_owner)
        if available_only == 'true':
            queryset = queryset.filter(is_available=True)
        serializer = ProductSerializer(queryset, many=True, context={'request': request})
        return success_response(
            data=serializer.data,
            message=t(request, 'product_list_retrieved_successfully'),
            status_code=status.HTTP_200_OK
        )
    elif request.method == 'POST':
        serializer = ProductCreateSerializer(data=request.data)
        if serializer.is_valid():
            product = Product.objects.create(shop_owner=shop_owner, **serializer.validated_data)
            response_serializer = ProductSerializer(product, context={'request': request})
            return success_response(
                data=response_serializer.data,
                message=t(request, 'product_added_successfully'),
                status_code=status.HTTP_201_CREATED
            )
        return error_response(
            message=t(request, 'invalid_data'),
            errors=serializer.errors,
            status_code=status.HTTP_400_BAD_REQUEST
        )


@api_view(['GET', 'PUT', 'DELETE'])
@permission_classes([IsShopOwner])
def product_detail_view(request, product_id):
    """
    عرض، تحديث، أو حذف منتج
    GET /api/shop/products/{id}/ - عرض منتج
    PUT /api/shop/products/{id}/ - تحديث منتج
    DELETE /api/shop/products/{id}/ - حذف منتج
    """
    shop_owner = request.user
    try:
        product = Product.objects.get(id=product_id, shop_owner=shop_owner)
    except Product.DoesNotExist:
        return error_response(
            message=t(request, 'product_not_found'),
            status_code=status.HTTP_404_NOT_FOUND
        )
    if request.method == 'GET':
        serializer = ProductSerializer(product, context={'request': request})
        return success_response(
            data=serializer.data,
            message=t(request, 'product_data_retrieved_successfully'),
            status_code=status.HTTP_200_OK
        )
    elif request.method == 'PUT':
        serializer = ProductCreateSerializer(product, data=request.data, partial=True)
        if serializer.is_valid():
            serializer.save()
            response_serializer = ProductSerializer(product, context={'request': request})
            return success_response(
                data=response_serializer.data,
                message=t(request, 'product_updated_successfully'),
                status_code=status.HTTP_200_OK
            )
        return error_response(
            message=t(request, 'invalid_data'),
            errors=serializer.errors,
            status_code=status.HTTP_400_BAD_REQUEST
        )
    elif request.method == 'DELETE':
        product.delete()
        return success_response(
            message=t(request, 'product_deleted_successfully'),
            status_code=status.HTTP_200_OK
        )


# Order APIs
@api_view(['GET', 'POST'])
@permission_classes([IsShopOwnerOrEmployee])
def order_list_view(request):
    """
    عرض قائمة الطلبات وإنشاء طلب جديد
    GET /api/shop/orders/ - عرض قائمة الطلبات
    POST /api/shop/orders/ - إنشاء طلب جديد (من المحل)
    """
    shop_owner = _get_shop_owner_from_request(request)
    
    if request.method == 'GET':
        status_filter = request.query_params.get('status')
        search_query = request.query_params.get('search')
        
        queryset = Order.objects.filter(shop_owner=shop_owner).select_related('customer', 'driver')
        
        if status_filter:
            queryset = queryset.filter(status=status_filter)
        
        if search_query:
            queryset = queryset.filter(
                Q(order_number__icontains=search_query) |
                Q(customer__name__icontains=search_query) |
                Q(customer__phone_number__icontains=search_query)
            )
        
        # Sorting
        sort_by = request.query_params.get('sort_by', '-created_at')
        if sort_by.lstrip('-') in ['created_at', 'updated_at', 'total_amount']:
            queryset = queryset.order_by(sort_by)
        
        # Pagination
        paginator = OrderPagination()
        page = paginator.paginate_queryset(queryset, request)
        
        if page is not None:
            serializer = OrderSerializer(page, many=True, context={'request': request})
            return paginator.get_paginated_response(serializer.data)
        
        serializer = OrderSerializer(queryset, many=True, context={'request': request})
        return success_response(
            data=serializer.data,
            message=t(request, 'orders_retrieved_successfully'),
            status_code=status.HTTP_200_OK
        )
    
    elif request.method == 'POST':
        serializer = OrderCreateSerializer(
            data=request.data,
            context={'shop_owner': shop_owner, 'request': request}
        )
        if serializer.is_valid():
            order = serializer.save()
            response_serializer = OrderSerializer(order, context={'request': request})
            return success_response(
                data=response_serializer.data,
                message=t(request, 'order_created_successfully'),
                status_code=status.HTTP_201_CREATED
            )
        return error_response(
            message=t(request, 'invalid_data'),
            errors=serializer.errors,
            status_code=status.HTTP_400_BAD_REQUEST
        )


def _get_shop_owner_from_request(request):
    """صاحب المحل من الطلب (صاحب محل أو موظف)"""
    user = request.user
    if hasattr(user, 'shop_owner_id') and user.shop_owner_id:
        return user.shop_owner
    return user


@api_view(['GET', 'PUT', 'DELETE'])
@permission_classes([IsShopOwnerOrEmployee])
def order_detail_view(request, order_id):
    """
    عرض، تحديث، أو حذف طلب
    GET /api/shop/orders/{id}/ - عرض طلب
    PUT /api/shop/orders/{id}/ - تحديث طلب (قبول/رفض/إلغاء/تسعير)
    DELETE /api/shop/orders/{id}/ - حذف طلب
    """
    shop_owner = _get_shop_owner_from_request(request)
    
    try:
        order = Order.objects.get(id=order_id, shop_owner=shop_owner)
    except Order.DoesNotExist:
        return error_response(
            message=t(request, 'order_not_found'),
            status_code=status.HTTP_404_NOT_FOUND
        )
    
    if request.method == 'GET':
        serializer = OrderSerializer(order, context={'request': request})
        return success_response(
            data=serializer.data,
            message=t(request, 'order_data_retrieved_successfully'),
            status_code=status.HTTP_200_OK
        )
    
    elif request.method == 'PUT':
        # تحديث الطلب
        old_driver = order.driver
        old_status = order.status
        
        # قبول الطلب: يجب تعبئة سعر الطلب (سعر التوصيل اختياري)
        new_status = request.data.get('status', order.status)
        if new_status == 'pending_customer_confirm':
            new_total = request.data.get('total_amount')
            if new_total is None:
                new_total = order.total_amount
            if new_total is None or (isinstance(new_total, (int, float)) and float(new_total) <= 0):
                return error_response(
                    message=t(request, 'order_price_required_for_accept'),
                    status_code=status.HTTP_400_BAD_REQUEST
                )
        
        if 'customer_id' in request.data:
            try:
                customer = Customer.objects.get(id=request.data['customer_id'], shop_owner=shop_owner)
                order.customer = customer
            except Customer.DoesNotExist:
                return error_response(
                    message=t(request, 'customer_not_found'),
                    status_code=status.HTTP_404_NOT_FOUND
                )
        
        if 'employee_id' in request.data:
            emp_id = request.data['employee_id']
            if emp_id:
                try:
                    order.employee = Employee.objects.get(id=emp_id, shop_owner=shop_owner)
                except Employee.DoesNotExist:
                    return error_response(
                        message=t(request, 'employee_not_found'),
                        status_code=status.HTTP_404_NOT_FOUND
                    )
            else:
                order.employee = None
        
        if 'driver_id' in request.data:
            driver_id = request.data['driver_id']
            if driver_id:
                try:
                    driver = Driver.objects.get(id=driver_id, shop_owner=shop_owner)
                    order.driver = driver
                except Driver.DoesNotExist:
                    return error_response(
                        message=t(request, 'driver_not_found'),
                        status_code=status.HTTP_404_NOT_FOUND
                    )
            else:
                order.driver = None
        
        # تحديث باقي الحقول
        for field in ['status', 'items', 'total_amount', 'delivery_fee', 'address', 'notes']:
            if field in request.data:
                setattr(order, field, request.data[field])
        
        order.save()
        
        # رسائل تلقائية عند الرفض/الإلغاء/القبول (حسب الصور والـ PDF)
        try:
            if new_status == 'cancelled':
                if old_status == 'new':
                    msg_content = t(request, 'store_reject_message')
                else:
                    msg_content = t(request, 'order_cancelled_successfully')
                sender_type = 'employee' if getattr(request.user, 'user_type', None) == 'employee' else 'shop_owner'
                sys_msg = ChatMessage.objects.create(
                    order=order,
                    chat_type='shop_customer',
                    sender_type=sender_type,
                    sender_shop_owner=shop_owner if sender_type == 'shop_owner' else None,
                    sender_employee=request.user if sender_type == 'employee' else None,
                    message_type='text',
                    content=msg_content,
                )
                broadcast_chat_message_to_order(order.id, {
                    'id': sys_msg.id,
                    'sender_type': sys_msg.sender_type,
                    'sender_name': sys_msg.sender_name,
                    'message_type': 'text',
                    'content': sys_msg.content,
                    'is_read': False,
                    'created_at': sys_msg.created_at.isoformat(),
                    'audio_file_url': None,
                    'image_file_url': None,
                    'latitude': None,
                    'longitude': None,
                })
            elif new_status == 'pending_customer_confirm':
                msg_content = t(request, 'order_priced_please_confirm')
                sender_type = 'employee' if getattr(request.user, 'user_type', None) == 'employee' else 'shop_owner'
                sys_msg = ChatMessage.objects.create(
                    order=order,
                    chat_type='shop_customer',
                    sender_type=sender_type,
                    sender_shop_owner=shop_owner if sender_type == 'shop_owner' else None,
                    sender_employee=request.user if sender_type == 'employee' else None,
                    message_type='text',
                    content=msg_content,
                )
                broadcast_chat_message_to_order(order.id, {
                    'id': sys_msg.id,
                    'sender_type': sys_msg.sender_type,
                    'sender_name': sys_msg.sender_name,
                    'message_type': 'text',
                    'content': sys_msg.content,
                    'is_read': False,
                    'created_at': sys_msg.created_at.isoformat(),
                    'audio_file_url': None,
                    'image_file_url': None,
                    'latitude': None,
                    'longitude': None,
                })
        except Exception as e:
            print(f"Order system message broadcast error: {e}")
        
        # تحديث عدد الطلبات للسائقين
        if old_driver:
            old_driver.current_orders_count = old_driver.orders.filter(
                status__in=['new', 'preparing', 'on_way']
            ).count()
            old_driver.save()
        
        if order.driver:
            order.driver.current_orders_count = order.driver.orders.filter(
                status__in=['new', 'preparing', 'on_way']
            ).count()
            order.driver.save()
        
        response_serializer = OrderSerializer(order, context={'request': request})
        
        # إرسال إشعار WebSocket بتحديث الطلب
        try:
            order_data = response_serializer.data
            notify_order_update(
                shop_owner_id=shop_owner.id,
                customer_id=order.customer_id,
                driver_id=order.driver_id if order.driver else None,
                order_data=order_data
            )
            
            # إذا تم تعيين سائق جديد، إشعاره
            if order.driver and (not old_driver or old_driver.id != order.driver.id):
                notify_driver_assigned(order.driver.id, order_data)
        except Exception as e:
            print(f"WebSocket notification error: {e}")
        
        return success_response(
            data=response_serializer.data,
            message=t(request, 'order_updated_successfully'),
            status_code=status.HTTP_200_OK
        )
    
    elif request.method == 'DELETE':
        order.delete()
        return success_response(
            message=t(request, 'order_deleted_successfully'),
            status_code=status.HTTP_200_OK
        )


# Invoice APIs
@api_view(['GET', 'POST'])
@permission_classes([IsShopOwner])
def invoice_list_view(request):
    """
    عرض قائمة الفواتير وإنشاء فاتورة سريعة
    GET /api/shop/invoices/ - عرض قائمة الفواتير
    POST /api/shop/invoices/ - إنشاء فاتورة سريعة
    """
    shop_owner = request.user
    
    if request.method == 'GET':
        queryset = Invoice.objects.filter(shop_owner=shop_owner).select_related('customer', 'order')
        serializer = InvoiceSerializer(queryset, many=True, context={'request': request})
        return success_response(
            data=serializer.data,
            message=t(request, 'invoices_retrieved_successfully'),
            status_code=status.HTTP_200_OK
        )
    
    elif request.method == 'POST':
        data = request.data.copy()
        if 'items' in data and isinstance(data.get('items'), str):
            data['items_text'] = data['items']
        serializer = InvoiceCreateSerializer(data=data)
        if serializer.is_valid():
            import json
            data = serializer.validated_data
            customer, _ = Customer.objects.get_or_create(
                shop_owner=shop_owner,
                phone_number=data['phone_number'],
                defaults={
                    'name': data['customer_name'],
                    'address': data['address']
                }
            )
            items_for_db = json.dumps(data['_items_json'], ensure_ascii=False) if data.get('_items_json') else data.get('_items_text', '[]')
            import random
            invoice_number = f"INV{shop_owner.shop_number}{random.randint(1000, 9999)}"
            while Invoice.objects.filter(invoice_number=invoice_number).exists():
                invoice_number = f"INV{shop_owner.shop_number}{random.randint(1000, 9999)}"
            invoice = Invoice.objects.create(
                shop_owner=shop_owner,
                customer=customer,
                invoice_number=invoice_number,
                items=items_for_db,
                total_amount=data['amount'],
                delivery_fee=data.get('delivery', 0),
                address=data['address'],
                phone_number=data['phone_number']
            )
            
            response_serializer = InvoiceSerializer(invoice, context={'request': request})
            return success_response(
                data=response_serializer.data,
                message=t(request, 'invoice_created_successfully'),
                status_code=status.HTTP_201_CREATED
            )
        return error_response(
            message=t(request, 'invalid_data'),
            errors=serializer.errors,
            status_code=status.HTTP_400_BAD_REQUEST
        )


@api_view(['GET', 'PUT'])
@permission_classes([IsShopOwner])
def invoice_detail_view(request, invoice_id):
    """
    عرض فاتورة أو تحديث حالة الإرسال
    GET /api/shop/invoices/{id}/ - عرض فاتورة
    PUT /api/shop/invoices/{id}/ - تحديث حالة الإرسال
    """
    shop_owner = request.user
    
    try:
        invoice = Invoice.objects.get(id=invoice_id, shop_owner=shop_owner)
    except Invoice.DoesNotExist:
        return error_response(
            message=t(request, 'invoice_not_found'),
            status_code=status.HTTP_404_NOT_FOUND
        )
    
    if request.method == 'GET':
        serializer = InvoiceSerializer(invoice, context={'request': request})
        return success_response(
            data=serializer.data,
            message=t(request, 'invoice_data_retrieved_successfully'),
            status_code=status.HTTP_200_OK
        )
    
    elif request.method == 'PUT':
        is_sent = request.data.get('is_sent', False)
        invoice.is_sent = is_sent
        if is_sent and not invoice.sent_at:
            invoice.sent_at = timezone.now()
        invoice.save()
        
        serializer = InvoiceSerializer(invoice, context={'request': request})
        return success_response(
            data=serializer.data,
            message=t(request, 'invoice_status_updated_successfully'),
            status_code=status.HTTP_200_OK
        )


# Statistics API
@api_view(['GET'])
@permission_classes([IsShopOwner])
def shop_dashboard_statistics_view(request):
    """
    إحصائيات لوحة التحكم للمحل
    GET /api/shop/dashboard/statistics/
    """
    shop_owner = request.user
    
    # إجمالي الإيرادات
    total_revenue = Order.objects.filter(
        shop_owner=shop_owner,
        status='delivered'
    ).aggregate(total=Sum('total_amount'))['total'] or 0
    
    # إجمالي الطلبات
    total_orders = Order.objects.filter(shop_owner=shop_owner).count()
    
    # الطلبات حسب الحالة
    orders_by_status = Order.objects.filter(shop_owner=shop_owner).values('status').annotate(
        count=Count('id')
    )
    
    # عدد العملاء
    total_customers = Customer.objects.filter(shop_owner=shop_owner).count()
    
    # عدد السائقين
    total_drivers = Driver.objects.filter(shop_owner=shop_owner).count()
    available_drivers = Driver.objects.filter(shop_owner=shop_owner, status='available').count()
    
    # الطلبات الجديدة
    new_orders_count = Order.objects.filter(shop_owner=shop_owner, status='new').count()
    
    statistics = {
        'total_revenue': float(total_revenue),
        'total_orders': total_orders,
        'total_customers': total_customers,
        'total_drivers': total_drivers,
        'available_drivers': available_drivers,
        'new_orders_count': new_orders_count,
        'orders_by_status': {item['status']: item['count'] for item in orders_by_status}
    }
    
    return success_response(
        data=statistics,
        message=t(request, 'statistics_retrieved_successfully'),
        status_code=status.HTTP_200_OK
    )


# Employee APIs
@api_view(['GET', 'POST'])
@permission_classes([IsShopOwner])
def employee_list_view(request):
    """
    عرض قائمة الموظفين وإضافة موظف جديد
    GET /api/shop/employees/ - عرض قائمة الموظفين
    POST /api/shop/employees/ - إضافة موظف جديد
    """
    shop_owner = request.user
    
    if request.method == 'GET':
        role_filter = request.query_params.get('role')
        queryset = Employee.objects.filter(shop_owner=shop_owner)
        
        if role_filter:
            queryset = queryset.filter(role=role_filter)
        
        serializer = EmployeeSerializer(queryset, many=True, context={'request': request})
        return success_response(
            data=serializer.data,
            message=t(request, 'employees_retrieved_successfully'),
            status_code=status.HTTP_200_OK
        )
    
    elif request.method == 'POST':
        serializer = EmployeeCreateSerializer(
            data=request.data,
            context={'shop_owner': shop_owner, 'request': request}
        )
        if serializer.is_valid():
            employee = serializer.save()
            response_serializer = EmployeeSerializer(employee, context={'request': request})
            return success_response(
                data=response_serializer.data,
                message=t(request, 'employee_added_successfully'),
                status_code=status.HTTP_201_CREATED
            )
        return error_response(
            message=t(request, 'invalid_data'),
            errors=serializer.errors,
            status_code=status.HTTP_400_BAD_REQUEST
        )


@api_view(['GET', 'PUT', 'DELETE'])
@permission_classes([IsShopOwner])
def employee_detail_view(request, employee_id):
    """
    عرض، تحديث، أو حذف موظف
    GET /api/shop/employees/{id}/ - عرض موظف
    PUT /api/shop/employees/{id}/ - تحديث موظف
    DELETE /api/shop/employees/{id}/ - حذف موظف
    """
    shop_owner = request.user
    
    try:
        employee = Employee.objects.get(id=employee_id, shop_owner=shop_owner)
    except Employee.DoesNotExist:
        return error_response(
            message=t(request, 'employee_not_found'),
            status_code=status.HTTP_404_NOT_FOUND
        )
    
    if request.method == 'GET':
        serializer = EmployeeSerializer(employee, context={'request': request})
        return success_response(
            data=serializer.data,
            message=t(request, 'employee_data_retrieved_successfully'),
            status_code=status.HTTP_200_OK
        )
    
    elif request.method == 'PUT':
        serializer = EmployeeUpdateSerializer(employee, data=request.data, partial=True)
        if serializer.is_valid():
            serializer.save()
            response_serializer = EmployeeSerializer(employee, context={'request': request})
            return success_response(
                data=response_serializer.data,
                message=t(request, 'employee_data_updated_successfully'),
                status_code=status.HTTP_200_OK
            )
        return error_response(
            message=t(request, 'invalid_data'),
            errors=serializer.errors,
            status_code=status.HTTP_400_BAD_REQUEST
        )
    
    elif request.method == 'DELETE':
        employee.delete()
        return success_response(
            message=t(request, 'employee_deleted_successfully'),
            status_code=status.HTTP_200_OK
        )


# Employee Statistics API
@api_view(['GET'])
@permission_classes([IsShopOwner])
def employee_statistics_view(request):
    """
    إحصائيات الموظفين
    GET /api/shop/employees/statistics/
    """
    shop_owner = request.user
    
    total_employees = Employee.objects.filter(shop_owner=shop_owner).count()
    active_employees = Employee.objects.filter(shop_owner=shop_owner, is_active=True).count()
    
    # الموظفين حسب الدور
    employees_by_role = Employee.objects.filter(shop_owner=shop_owner).values('role').annotate(
        count=Count('id')
    )
    
    statistics = {
        'total_employees': total_employees,
        'active_employees': active_employees,
        'employees_by_role': {item['role']: item['count'] for item in employees_by_role}
    }
    
    return success_response(
        data=statistics,
        message=t(request, 'employee_statistics_retrieved_successfully'),
        status_code=status.HTTP_200_OK
    )


# Employee Login View
@api_view(['POST'])
@permission_classes([AllowAny])
def employee_login_view(request):
    """
    تسجيل دخول الموظف وإرجاع JWT Token
    POST /api/employee/login/
    Body: {
        "phone_number": "رقم الهاتف",
        "password": "كلمة المرور"
    }
    """
    serializer = EmployeeTokenObtainPairSerializer(data=request.data)
    
    try:
        serializer.is_valid(raise_exception=True)
    except Exception as e:
        errors = serializer.errors if hasattr(serializer, 'errors') else {'detail': str(e)}
        return error_response(
            message=t(request, 'login_failed'),
            errors=errors,
            status_code=status.HTTP_400_BAD_REQUEST
        )
    
    return success_response(
        data=serializer.validated_data,
        message=t(request, 'login_successful'),
        status_code=status.HTTP_200_OK
    )


# Driver Login View
@api_view(['POST'])
@permission_classes([AllowAny])
def driver_login_view(request):
    """
    تسجيل دخول السائق وإرجاع JWT Token
    POST /api/driver/login/
    Body: {
        "phone_number": "رقم الهاتف",
        "password": "كلمة المرور"
    }
    """
    serializer = DriverTokenObtainPairSerializer(data=request.data)
    
    try:
        serializer.is_valid(raise_exception=True)
    except Exception as e:
        errors = serializer.errors if hasattr(serializer, 'errors') else {'detail': str(e)}
        return error_response(
            message=t(request, 'login_failed'),
            errors=errors,
            status_code=status.HTTP_400_BAD_REQUEST
        )
    
    return success_response(
        data=serializer.validated_data,
        message=t(request, 'login_successful'),
        status_code=status.HTTP_200_OK
    )


# ==================== Customer Auth APIs ====================

@api_view(['POST'])
@permission_classes([AllowAny])
def customer_register_view(request):
    """
    تسجيل عميل جديد
    POST /api/customer/register/
    Body: { "name": "...", "phone_number": "...",   "password": "..." }
    """
    serializer = CustomerRegisterSerializer(data=request.data)
    if serializer.is_valid():
        customer = serializer.save()
        token_serializer = CustomerTokenObtainPairSerializer()
        refresh = token_serializer.get_token(customer)
        return success_response(
            data={
                'refresh': str(refresh),
                'access': str(refresh.access_token),
                'customer': {
                    'id': customer.id,
                    'name': customer.name,
                    'phone_number': customer.phone_number,
                    
                }
            },
            message=t(request, 'registration_successful'),
            status_code=status.HTTP_201_CREATED
        )
    return error_response(
        message=t(request, 'registration_failed'),
        errors=serializer.errors,
        status_code=status.HTTP_400_BAD_REQUEST
    )


@api_view(['POST'])
@permission_classes([AllowAny])
def customer_login_view(request):
    """
    تسجيل دخول العميل
    POST /api/customer/login/
    Body: { "phone_number": "...", "password": "..." }
    """
    serializer = CustomerTokenObtainPairSerializer(data=request.data)
    try:
        serializer.is_valid(raise_exception=True)
    except Exception as e:
        errors = serializer.errors if hasattr(serializer, 'errors') else {'detail': str(e)}
        return error_response(
            message=t(request, 'login_failed'),
            errors=errors,
            status_code=status.HTTP_400_BAD_REQUEST
        )
    return success_response(
        data=serializer.validated_data,
        message=t(request, 'login_successful'),
        status_code=status.HTTP_200_OK
    )


def _get_customer_from_request(request):
    """العميل من الطلب (لـ JWT عميل)"""
    user = request.user
    if isinstance(user, Customer):
        return user
    try:
        return Customer.objects.get(id=user.id)
    except (Customer.DoesNotExist, AttributeError):
        return None


# ==================== Public Shops (for Customer selection) ====================

@api_view(['GET'])
@permission_classes([AllowAny])
def public_shops_list_view(request):
    """
    List active shops (public).
    GET /api/shops/
    """
    shops = ShopOwner.objects.filter(is_active=True).order_by('shop_name', 'shop_number')
    data = [{'id': s.id, 'shop_number': s.shop_number, 'shop_name': s.shop_name} for s in shops]
    return success_response(
        data=data,
        message="shops_retrieved_successfully",
        status_code=status.HTTP_200_OK
    )


# ==================== Customer Shop Selection ====================

@api_view(['POST'])
@permission_classes([IsCustomer])
def customer_select_shop_view(request):
    """
    Link customer to a shop to allow creating orders.
    POST /api/customer/select-shop/
    Body: { "shop_owner_id": 1 } or { "shop_number": "12345" }
    """
    customer = _get_customer_from_request(request)
    if not customer:
        return error_response(message=t(request, 'customer_not_found'), status_code=status.HTTP_404_NOT_FOUND)

    shop_owner_id = request.data.get('shop_owner_id') or request.data.get('shop_id')
    shop_number = request.data.get('shop_number')

    if shop_owner_id:
        shop = ShopOwner.objects.filter(id=shop_owner_id, is_active=True).first()
    elif shop_number:
        shop = ShopOwner.objects.filter(shop_number=shop_number, is_active=True).first()
    else:
        return error_response(
            message=t(request, 'invalid_data'),
            errors={'shop': 'يرجى إرسال shop_owner_id أو shop_number لاختيار المحل.'},
            status_code=status.HTTP_400_BAD_REQUEST
        )

    if not shop:
        return error_response(
            message=t(request, 'not_found'),
            errors={'shop': 'المحل غير موجود.'},
            status_code=status.HTTP_404_NOT_FOUND
        )

    customer.shop_owner = shop
    customer.save()

    return success_response(
        data={'shop_owner_id': shop.id, 'shop_number': shop.shop_number, 'shop_name': shop.shop_name},
        message="تم اختيار المحل بنجاح.",
        status_code=status.HTTP_200_OK
    )


# ==================== Customer Orders (طلبات العميل - الطلب كأول رسالة) ====================

@api_view(['GET', 'POST'])
@permission_classes([IsCustomer])
def customer_orders_list_create_view(request):
    """
    قائمة طلبات العميل وإنشاء طلب جديد (الرسالة الأولى = الفاتورة: اسم، عنوان، بند 1، 2، 3، ...)
    GET /api/customer/orders/ - قائمة طلباتي
    POST /api/customer/orders/ - إنشاء طلب (يملأ النموذج ويبعث للمحل)
    """
    customer = _get_customer_from_request(request)
    if not customer:
        return error_response(message=t(request, 'customer_not_found'), status_code=status.HTTP_404_NOT_FOUND)
    
    if request.method == 'GET':
        orders = Order.objects.filter(customer=customer).order_by('-created_at')
        serializer = OrderSerializer(orders, many=True, context={'request': request})
        return success_response(
            data=serializer.data,
            message=t(request, 'orders_retrieved_successfully'),
            status_code=status.HTTP_200_OK
        )
    
    elif request.method == 'POST':
        serializer = CustomerOrderCreateSerializer(
            data=request.data,
            context={'customer': customer, 'request': request}
        )
        if serializer.is_valid():
            order = serializer.save()
            response_serializer = OrderSerializer(order, context={'request': request})
            try:
                notify_new_order(order.shop_owner_id, response_serializer.data)
            except Exception as e:
                print(f"new_order WebSocket error: {e}")
            return success_response(
                data=response_serializer.data,
                message=t(request, 'order_created_successfully'),
                status_code=status.HTTP_201_CREATED
            )
        return error_response(
            message=t(request, 'invalid_data'),
            errors=serializer.errors,
            status_code=status.HTTP_400_BAD_REQUEST
        )


@api_view(['POST'])
@permission_classes([IsCustomer])
def customer_order_confirm_view(request, order_id):
    """
    تأكيد الطلب بعد التسعير (العميل يضغط زرار تأكيد)
    POST /api/customer/orders/{id}/confirm/
    """
    customer = _get_customer_from_request(request)
    if not customer:
        return error_response(message=t(request, 'customer_not_found'), status_code=status.HTTP_404_NOT_FOUND)
    
    try:
        order = Order.objects.get(id=order_id, customer=customer)
    except Order.DoesNotExist:
        return error_response(
            message=t(request, 'order_not_found'),
            status_code=status.HTTP_404_NOT_FOUND
        )
    
    if order.status != 'pending_customer_confirm':
        return error_response(
            message=t(request, 'order_not_pending_confirm'),
            status_code=status.HTTP_400_BAD_REQUEST
        )
    
    order.status = 'confirmed'
    order.save()
    
    response_serializer = OrderSerializer(order, context={'request': request})
    try:
        notify_order_update(
            shop_owner_id=order.shop_owner_id,
            customer_id=order.customer_id,
            driver_id=order.driver_id,
            order_data=response_serializer.data
        )
    except Exception as e:
        print(f"WebSocket notification error: {e}")
    
    return success_response(
        data=response_serializer.data,
        message=t(request, 'order_confirmed_successfully'),
        status_code=status.HTTP_200_OK
    )


@api_view(['GET', 'PUT'])
@permission_classes([IsCustomer])
def customer_profile_view(request):
    """
    عرض وتحديث ملف العميل
    GET/PUT /api/customer/profile/
    """
    # التحقق من أن المستخدم هو عميل
    user = request.user
    
    # إذا كان المستخدم Customer مباشرة من الـ authentication
    if isinstance(user, Customer):
        customer = user
    else:
        # محاولة جلب العميل بالـ ID
        try:
            customer = Customer.objects.get(id=user.id)
        except Customer.DoesNotExist:
            return error_response(message=t(request, 'customer_not_found'), status_code=status.HTTP_404_NOT_FOUND)
    
    if not customer:
        return error_response(message=t(request, 'customer_not_found'), status_code=status.HTTP_404_NOT_FOUND)
    
    if request.method == 'GET':
        serializer = CustomerSerializer(customer, context={'request': request})
        return success_response(data=serializer.data, message=t(request, 'profile_retrieved_successfully'))
    
    elif request.method == 'PUT':
        data = request.data.copy()
        if 'password' in data:
            data.pop('password')  # تغيير كلمة المرور له endpoint منفصل
        for field in ['name',  'profile_image']:
            if field in data:
                setattr(customer, field, data[field])
        customer.save()
        serializer = CustomerSerializer(customer, context={'request': request})
        return success_response(data=serializer.data, message=t(request, 'profile_updated_successfully'))


# ==================== Customer Address APIs ====================

@api_view(['GET', 'POST'])
@permission_classes([IsCustomer])
def customer_address_list_view(request):
    """
    قائمة عناوين العميل وإضافة عنوان جديد
    GET /api/customer/addresses/
    POST /api/customer/addresses/
    """
    customer_id = request.user.id  # أو من JWT
    try:
        customer = Customer.objects.get(id=customer_id)
    except Customer.DoesNotExist:
        return error_response(message=t(request, 'customer_not_found'), status_code=status.HTTP_404_NOT_FOUND)
    
    if request.method == 'GET':
        addresses = customer.addresses.all()
        serializer = CustomerAddressSerializer(addresses, many=True)
        return success_response(data=serializer.data, message=t(request, 'addresses_retrieved_successfully'))
    
    elif request.method == 'POST':
        serializer = CustomerAddressSerializer(data=request.data)
        if serializer.is_valid():
            serializer.save(customer=customer)
            return success_response(data=serializer.data, message=t(request, 'address_added_successfully'), status_code=status.HTTP_201_CREATED)
        return error_response(message=t(request, 'invalid_data'), errors=serializer.errors, status_code=status.HTTP_400_BAD_REQUEST)


@api_view(['GET', 'PUT', 'DELETE'])
@permission_classes([IsCustomer])
def customer_address_detail_view(request, address_id):
    """
    عرض، تحديث، حذف عنوان
    GET/PUT/DELETE /api/customer/addresses/{id}/
    """
    customer_id = request.user.id
    try:
        address = CustomerAddress.objects.get(id=address_id, customer_id=customer_id)
    except CustomerAddress.DoesNotExist:
        return error_response(message=t(request, 'address_not_found'), status_code=status.HTTP_404_NOT_FOUND)
    
    if request.method == 'GET':
        serializer = CustomerAddressSerializer(address)
        return success_response(data=serializer.data, message=t(request, 'address_retrieved_successfully'))
    
    elif request.method == 'PUT':
        serializer = CustomerAddressSerializer(address, data=request.data, partial=True)
        if serializer.is_valid():
            serializer.save()
            return success_response(data=serializer.data, message=t(request, 'address_updated_successfully'))
        return error_response(message=t(request, 'invalid_data'), errors=serializer.errors, status_code=status.HTTP_400_BAD_REQUEST)
    
    elif request.method == 'DELETE':
        address.delete()
        return success_response(message=t(request, 'address_deleted_successfully'))


# ==================== Category APIs ====================

@api_view(['GET', 'POST'])
@permission_classes([IsShopOwner])
def category_list_view(request):
    """
    قائمة التصنيفات
    GET /api/shop/categories/
    POST /api/shop/categories/
    """
    shop_owner = request.user
    
    if request.method == 'GET':
        categories = Category.objects.filter(shop_owner=shop_owner, is_active=True)
        serializer = CategorySerializer(categories, many=True, context={'request': request})
        return success_response(data=serializer.data, message=t(request, 'categories_retrieved_successfully'))
    
    elif request.method == 'POST':
        serializer = CategorySerializer(data=request.data)
        if serializer.is_valid():
            serializer.save(shop_owner=shop_owner)
            return success_response(data=serializer.data, message=t(request, 'category_added_successfully'), status_code=status.HTTP_201_CREATED)
        return error_response(message=t(request, 'invalid_data'), errors=serializer.errors, status_code=status.HTTP_400_BAD_REQUEST)


@api_view(['GET', 'PUT', 'DELETE'])
@permission_classes([IsShopOwner])
def category_detail_view(request, category_id):
    """
    عرض، تحديث، حذف تصنيف
    GET/PUT/DELETE /api/shop/categories/{id}/
    """
    shop_owner = request.user
    try:
        category = Category.objects.get(id=category_id, shop_owner=shop_owner)
    except Category.DoesNotExist:
        return error_response(message=t(request, 'category_not_found'), status_code=status.HTTP_404_NOT_FOUND)
    
    if request.method == 'GET':
        serializer = CategorySerializer(category, context={'request': request})
        return success_response(data=serializer.data, message=t(request, 'category_retrieved_successfully'))
    
    elif request.method == 'PUT':
        serializer = CategorySerializer(category, data=request.data, partial=True)
        if serializer.is_valid():
            serializer.save()
            return success_response(data=serializer.data, message=t(request, 'category_updated_successfully'))
        return error_response(message=t(request, 'invalid_data'), errors=serializer.errors, status_code=status.HTTP_400_BAD_REQUEST)
    
    elif request.method == 'DELETE':
        category.delete()
        return success_response(message=t(request, 'category_deleted_successfully'))


# ==================== Order Rating APIs ====================

@api_view(['POST'])
@permission_classes([IsCustomer])
def order_rating_create_view(request):
    """
    تقييم طلب
    POST /api/orders/rate/
    Body: { "order_id": 1, "shop_rating": 5, "driver_rating": 4, "food_rating": 5, "comment": "..." }
    """
    serializer = OrderRatingCreateSerializer(data=request.data)
    if not serializer.is_valid():
        return error_response(message=t(request, 'invalid_data'), errors=serializer.errors, status_code=status.HTTP_400_BAD_REQUEST)
    
    data = serializer.validated_data
    order_id = data['order_id']
    
    try:
        order = Order.objects.get(id=order_id)
    except Order.DoesNotExist:
        return error_response(message=t(request, 'order_not_found'), status_code=status.HTTP_404_NOT_FOUND)
    
    if order.status != 'delivered':
        return error_response(message=t(request, 'cannot_rate_an_incomplete_order'), status_code=status.HTTP_400_BAD_REQUEST)
    
    if hasattr(order, 'rating'):
        return error_response(message=t(request, 'this_order_has_already_been_rated'), status_code=status.HTTP_400_BAD_REQUEST)
    
    rating = OrderRating.objects.create(
        order=order,
        customer=order.customer,
        shop_rating=data['shop_rating'],
        driver_rating=data.get('driver_rating'),
        food_rating=data.get('food_rating'),
        comment=data.get('comment', '')
    )
    
    # تحديث تقييم السائق إن وجد
    if order.driver and data.get('driver_rating'):
        driver = order.driver
        avg_rating = OrderRating.objects.filter(
            order__driver=driver
        ).aggregate(avg=Avg('driver_rating'))['avg']
        if avg_rating:
            driver.rating = round(avg_rating, 2)
            driver.save()
    
    response_serializer = OrderRatingSerializer(rating)
    return success_response(data=response_serializer.data, message=t(request, 'rating_added_successfully'), status_code=status.HTTP_201_CREATED)


@api_view(['GET'])
@permission_classes([IsShopOwner])
def order_rating_view(request, order_id):
    """
    عرض تقييم طلب
    GET /api/orders/{id}/rating/
    """
    try:
        rating = OrderRating.objects.get(order_id=order_id)
    except OrderRating.DoesNotExist:
        return error_response(message=t(request, 'no_rating_found_for_this_order'), status_code=status.HTTP_404_NOT_FOUND)
    
    serializer = OrderRatingSerializer(rating)
    return success_response(data=serializer.data, message=t(request, 'rating_retrieved_successfully'))


# ==================== Payment Method APIs ====================

@api_view(['GET', 'POST'])
@permission_classes([IsCustomer])
def payment_method_list_view(request):
    """
    قائمة طرق الدفع وإضافة طريقة جديدة
    GET /api/customer/payment-methods/
    POST /api/customer/payment-methods/
    """
    customer_id = request.user.id
    try:
        customer = Customer.objects.get(id=customer_id)
    except Customer.DoesNotExist:
        return error_response(message=t(request, 'customer_not_found'), status_code=status.HTTP_404_NOT_FOUND)
    
    if request.method == 'GET':
        methods = customer.payment_methods.all()
        serializer = PaymentMethodSerializer(methods, many=True)
        return success_response(data=serializer.data, message=t(request, 'payment_methods_retrieved_successfully'))
    
    elif request.method == 'POST':
        serializer = PaymentMethodCreateSerializer(data=request.data)
        if serializer.is_valid():
            data = serializer.validated_data
            method = PaymentMethod.objects.create(
                customer=customer,
                card_type=data['card_type'],
                last_four_digits=data['card_number'][-4:],
                card_holder_name=data['card_holder_name'],
                expiry_month=data['expiry_month'],
                expiry_year=data['expiry_year'],
                is_default=data.get('is_default', False)
            )
            response_serializer = PaymentMethodSerializer(method)
            return success_response(data=response_serializer.data, message=t(request, 'payment_method_added_successfully'), status_code=status.HTTP_201_CREATED)
        return error_response(message=t(request, 'invalid_data'), errors=serializer.errors, status_code=status.HTTP_400_BAD_REQUEST)


@api_view(['DELETE'])
@permission_classes([IsCustomer])
def payment_method_delete_view(request, method_id):
    """
    حذف طريقة دفع
    DELETE /api/customer/payment-methods/{id}/
    """
    customer_id = request.user.id
    try:
        method = PaymentMethod.objects.get(id=method_id, customer_id=customer_id)
    except PaymentMethod.DoesNotExist:
        return error_response(message=t(request, 'payment_method_not_found'), status_code=status.HTTP_404_NOT_FOUND)
    
    method.delete()
    return success_response(message=t(request, 'payment_method_deleted_successfully'))


# ==================== Notification APIs ====================

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def notification_list_view(request):
    """
    قائمة الإشعارات
    GET /api/notifications/
    """
    user = request.user
    # تحديد نوع المستخدم
    notifications = Notification.objects.none()
    
    if isinstance(user, ShopOwner):
        notifications = Notification.objects.filter(shop_owner=user)
    elif isinstance(user, Customer):
        notifications = Notification.objects.filter(customer=user)
    elif isinstance(user, Employee):
        notifications = Notification.objects.filter(employee=user)
    elif isinstance(user, Driver):
        notifications = Notification.objects.filter(driver=user)
    else:
        # محاولة من customer_id في JWT
        try:
            customer = Customer.objects.get(id=user.id)
            notifications = Notification.objects.filter(customer=customer)
        except:
            pass
    
    serializer = NotificationSerializer(notifications[:50], many=True)
    unread_count = notifications.filter(is_read=False).count()
    return success_response(
        data={'notifications': serializer.data, 'unread_count': unread_count},
        message=t(request, 'notifications_retrieved_successfully')
    )


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def notification_mark_read_view(request, notification_id):
    """
    تحديد إشعار كمقروء
    POST /api/notifications/{id}/read/
    """
    try:
        notification = Notification.objects.get(id=notification_id)
        notification.is_read = True
        notification.save()
        return success_response(message=t(request, 'notification_marked_as_read'))
    except Notification.DoesNotExist:
        return error_response(message=t(request, 'notification_not_found'), status_code=status.HTTP_404_NOT_FOUND)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def notification_mark_all_read_view(request):
    """
    تحديد جميع الإشعارات كمقروءة
    POST /api/notifications/read-all/
    """
    user = request.user
    if isinstance(user, ShopOwner):
        Notification.objects.filter(shop_owner=user, is_read=False).update(is_read=True)
    elif isinstance(user, Customer):
        Notification.objects.filter(customer=user, is_read=False).update(is_read=True)
    return success_response(message=t(request, 'all_notifications_marked_as_read'))


# ==================== Cart APIs ====================

@api_view(['GET'])
@permission_classes([IsCustomer])
def cart_view(request, shop_id):
    """
    عرض سلة التسوق لمحل معين
    GET /api/cart/{shop_id}/
    """
    customer_id = request.user.id
    try:
        customer = Customer.objects.get(id=customer_id)
    except Customer.DoesNotExist:
        return error_response(message=t(request, 'customer_not_found'), status_code=status.HTTP_404_NOT_FOUND)
    
    cart, created = Cart.objects.get_or_create(customer=customer, shop_owner_id=shop_id)
    serializer = CartSerializer(cart, context={'request': request})
    return success_response(data=serializer.data, message=t(request, 'cart_retrieved_successfully'))


@api_view(['POST'])
@permission_classes([IsCustomer])
def cart_add_item_view(request, shop_id):
    """
    إضافة منتج للسلة
    POST /api/cart/{shop_id}/add/
    Body: { "product_id": 1, "quantity": 2, "notes": "..." }
    """
    customer_id = request.user.id
    try:
        customer = Customer.objects.get(id=customer_id)
    except Customer.DoesNotExist:
        return error_response(message=t(request, 'customer_not_found'), status_code=status.HTTP_404_NOT_FOUND)
    
    serializer = AddToCartSerializer(data=request.data)
    if not serializer.is_valid():
        return error_response(message=t(request, 'invalid_data'), errors=serializer.errors, status_code=status.HTTP_400_BAD_REQUEST)
    
    data = serializer.validated_data
    try:
        product = Product.objects.get(id=data['product_id'], shop_owner_id=shop_id, is_available=True)
    except Product.DoesNotExist:
        return error_response(message=t(request, 'product_not_found_or_unavailable'), status_code=status.HTTP_404_NOT_FOUND)
    
    cart, _ = Cart.objects.get_or_create(customer=customer, shop_owner_id=shop_id)
    
    cart_item, created = CartItem.objects.get_or_create(
        cart=cart,
        product=product,
        defaults={'quantity': data['quantity'], 'notes': data.get('notes', '')}
    )
    
    if not created:
        cart_item.quantity += data['quantity']
        if data.get('notes'):
            cart_item.notes = data['notes']
        cart_item.save()
    
    cart_serializer = CartSerializer(cart, context={'request': request})
    return success_response(data=cart_serializer.data, message=t(request, 'product_added_to_cart_successfully'))


@api_view(['PUT', 'DELETE'])
@permission_classes([IsCustomer])
def cart_item_view(request, shop_id, item_id):
    """
    تحديث أو حذف عنصر من السلة
    PUT /api/cart/{shop_id}/items/{item_id}/
    DELETE /api/cart/{shop_id}/items/{item_id}/
    """
    customer_id = request.user.id
    try:
        cart = Cart.objects.get(customer_id=customer_id, shop_owner_id=shop_id)
        cart_item = cart.items.get(id=item_id)
    except (Cart.DoesNotExist, CartItem.DoesNotExist):
        return error_response(message=t(request, 'item_not_found'), status_code=status.HTTP_404_NOT_FOUND)
    
    if request.method == 'PUT':
        serializer = UpdateCartItemSerializer(data=request.data)
        if not serializer.is_valid():
            return error_response(message=t(request, 'invalid_data'), errors=serializer.errors, status_code=status.HTTP_400_BAD_REQUEST)
        
        data = serializer.validated_data
        if data['quantity'] == 0:
            cart_item.delete()
        else:
            cart_item.quantity = data['quantity']
            if 'notes' in data:
                cart_item.notes = data['notes']
            cart_item.save()
    
    elif request.method == 'DELETE':
        cart_item.delete()
    
    cart.refresh_from_db()
    cart_serializer = CartSerializer(cart, context={'request': request})
    return success_response(data=cart_serializer.data, message=t(request, 'cart_updated_successfully'))


@api_view(['DELETE'])
@permission_classes([IsCustomer])
def cart_clear_view(request, shop_id):
    """
    تفريغ السلة
    DELETE /api/cart/{shop_id}/clear/
    """
    customer_id = request.user.id
    try:
        cart = Cart.objects.get(customer_id=customer_id, shop_owner_id=shop_id)
        cart.items.all().delete()
        return success_response(message=t(request, 'cart_cleared_successfully'))
    except Cart.DoesNotExist:
        return error_response(message=t(request, 'cart_not_found'), status_code=status.HTTP_404_NOT_FOUND)


# ==================== Driver Location APIs ====================

@api_view(['PUT'])
@permission_classes([IsDriver])
def driver_location_update_view(request):
    """
    تحديث موقع السائق
    PUT /api/driver/location/
    Body: { "latitude": 24.7136, "longitude": 46.6753 }
    """
    # نفترض أن السائق مسجل دخول
    driver = request.user
    if not isinstance(driver, Driver):
        try:
            driver = Driver.objects.get(id=request.user.id)
        except:
            return error_response(message=t(request, 'driver_not_found'), status_code=status.HTTP_404_NOT_FOUND)
    
    serializer = DriverLocationUpdateSerializer(data=request.data)
    if not serializer.is_valid():
        return error_response(message=t(request, 'invalid_data'), errors=serializer.errors, status_code=status.HTTP_400_BAD_REQUEST)
    
    driver.current_latitude = serializer.validated_data['latitude']
    driver.current_longitude = serializer.validated_data['longitude']
    driver.location_updated_at = timezone.now()
    driver.save()
    
    return success_response(
        data={
            'latitude': str(driver.current_latitude),
            'longitude': str(driver.current_longitude),
            'updated_at': driver.location_updated_at
        },
        message=t(request, 'location_updated_successfully')
    )


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def order_tracking_view(request, order_id):
    """
    تتبع الطلب (موقع السائق)
    GET /api/orders/{id}/track/
    """
    try:
        order = Order.objects.get(id=order_id)
    except Order.DoesNotExist:
        return error_response(message=t(request, 'order_not_found'), status_code=status.HTTP_404_NOT_FOUND)
    
    if order.status not in ['on_way', 'preparing']:
        return error_response(message=t(request, 'order_is_not_trackable_at_the_moment'), status_code=status.HTTP_400_BAD_REQUEST)
    
    driver = order.driver
    if not driver:
        return error_response(message=t(request, 'no_driver_has_been_assigned_to_the_order'), status_code=status.HTTP_404_NOT_FOUND)
    
    return success_response(
        data={
            'order_id': order.id,
            'order_status': order.status,
            'order_status_display': order.get_status_display(),
            'driver': {
                'id': driver.id,
                'name': driver.name,
                'phone_number': driver.phone_number,
                'latitude': str(driver.current_latitude) if driver.current_latitude else None,
                'longitude': str(driver.current_longitude) if driver.current_longitude else None,
                'location_updated_at': driver.location_updated_at,
            },
            'estimated_delivery_time': order.estimated_delivery_time,
        },
        message=t(request, 'tracking_data_retrieved_successfully')
    )


