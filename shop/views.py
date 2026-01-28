from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.pagination import PageNumberPagination
from django.db.models import Q, Count, Sum, F
from django.utils import timezone
from datetime import timedelta
from .models import ShopStatus, Customer, Driver, Order, ChatMessage, Invoice
from .serializers import (
    ShopStatusSerializer,
    CustomerSerializer,
    CustomerCreateSerializer,
    DriverSerializer,
    DriverCreateSerializer,
    OrderSerializer,
    OrderCreateSerializer,
    ChatMessageSerializer,
    InvoiceSerializer,
    InvoiceCreateSerializer
)
from user.models import ShopOwner
from user.utils import success_response, error_response


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
            "message": "تم جلب الطلبات بنجاح",
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
            "message": "تم جلب العملاء بنجاح",
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
@permission_classes([IsAuthenticated])
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
            message='تم جلب حالة المتجر بنجاح',
            status_code=status.HTTP_200_OK
        )
    
    elif request.method == 'PUT':
        serializer = ShopStatusSerializer(status_obj, data=request.data, partial=True)
        if serializer.is_valid():
            serializer.save()
            return success_response(
                data=serializer.data,
                message='تم تحديث حالة المتجر بنجاح',
                status_code=status.HTTP_200_OK
            )
        return error_response(
            message='بيانات غير صحيحة',
            errors=serializer.errors,
            status_code=status.HTTP_400_BAD_REQUEST
        )


# Customer APIs
@api_view(['GET', 'POST'])
@permission_classes([IsAuthenticated])
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
            message='تم جلب العملاء بنجاح',
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
                message='تم إضافة العميل بنجاح',
                status_code=status.HTTP_201_CREATED
            )
        return error_response(
            message='بيانات غير صحيحة',
            errors=serializer.errors,
            status_code=status.HTTP_400_BAD_REQUEST
        )


@api_view(['GET', 'PUT', 'DELETE'])
@permission_classes([IsAuthenticated])
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
            message='العميل غير موجود',
            status_code=status.HTTP_404_NOT_FOUND
        )
    
    if request.method == 'GET':
        serializer = CustomerSerializer(customer, context={'request': request})
        return success_response(
            data=serializer.data,
            message='تم جلب بيانات العميل بنجاح',
            status_code=status.HTTP_200_OK
        )
    
    elif request.method == 'PUT':
        serializer = CustomerCreateSerializer(customer, data=request.data, partial=True)
        if serializer.is_valid():
            serializer.save()
            response_serializer = CustomerSerializer(customer, context={'request': request})
            return success_response(
                data=response_serializer.data,
                message='تم تحديث بيانات العميل بنجاح',
                status_code=status.HTTP_200_OK
            )
        return error_response(
            message='بيانات غير صحيحة',
            errors=serializer.errors,
            status_code=status.HTTP_400_BAD_REQUEST
        )
    
    elif request.method == 'DELETE':
        customer.delete()
        return success_response(
            message='تم حذف العميل بنجاح',
            status_code=status.HTTP_200_OK
        )


# Driver APIs
@api_view(['GET', 'POST'])
@permission_classes([IsAuthenticated])
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
            message='تم جلب السائقين بنجاح',
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
                message='تم إضافة السائق بنجاح',
                status_code=status.HTTP_201_CREATED
            )
        return error_response(
            message='بيانات غير صحيحة',
            errors=serializer.errors,
            status_code=status.HTTP_400_BAD_REQUEST
        )


@api_view(['GET', 'PUT', 'DELETE'])
@permission_classes([IsAuthenticated])
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
            message='السائق غير موجود',
            status_code=status.HTTP_404_NOT_FOUND
        )
    
    if request.method == 'GET':
        serializer = DriverSerializer(driver, context={'request': request})
        return success_response(
            data=serializer.data,
            message='تم جلب بيانات السائق بنجاح',
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
                message='تم تحديث بيانات السائق بنجاح',
                status_code=status.HTTP_200_OK
            )
        return error_response(
            message='بيانات غير صحيحة',
            errors=serializer.errors,
            status_code=status.HTTP_400_BAD_REQUEST
        )
    
    elif request.method == 'DELETE':
        driver.delete()
        return success_response(
            message='تم حذف السائق بنجاح',
            status_code=status.HTTP_200_OK
        )


# Order APIs
@api_view(['GET', 'POST'])
@permission_classes([IsAuthenticated])
def order_list_view(request):
    """
    عرض قائمة الطلبات وإنشاء طلب جديد
    GET /api/shop/orders/ - عرض قائمة الطلبات
    POST /api/shop/orders/ - إنشاء طلب جديد
    """
    shop_owner = request.user
    
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
            message='تم جلب الطلبات بنجاح',
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
                message='تم إنشاء الطلب بنجاح',
                status_code=status.HTTP_201_CREATED
            )
        return error_response(
            message='بيانات غير صحيحة',
            errors=serializer.errors,
            status_code=status.HTTP_400_BAD_REQUEST
        )


@api_view(['GET', 'PUT', 'DELETE'])
@permission_classes([IsAuthenticated])
def order_detail_view(request, order_id):
    """
    عرض، تحديث، أو حذف طلب
    GET /api/shop/orders/{id}/ - عرض طلب
    PUT /api/shop/orders/{id}/ - تحديث طلب
    DELETE /api/shop/orders/{id}/ - حذف طلب
    """
    shop_owner = request.user
    
    try:
        order = Order.objects.get(id=order_id, shop_owner=shop_owner)
    except Order.DoesNotExist:
        return error_response(
            message='الطلب غير موجود',
            status_code=status.HTTP_404_NOT_FOUND
        )
    
    if request.method == 'GET':
        serializer = OrderSerializer(order, context={'request': request})
        return success_response(
            data=serializer.data,
            message='تم جلب بيانات الطلب بنجاح',
            status_code=status.HTTP_200_OK
        )
    
    elif request.method == 'PUT':
        # تحديث الطلب
        old_driver = order.driver
        
        if 'customer_id' in request.data:
            try:
                customer = Customer.objects.get(id=request.data['customer_id'], shop_owner=shop_owner)
                order.customer = customer
            except Customer.DoesNotExist:
                return error_response(
                    message='العميل غير موجود',
                    status_code=status.HTTP_404_NOT_FOUND
                )
        
        if 'driver_id' in request.data:
            driver_id = request.data['driver_id']
            if driver_id:
                try:
                    driver = Driver.objects.get(id=driver_id, shop_owner=shop_owner)
                    order.driver = driver
                except Driver.DoesNotExist:
                    return error_response(
                        message='السائق غير موجود',
                        status_code=status.HTTP_404_NOT_FOUND
                    )
            else:
                order.driver = None
        
        # تحديث باقي الحقول
        for field in ['status', 'items', 'total_amount', 'delivery_fee', 'address', 'notes']:
            if field in request.data:
                setattr(order, field, request.data[field])
        
        order.save()
        
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
        return success_response(
            data=response_serializer.data,
            message='تم تحديث الطلب بنجاح',
            status_code=status.HTTP_200_OK
        )
    
    elif request.method == 'DELETE':
        order.delete()
        return success_response(
            message='تم حذف الطلب بنجاح',
            status_code=status.HTTP_200_OK
        )


# Chat Message APIs
@api_view(['GET', 'POST'])
@permission_classes([IsAuthenticated])
def order_messages_view(request, order_id):
    """
    عرض وإرسال رسائل المحادثة للطلب
    GET /api/shop/orders/{id}/messages/ - عرض رسائل الطلب
    POST /api/shop/orders/{id}/messages/ - إرسال رسالة جديدة
    """
    shop_owner = request.user
    
    try:
        order = Order.objects.get(id=order_id, shop_owner=shop_owner)
    except Order.DoesNotExist:
        return error_response(
            message='الطلب غير موجود',
            status_code=status.HTTP_404_NOT_FOUND
        )
    
    if request.method == 'GET':
        messages = order.messages.all()
        serializer = ChatMessageSerializer(messages, many=True, context={'request': request})
        return success_response(
            data=serializer.data,
            message='تم جلب الرسائل بنجاح',
            status_code=status.HTTP_200_OK
        )
    
    elif request.method == 'POST':
        data = request.data.copy()
        data['order'] = order.id
        data['sender_type'] = 'shop'  # الرسالة من المحل
        
        serializer = ChatMessageSerializer(data=data, context={'request': request})
        if serializer.is_valid():
            message = ChatMessage.objects.create(
                order=order,
                sender_type='shop',
                message_type=data.get('message_type', 'text'),
                content=data.get('content', ''),
                audio_file=data.get('audio_file'),
                image_file=data.get('image_file')
            )
            # تحديث عدد الرسائل غير المقروءة
            order.unread_messages_count = order.messages.filter(is_read=False, sender_type='customer').count()
            order.save()
            
            response_serializer = ChatMessageSerializer(message, context={'request': request})
            return success_response(
                data=response_serializer.data,
                message='تم إرسال الرسالة بنجاح',
                status_code=status.HTTP_201_CREATED
            )
        return error_response(
            message='بيانات غير صحيحة',
            errors=serializer.errors,
            status_code=status.HTTP_400_BAD_REQUEST
        )


@api_view(['PUT'])
@permission_classes([IsAuthenticated])
def mark_messages_read_view(request, order_id):
    """
    تعليم رسائل الطلب كمقروءة
    PUT /api/shop/orders/{id}/messages/read/
    """
    shop_owner = request.user
    
    try:
        order = Order.objects.get(id=order_id, shop_owner=shop_owner)
    except Order.DoesNotExist:
        return error_response(
            message='الطلب غير موجود',
            status_code=status.HTTP_404_NOT_FOUND
        )
    
    # تعليم جميع رسائل العميل كمقروءة
    ChatMessage.objects.filter(order=order, sender_type='customer', is_read=False).update(is_read=True)
    order.unread_messages_count = 0
    order.save()
    
    return success_response(
        message='تم تعليم الرسائل كمقروءة',
        status_code=status.HTTP_200_OK
    )


# Invoice APIs
@api_view(['GET', 'POST'])
@permission_classes([IsAuthenticated])
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
            message='تم جلب الفواتير بنجاح',
            status_code=status.HTTP_200_OK
        )
    
    elif request.method == 'POST':
        serializer = InvoiceCreateSerializer(data=request.data)
        if serializer.is_valid():
            # إنشاء أو الحصول على العميل
            customer, _ = Customer.objects.get_or_create(
                shop_owner=shop_owner,
                phone_number=serializer.validated_data['phone_number'],
                defaults={
                    'name': serializer.validated_data['customer_name'],
                    'address': serializer.validated_data['address']
                }
            )
            
            # إنشاء رقم فاتورة تلقائي
            import random
            invoice_number = f"INV{shop_owner.shop_number}{random.randint(1000, 9999)}"
            while Invoice.objects.filter(invoice_number=invoice_number).exists():
                invoice_number = f"INV{shop_owner.shop_number}{random.randint(1000, 9999)}"
            
            invoice = Invoice.objects.create(
                shop_owner=shop_owner,
                customer=customer,
                invoice_number=invoice_number,
                items=serializer.validated_data['items'],
                total_amount=serializer.validated_data['amount'],
                delivery_fee=serializer.validated_data.get('delivery', 0),
                address=serializer.validated_data['address'],
                phone_number=serializer.validated_data['phone_number']
            )
            
            response_serializer = InvoiceSerializer(invoice, context={'request': request})
            return success_response(
                data=response_serializer.data,
                message='تم إنشاء الفاتورة بنجاح',
                status_code=status.HTTP_201_CREATED
            )
        return error_response(
            message='بيانات غير صحيحة',
            errors=serializer.errors,
            status_code=status.HTTP_400_BAD_REQUEST
        )


@api_view(['GET', 'PUT'])
@permission_classes([IsAuthenticated])
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
            message='الفاتورة غير موجودة',
            status_code=status.HTTP_404_NOT_FOUND
        )
    
    if request.method == 'GET':
        serializer = InvoiceSerializer(invoice, context={'request': request})
        return success_response(
            data=serializer.data,
            message='تم جلب بيانات الفاتورة بنجاح',
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
            message='تم تحديث حالة الفاتورة بنجاح',
            status_code=status.HTTP_200_OK
        )


# Statistics API
@api_view(['GET'])
@permission_classes([IsAuthenticated])
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
        message='تم جلب الإحصائيات بنجاح',
        status_code=status.HTTP_200_OK
    )
