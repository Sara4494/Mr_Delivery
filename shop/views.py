from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework.response import Response
from rest_framework.pagination import PageNumberPagination
import json
from django.db.models import Q, Count, Sum, F, Avg
from django.utils import timezone
from datetime import timedelta
from .models import (
    ShopStatus, Customer, CustomerAddress, Driver, Order, ChatMessage, 
    Invoice, Employee, Product, Category, OrderRating, PaymentMethod, 
    Notification, Cart, CartItem
)
from .serializers import (
    ShopCategorySerializer,
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
    PublicProductSerializer,
    PublicOfferProductSerializer,
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
from user.models import ShopCategory, ShopOwner
from user.utils import success_response, error_response, build_message_fields, t
from user.otp_service import send_otp as otp_send, verify_otp as otp_verify, normalize_phone
from .websocket_utils import notify_order_update, notify_driver_assigned, notify_new_order, broadcast_chat_message_to_order


class OrderPagination(PageNumberPagination):
    """Pagination Ù„Ù„Ø·Ù„Ø¨Ø§Øª"""
    page_size = 20
    page_size_query_param = 'page_size'
    max_page_size = 100
    
    def get_paginated_response(self, data):
        """ØªØ®ØµÙŠØµ Ø´ÙƒÙ„ Ø§Ù„Ù€ response Ù„Ù„Ù€ pagination"""
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
    """Pagination Ù„Ù„Ø¹Ù…Ù„Ø§Ø¡"""
    page_size = 20
    page_size_query_param = 'page_size'
    max_page_size = 100
    
    def get_paginated_response(self, data):
        """ØªØ®ØµÙŠØµ Ø´ÙƒÙ„ Ø§Ù„Ù€ response Ù„Ù„Ù€ pagination"""
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


def _is_true_query_value(value):
    """ØªØ­ÙˆÙŠÙ„ Ù‚ÙŠÙ…Ø© query param Ø¥Ù„Ù‰ bool."""
    return str(value).lower() in {'1', 'true', 'yes', 'on'}


STAFF_TYPE_EMPLOYEE = 'employee'
STAFF_TYPE_DRIVER = 'driver'
VALID_STAFF_TYPES = {STAFF_TYPE_EMPLOYEE, STAFF_TYPE_DRIVER}


def _normalize_staff_type(value, allow_all=False):
    staff_type = (value or '').strip().lower()
    if not staff_type and allow_all:
        return 'all'
    if not staff_type:
        return None

    allowed_values = set(VALID_STAFF_TYPES)
    if allow_all:
        allowed_values.add('all')
    if staff_type not in allowed_values:
        return None
    return staff_type


def _staff_type_validation_error(request, allow_all=False):
    allowed_values = 'employee, driver, all' if allow_all else 'employee, driver'
    return error_response(
        message=t(request, 'invalid_data'),
        errors={'staff_type': f'Invalid staff_type. Allowed values: {allowed_values}.'},
        status_code=status.HTTP_400_BAD_REQUEST
    )


def _staff_orders_queryset(shop_owner, member, staff_type):
    queryset = Order.objects.filter(shop_owner=shop_owner).exclude(status='cancelled')
    if staff_type == STAFF_TYPE_EMPLOYEE:
        return queryset.filter(employee=member)
    return queryset.filter(driver=member)


def _to_float(value):
    return float(value) if value is not None else 0.0


def _build_staff_metrics(shop_owner, member, staff_type):
    today = timezone.localdate()
    week_start = today - timedelta(days=today.weekday())
    month_start = today.replace(day=1)

    orders_qs = _staff_orders_queryset(shop_owner, member, staff_type)
    today_orders_qs = orders_qs.filter(created_at__date=today)
    week_orders_qs = orders_qs.filter(created_at__date__gte=week_start)
    month_orders_qs = orders_qs.filter(created_at__date__gte=month_start)

    started_today_at = today_orders_qs.order_by('created_at').values_list('created_at', flat=True).first()
    started_today_time = (
        timezone.localtime(started_today_at).strftime('%H:%M')
        if started_today_at
        else None
    )

    metrics = {
        'total_orders': orders_qs.count(),
        'daily_orders_count': today_orders_qs.count(),
        'weekly_orders_count': week_orders_qs.count(),
        'monthly_orders_count': month_orders_qs.count(),
        'started_today_at': started_today_at,
        'started_today_time': started_today_time,
    }

    if staff_type == STAFF_TYPE_EMPLOYEE:
        delivered_qs = orders_qs.filter(status='delivered')
        metrics.update({
            'daily_sales': _to_float(
                delivered_qs.filter(created_at__date=today).aggregate(total=Sum('total_amount'))['total']
            ),
            'weekly_sales': _to_float(
                delivered_qs.filter(created_at__date__gte=week_start).aggregate(total=Sum('total_amount'))['total']
            ),
            'monthly_sales': _to_float(
                delivered_qs.filter(created_at__date__gte=month_start).aggregate(total=Sum('total_amount'))['total']
            ),
            'metric_type': 'sales',
        })
        metrics['daily_value'] = metrics['daily_sales']
        metrics['weekly_value'] = metrics['weekly_sales']
        metrics['monthly_value'] = metrics['monthly_sales']
    else:
        metrics.update({
            'daily_sales': None,
            'weekly_sales': None,
            'monthly_sales': None,
            'metric_type': 'orders',
        })
        metrics['daily_value'] = metrics['daily_orders_count']
        metrics['weekly_value'] = metrics['weekly_orders_count']
        metrics['monthly_value'] = metrics['monthly_orders_count']

    return metrics


def _serialize_staff_member(member, staff_type, request):
    shop_owner = request.user
    metrics = _build_staff_metrics(shop_owner, member, staff_type)

    if staff_type == STAFF_TYPE_EMPLOYEE:
        data = dict(EmployeeSerializer(member, context={'request': request}).data)
        data['staff_type'] = STAFF_TYPE_EMPLOYEE
        data['is_blocked'] = not member.is_active
        data['status'] = 'active' if member.is_active else 'blocked'
        data['status_display'] = 'نشط' if member.is_active else 'محظور'
        data['job_title'] = data.get('role_display')
        data.update(metrics)
        return data

    data = dict(DriverSerializer(member, context={'request': request}).data)
    data['staff_type'] = STAFF_TYPE_DRIVER
    data['is_blocked'] = member.status == 'offline'
    data['job_title'] = 'سائق'
    data.update(metrics)
    return data


def _get_staff_member(shop_owner, staff_type, staff_id):
    if staff_type == STAFF_TYPE_EMPLOYEE:
        try:
            return Employee.objects.get(id=staff_id, shop_owner=shop_owner), None
        except Employee.DoesNotExist:
            return None, 'employee_not_found'

    try:
        return Driver.objects.get(id=staff_id, shop_owner=shop_owner), None
    except Driver.DoesNotExist:
        return None, 'driver_not_found'


def _coerce_staff_id(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _parse_blocked_flag(request):
    raw_value = request.data.get('blocked', None)
    if raw_value is None:
        raw_value = request.query_params.get('blocked', None)
    if raw_value is None:
        return True
    if isinstance(raw_value, bool):
        return raw_value
    return _is_true_query_value(raw_value)


def _clean_staff_payload(request):
    payload = request.data.copy()
    payload.pop('staff_type', None)
    payload.pop('staff_id', None)
    payload.pop('blocked', None)
    return payload


def _driver_phone_variants(phone_number):
    raw = str(phone_number or '').strip()
    normalized = normalize_phone(raw)
    variants = {raw, normalized}
    if normalized.startswith('+20'):
        variants.add(normalized[1:])  # 20xxxxxxxxxx
        variants.add('0' + normalized[3:])  # 01xxxxxxxxx
    return [v for v in variants if v]


def _invite_driver(request, shop_owner, payload):
    phone_number = payload.get('phone_number')
    if not phone_number:
        return error_response(
            message=t(request, 'phone_number_is_required'),
            status_code=status.HTTP_400_BAD_REQUEST
        )

    phone_candidates = _driver_phone_variants(phone_number)
    normalized_phone = normalize_phone(phone_number)
    if not normalized_phone:
        return error_response(
            message=t(request, 'invalid_data'),
            errors={'phone_number': ['Invalid phone number.']},
            status_code=status.HTTP_400_BAD_REQUEST
        )

    driver = Driver.objects.filter(shop_owner=shop_owner, phone_number__in=phone_candidates).first()
    if driver and driver.status != 'pending':
        return error_response(
            message='Driver already exists and is not pending invitation.',
            status_code=status.HTTP_400_BAD_REQUEST
        )

    if driver is None:
        invite_name = payload.get('name') or f'Driver {normalized_phone[-4:]}'
        driver = Driver.objects.create(
            shop_owner=shop_owner,
            name=invite_name,
            phone_number=normalized_phone,
            status='pending',
            password=''
        )
    else:
        if payload.get('name'):
            driver.name = payload.get('name')
        driver.phone_number = normalized_phone
        driver.status = 'pending'
        driver.save()

    send_ok, send_msg = otp_send(normalized_phone)
    if not send_ok:
        return error_response(
            message=str(send_msg),
            status_code=status.HTTP_400_BAD_REQUEST
        )

    response_data = _serialize_staff_member(driver, STAFF_TYPE_DRIVER, request)
    response_data['invitation_sent'] = True
    response_data['invitation_channel'] = 'whatsapp_otp'
    response_data['invitation_note'] = 'Driver should respond using /api/driver/invitation/respond/'
    return success_response(
        data=response_data,
        message='Driver invitation sent successfully.',
        status_code=status.HTTP_201_CREATED
    )


@api_view(['GET', 'POST', 'PUT'])
@permission_classes([IsShopOwner])
def staff_view(request):
    """
    Endpoint Ù…ÙˆØ­Ø¯ Ù„Ù„Ù…ÙˆØ¸ÙÙŠÙ† ÙˆØ§Ù„Ø³Ø§Ø¦Ù‚ÙŠÙ†.
    GET /api/shop/staff/ -> Ø§Ù„Ù‚Ø§Ø¦Ù…Ø© (staff_type=all|employee|driver) Ø£Ùˆ ØªÙØ§ØµÙŠÙ„ Ø¹Ù†ØµØ± ÙˆØ§Ø­Ø¯ (staff_id)
    POST /api/shop/staff/ -> Ø¥Ø¶Ø§ÙØ© Ù…ÙˆØ¸Ù/Ø³Ø§Ø¦Ù‚ Ø¬Ø¯ÙŠØ¯ (staff_type Ù…Ø·Ù„ÙˆØ¨)
    PUT /api/shop/staff/ -> ØªØ­Ø¯ÙŠØ« Ù…ÙˆØ¸Ù/Ø³Ø§Ø¦Ù‚ (staff_type + staff_id)
    """
    shop_owner = request.user

    if request.method == 'GET':
        staff_type = _normalize_staff_type(request.query_params.get('staff_type'), allow_all=True)
        if not staff_type:
            return _staff_type_validation_error(request, allow_all=True)

        staff_id = request.query_params.get('staff_id')
        if staff_id is not None:
            if staff_type not in VALID_STAFF_TYPES:
                return _staff_type_validation_error(request)

            staff_id = _coerce_staff_id(staff_id)
            if staff_id is None:
                return error_response(
                    message=t(request, 'invalid_data'),
                    errors={'staff_id': ['staff_id must be an integer.']},
                    status_code=status.HTTP_400_BAD_REQUEST
                )

            staff_member, not_found_message = _get_staff_member(shop_owner, staff_type, staff_id)
            if not staff_member:
                return error_response(
                    message=t(request, not_found_message),
                    status_code=status.HTTP_404_NOT_FOUND
                )

            detail_message = (
                'employee_data_retrieved_successfully'
                if staff_type == STAFF_TYPE_EMPLOYEE
                else 'driver_data_retrieved_successfully'
            )
            return success_response(
                data=_serialize_staff_member(staff_member, staff_type, request),
                message=t(request, detail_message),
                status_code=status.HTTP_200_OK
            )

        staff_items = []
        requested_types = VALID_STAFF_TYPES if staff_type == 'all' else {staff_type}

        if STAFF_TYPE_EMPLOYEE in requested_types:
            employee_queryset = Employee.objects.filter(shop_owner=shop_owner).order_by('-updated_at')
            role_filter = request.query_params.get('role')
            is_active_filter = request.query_params.get('is_active')
            if role_filter:
                employee_queryset = employee_queryset.filter(role=role_filter)
            if is_active_filter is not None:
                employee_queryset = employee_queryset.filter(is_active=_is_true_query_value(is_active_filter))
            for employee in employee_queryset:
                staff_items.append((employee.updated_at, _serialize_staff_member(employee, STAFF_TYPE_EMPLOYEE, request)))

        if STAFF_TYPE_DRIVER in requested_types:
            driver_queryset = Driver.objects.filter(shop_owner=shop_owner).order_by('-updated_at')
            status_filter = request.query_params.get('status')
            if status_filter:
                driver_queryset = driver_queryset.filter(status=status_filter)
            for driver in driver_queryset:
                staff_items.append((driver.updated_at, _serialize_staff_member(driver, STAFF_TYPE_DRIVER, request)))

        staff_items.sort(key=lambda item: item[0], reverse=True)
        staff_results = [item[1] for item in staff_items]

        summary = {
            'total_staff': len(staff_results),
            'total_employees': Employee.objects.filter(shop_owner=shop_owner).count(),
            'active_employees': Employee.objects.filter(shop_owner=shop_owner, is_active=True).count(),
            'blocked_employees': Employee.objects.filter(shop_owner=shop_owner, is_active=False).count(),
            'total_drivers': Driver.objects.filter(shop_owner=shop_owner).count(),
            'available_drivers': Driver.objects.filter(shop_owner=shop_owner, status='available').count(),
            'active_drivers': Driver.objects.filter(shop_owner=shop_owner, status__in=['available', 'busy']).count(),
            'blocked_drivers': Driver.objects.filter(shop_owner=shop_owner, status='offline').count(),
        }

        if staff_type == STAFF_TYPE_EMPLOYEE:
            summary['selected_total_count'] = summary['total_employees']
            summary['selected_active_count'] = summary['active_employees']
        elif staff_type == STAFF_TYPE_DRIVER:
            summary['selected_total_count'] = summary['total_drivers']
            summary['selected_active_count'] = summary['active_drivers']
        else:
            summary['selected_total_count'] = summary['total_staff']
            summary['selected_active_count'] = summary['active_employees'] + summary['active_drivers']

        if staff_type == STAFF_TYPE_EMPLOYEE:
            message_key = 'employees_retrieved_successfully'
        elif staff_type == STAFF_TYPE_DRIVER:
            message_key = 'drivers_retrieved_successfully'
        else:
            message_key = 'staff_retrieved_successfully'

        return success_response(
            data={'summary': summary, 'results': staff_results},
            message=t(request, message_key),
            status_code=status.HTTP_200_OK
        )

    if request.method == 'POST':
        staff_type = _normalize_staff_type(request.data.get('staff_type'))
        if not staff_type:
            return _staff_type_validation_error(request)

        payload = _clean_staff_payload(request)
        if staff_type == STAFF_TYPE_DRIVER:
            return _invite_driver(request, shop_owner, payload)

        if staff_type == STAFF_TYPE_EMPLOYEE:
            serializer = EmployeeCreateSerializer(
                data=payload,
                context={'shop_owner': shop_owner, 'request': request}
            )
            success_message = 'employee_added_successfully'

        if serializer.is_valid():
            staff_member = serializer.save()
            return success_response(
                data=_serialize_staff_member(staff_member, staff_type, request),
                message=t(request, success_message),
                status_code=status.HTTP_201_CREATED
            )
        return error_response(
            message=t(request, 'invalid_data'),
            errors=serializer.errors,
            status_code=status.HTTP_400_BAD_REQUEST
        )

    staff_type = _normalize_staff_type(
        request.data.get('staff_type') or request.query_params.get('staff_type')
    )
    if not staff_type:
        return _staff_type_validation_error(request)

    staff_id = _coerce_staff_id(
        request.data.get('staff_id') or request.query_params.get('staff_id')
    )
    if staff_id is None:
        return error_response(
            message=t(request, 'invalid_data'),
            errors={'staff_id': ['staff_id is required and must be an integer.']},
            status_code=status.HTTP_400_BAD_REQUEST
        )

    staff_member, not_found_message = _get_staff_member(shop_owner, staff_type, staff_id)
    if not staff_member:
        return error_response(
            message=t(request, not_found_message),
            status_code=status.HTTP_404_NOT_FOUND
        )

    payload = _clean_staff_payload(request)
    if staff_type == STAFF_TYPE_EMPLOYEE:
        serializer = EmployeeUpdateSerializer(staff_member, data=payload, partial=True)
        success_message = 'employee_data_updated_successfully'
    else:
        serializer = DriverCreateSerializer(staff_member, data=payload, partial=True)
        success_message = 'driver_data_updated_successfully'

    if serializer.is_valid():
        serializer.save()
        if staff_type == STAFF_TYPE_DRIVER:
            staff_member.current_orders_count = staff_member.orders.filter(
                status__in=['new', 'preparing', 'on_way']
            ).count()
            staff_member.save()

        return success_response(
            data=_serialize_staff_member(staff_member, staff_type, request),
            message=t(request, success_message),
            status_code=status.HTTP_200_OK
        )
    return error_response(
        message=t(request, 'invalid_data'),
        errors=serializer.errors,
        status_code=status.HTTP_400_BAD_REQUEST
    )


@api_view(['DELETE'])
@permission_classes([IsShopOwner])
def staff_delete_view(request, staff_type, staff_id):
    """
    DELETE /api/shop/staff/{staff_type}/{staff_id}/delete/
    """
    staff_type = _normalize_staff_type(staff_type)
    if not staff_type:
        return _staff_type_validation_error(request)

    staff_member, not_found_message = _get_staff_member(request.user, staff_type, staff_id)
    if not staff_member:
        return error_response(
            message=t(request, not_found_message),
            status_code=status.HTTP_404_NOT_FOUND
        )

    staff_member.delete()
    deleted_message = (
        'employee_deleted_successfully'
        if staff_type == STAFF_TYPE_EMPLOYEE
        else 'driver_deleted_successfully'
    )
    return success_response(
        message=t(request, deleted_message),
        status_code=status.HTTP_200_OK
    )


@api_view(['POST'])
@permission_classes([IsShopOwner])
def staff_block_view(request, staff_type, staff_id):
    """
    POST /api/shop/staff/{staff_type}/{staff_id}/block/
    Body: { "blocked": true|false }  # optional (default: true)
    """
    staff_type = _normalize_staff_type(staff_type)
    if not staff_type:
        return _staff_type_validation_error(request)

    staff_member, not_found_message = _get_staff_member(request.user, staff_type, staff_id)
    if not staff_member:
        return error_response(
            message=t(request, not_found_message),
            status_code=status.HTTP_404_NOT_FOUND
        )

    blocked = _parse_blocked_flag(request)
    if staff_type == STAFF_TYPE_EMPLOYEE:
        staff_member.is_active = not blocked
        staff_member.save()
    else:
        if blocked:
            staff_member.status = 'offline'
        elif staff_member.status == 'offline':
            staff_member.status = 'available'
        staff_member.save()

    response_data = _serialize_staff_member(staff_member, staff_type, request)
    response_data['blocked'] = blocked
    return success_response(
        data=response_data,
        message=t(request, 'staff_block_status_updated_successfully'),
        status_code=status.HTTP_200_OK
    )


@api_view(['POST'])
@permission_classes([AllowAny])
def driver_invitation_respond_view(request):
    """
    Driver accepts/rejects invitation sent by shop owner.
    POST /api/driver/invitation/respond/
    Body: {
      "phone_number": "01000000001",
      "shop_number": "12345",
      "otp": "123456",
      "action": "accept|reject",
      "name": "Driver Name",            # required for accept when missing
      "password": "password123"         # required for accept when no password yet
    }
    """
    phone_number = request.data.get('phone_number')
    shop_number = request.data.get('shop_number')
    otp_code = request.data.get('otp')
    action = str(request.data.get('action', '')).strip().lower()

    errors = {}
    if not phone_number:
        errors['phone_number'] = ['phone_number is required.']
    if not shop_number:
        errors['shop_number'] = ['shop_number is required.']
    if not otp_code:
        errors['otp'] = ['otp is required.']
    if action not in {'accept', 'reject'}:
        errors['action'] = ['action must be accept or reject.']
    if errors:
        return error_response(
            message=t(request, 'invalid_data'),
            errors=errors,
            status_code=status.HTTP_400_BAD_REQUEST
        )

    normalized_phone = normalize_phone(phone_number)
    if not otp_verify(normalized_phone, otp_code):
        return error_response(
            message=t(request, 'verification_code_is_invalid_or_expired'),
            status_code=status.HTTP_401_UNAUTHORIZED
        )

    shop_owner = ShopOwner.objects.filter(shop_number=shop_number).first()
    if not shop_owner:
        return error_response(
            message=t(request, 'shop_number_or_password_is_incorrect'),
            status_code=status.HTTP_404_NOT_FOUND
        )

    driver = Driver.objects.filter(
        shop_owner=shop_owner,
        phone_number__in=_driver_phone_variants(normalized_phone),
        status='pending'
    ).first()
    if not driver:
        return error_response(
            message='No pending driver invitation found.',
            status_code=status.HTTP_404_NOT_FOUND
        )

    if action == 'reject':
        driver.delete()
        return success_response(
            data={
                'action': 'reject',
                'phone_number': normalized_phone,
                'shop_number': shop_owner.shop_number
            },
            message='Driver invitation rejected successfully.',
            status_code=status.HTTP_200_OK
        )

    password = request.data.get('password')
    name = request.data.get('name')
    if not driver.password and (not password or len(str(password)) < 6):
        return error_response(
            message=t(request, 'invalid_data'),
            errors={'password': ['password is required and must be at least 6 characters.']},
            status_code=status.HTTP_400_BAD_REQUEST
        )

    if name:
        driver.name = name
    if password:
        driver.set_password(password)
    driver.phone_number = normalized_phone
    driver.status = 'available'
    driver.save()

    return success_response(
        data={
            'action': 'accept',
            'shop': {
                'id': shop_owner.id,
                'shop_name': shop_owner.shop_name,
                'shop_number': shop_owner.shop_number,
            },
            'driver': DriverSerializer(driver, context={'request': request}).data
        },
        message='Driver invitation accepted successfully.',
        status_code=status.HTTP_200_OK
    )


# Shop Status APIs
@api_view(['GET', 'PUT'])
@permission_classes([IsShopOwner])
def shop_status_view(request):
    """
    Ø¹Ø±Ø¶ ÙˆØªØ­Ø¯ÙŠØ« Ø­Ø§Ù„Ø© Ø§Ù„Ù…ØªØ¬Ø±
    GET /api/shop/status/ - Ø¹Ø±Ø¶ Ø­Ø§Ù„Ø© Ø§Ù„Ù…ØªØ¬Ø±
    PUT /api/shop/status/ - ØªØ­Ø¯ÙŠØ« Ø­Ø§Ù„Ø© Ø§Ù„Ù…ØªØ¬Ø±
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
    Ø¹Ø±Ø¶ Ù‚Ø§Ø¦Ù…Ø© Ø§Ù„Ø¹Ù…Ù„Ø§Ø¡ ÙˆØ¥Ø¶Ø§ÙØ© Ø¹Ù…ÙŠÙ„ Ø¬Ø¯ÙŠØ¯
    GET /api/shop/customers/ - Ø¹Ø±Ø¶ Ù‚Ø§Ø¦Ù…Ø© Ø§Ù„Ø¹Ù…Ù„Ø§Ø¡
    POST /api/shop/customers/ - Ø¥Ø¶Ø§ÙØ© Ø¹Ù…ÙŠÙ„ Ø¬Ø¯ÙŠØ¯
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
    Ø¹Ø±Ø¶ØŒ ØªØ­Ø¯ÙŠØ«ØŒ Ø£Ùˆ Ø­Ø°Ù Ø¹Ù…ÙŠÙ„
    GET /api/shop/customers/{id}/ - Ø¹Ø±Ø¶ Ø¹Ù…ÙŠÙ„
    PUT /api/shop/customers/{id}/ - ØªØ­Ø¯ÙŠØ« Ø¹Ù…ÙŠÙ„
    DELETE /api/shop/customers/{id}/ - Ø­Ø°Ù Ø¹Ù…ÙŠÙ„
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


# Product APIs (Ù‚Ø§Ø¦Ù…Ø© Ø§Ù„Ù…Ù†ØªØ¬Ø§Øª - Ø¨Ø±ÙˆÙØ§ÙŠÙ„ Ø§Ù„Ù…Ø­Ù„)
@api_view(['GET', 'POST'])
@permission_classes([IsShopOwner])
def product_list_view(request):
    """
    Ø¹Ø±Ø¶ Ù‚Ø§Ø¦Ù…Ø© Ø§Ù„Ù…Ù†ØªØ¬Ø§Øª ÙˆØ¥Ø¶Ø§ÙØ© Ù…Ù†ØªØ¬
    GET /api/shop/products/ - Ø¹Ø±Ø¶ Ù‚Ø§Ø¦Ù…Ø© Ø§Ù„Ù…Ù†ØªØ¬Ø§Øª
    POST /api/shop/products/ - Ø¥Ø¶Ø§ÙØ© Ù…Ù†ØªØ¬
    """
    shop_owner = request.user
    if request.method == 'GET':
        available_only = request.query_params.get('available')
        category_id = request.query_params.get('category_id')
        has_offer = request.query_params.get('has_offer')
        search_query = request.query_params.get('search')

        queryset = Product.objects.filter(shop_owner=shop_owner).select_related('category')
        if _is_true_query_value(available_only):
            queryset = queryset.filter(is_available=True)
        if category_id:
            queryset = queryset.filter(category_id=category_id)
        if _is_true_query_value(has_offer):
            queryset = queryset.filter(discount_price__isnull=False, discount_price__lt=F('price'))
        if search_query:
            queryset = queryset.filter(
                Q(name__icontains=search_query) | Q(description__icontains=search_query)
            )
        serializer = ProductSerializer(queryset, many=True, context={'request': request})
        return success_response(
            data=serializer.data,
            message=t(request, 'product_list_retrieved_successfully'),
            status_code=status.HTTP_200_OK
        )
    elif request.method == 'POST':
        serializer = ProductCreateSerializer(data=request.data, context={'shop_owner': shop_owner})
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
    Ø¹Ø±Ø¶ØŒ ØªØ­Ø¯ÙŠØ«ØŒ Ø£Ùˆ Ø­Ø°Ù Ù…Ù†ØªØ¬
    GET /api/shop/products/{id}/ - Ø¹Ø±Ø¶ Ù…Ù†ØªØ¬
    PUT /api/shop/products/{id}/ - ØªØ­Ø¯ÙŠØ« Ù…Ù†ØªØ¬
    DELETE /api/shop/products/{id}/ - Ø­Ø°Ù Ù…Ù†ØªØ¬
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
        serializer = ProductCreateSerializer(
            product,
            data=request.data,
            partial=True,
            context={'shop_owner': shop_owner}
        )
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
    Ø¹Ø±Ø¶ Ù‚Ø§Ø¦Ù…Ø© Ø§Ù„Ø·Ù„Ø¨Ø§Øª ÙˆØ¥Ù†Ø´Ø§Ø¡ Ø·Ù„Ø¨ Ø¬Ø¯ÙŠØ¯
    GET /api/shop/orders/ - Ø¹Ø±Ø¶ Ù‚Ø§Ø¦Ù…Ø© Ø§Ù„Ø·Ù„Ø¨Ø§Øª
    POST /api/shop/orders/ - Ø¥Ù†Ø´Ø§Ø¡ Ø·Ù„Ø¨ Ø¬Ø¯ÙŠØ¯ (Ù…Ù† Ø§Ù„Ù…Ø­Ù„)
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
    """ØµØ§Ø­Ø¨ Ø§Ù„Ù…Ø­Ù„ Ù…Ù† Ø§Ù„Ø·Ù„Ø¨ (ØµØ§Ø­Ø¨ Ù…Ø­Ù„ Ø£Ùˆ Ù…ÙˆØ¸Ù)"""
    user = request.user
    if hasattr(user, 'shop_owner_id') and user.shop_owner_id:
        return user.shop_owner
    return user


@api_view(['GET', 'PUT', 'DELETE'])
@permission_classes([IsShopOwnerOrEmployee])
def order_detail_view(request, order_id):
    """
    Ø¹Ø±Ø¶ØŒ ØªØ­Ø¯ÙŠØ«ØŒ Ø£Ùˆ Ø­Ø°Ù Ø·Ù„Ø¨
    GET /api/shop/orders/{id}/ - Ø¹Ø±Ø¶ Ø·Ù„Ø¨
    PUT /api/shop/orders/{id}/ - ØªØ­Ø¯ÙŠØ« Ø·Ù„Ø¨ (Ù‚Ø¨ÙˆÙ„/Ø±ÙØ¶/Ø¥Ù„ØºØ§Ø¡/ØªØ³Ø¹ÙŠØ±)
    DELETE /api/shop/orders/{id}/ - Ø­Ø°Ù Ø·Ù„Ø¨
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
        # ØªØ­Ø¯ÙŠØ« Ø§Ù„Ø·Ù„Ø¨
        old_driver = order.driver
        
        # Ù‚Ø¨ÙˆÙ„ Ø§Ù„Ø·Ù„Ø¨: ÙŠØ¬Ø¨ ØªØ¹Ø¨Ø¦Ø© Ø³Ø¹Ø± Ø§Ù„Ø·Ù„Ø¨ (Ø³Ø¹Ø± Ø§Ù„ØªÙˆØµÙŠÙ„ Ø§Ø®ØªÙŠØ§Ø±ÙŠ)
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
        elif getattr(request.user, 'user_type', None) == 'employee' and not order.employee_id:
            # Auto-link the order with the logged-in employee when no explicit employee_id is sent.
            order.employee = request.user
        
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
        
        # ØªØ­Ø¯ÙŠØ« Ø¨Ø§Ù‚ÙŠ Ø§Ù„Ø­Ù‚ÙˆÙ„
        for field in ['status', 'items', 'total_amount', 'delivery_fee', 'address', 'notes']:
            if field in request.data:
                field_value = request.data[field]
                if field == 'items' and isinstance(field_value, list):
                    field_value = json.dumps(field_value, ensure_ascii=False)
                setattr(order, field, field_value)
        
        order.save()
        
        # Ø±Ø³Ø§Ø¦Ù„ ØªÙ„Ù‚Ø§Ø¦ÙŠØ© Ø¹Ù†Ø¯ Ø§Ù„Ø±ÙØ¶/Ø§Ù„Ø¥Ù„ØºØ§Ø¡/Ø§Ù„Ù‚Ø¨ÙˆÙ„ (Ø­Ø³Ø¨ Ø§Ù„ØµÙˆØ± ÙˆØ§Ù„Ù€ PDF)
        try:
            if new_status == 'cancelled':
                msg_content = 'نأسف لعدم استقبال اوردراتكم في الوقت الحالي يرجى المحاوله في وقت لاحق'
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
        
        # ØªØ­Ø¯ÙŠØ« Ø¹Ø¯Ø¯ Ø§Ù„Ø·Ù„Ø¨Ø§Øª Ù„Ù„Ø³Ø§Ø¦Ù‚ÙŠÙ†
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
        
        # Ø¥Ø±Ø³Ø§Ù„ Ø¥Ø´Ø¹Ø§Ø± WebSocket Ø¨ØªØ­Ø¯ÙŠØ« Ø§Ù„Ø·Ù„Ø¨
        try:
            order_data = response_serializer.data
            notify_order_update(
                shop_owner_id=shop_owner.id,
                customer_id=order.customer_id,
                driver_id=order.driver_id if order.driver else None,
                order_data=order_data
            )
            
            # Ø¥Ø°Ø§ ØªÙ… ØªØ¹ÙŠÙŠÙ† Ø³Ø§Ø¦Ù‚ Ø¬Ø¯ÙŠØ¯ØŒ Ø¥Ø´Ø¹Ø§Ø±Ù‡
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
    Ø¹Ø±Ø¶ Ù‚Ø§Ø¦Ù…Ø© Ø§Ù„ÙÙˆØ§ØªÙŠØ± ÙˆØ¥Ù†Ø´Ø§Ø¡ ÙØ§ØªÙˆØ±Ø© Ø³Ø±ÙŠØ¹Ø©
    GET /api/shop/invoices/ - Ø¹Ø±Ø¶ Ù‚Ø§Ø¦Ù…Ø© Ø§Ù„ÙÙˆØ§ØªÙŠØ±
    POST /api/shop/invoices/ - Ø¥Ù†Ø´Ø§Ø¡ ÙØ§ØªÙˆØ±Ø© Ø³Ø±ÙŠØ¹Ø©
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
    Ø¹Ø±Ø¶ ÙØ§ØªÙˆØ±Ø© Ø£Ùˆ ØªØ­Ø¯ÙŠØ« Ø­Ø§Ù„Ø© Ø§Ù„Ø¥Ø±Ø³Ø§Ù„
    GET /api/shop/invoices/{id}/ - Ø¹Ø±Ø¶ ÙØ§ØªÙˆØ±Ø©
    PUT /api/shop/invoices/{id}/ - ØªØ­Ø¯ÙŠØ« Ø­Ø§Ù„Ø© Ø§Ù„Ø¥Ø±Ø³Ø§Ù„
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
    Ø¥Ø­ØµØ§Ø¦ÙŠØ§Øª Ù„ÙˆØ­Ø© Ø§Ù„ØªØ­ÙƒÙ… Ù„Ù„Ù…Ø­Ù„
    GET /api/shop/dashboard/statistics/
    """
    shop_owner = request.user
    
    # Ø¥Ø¬Ù…Ø§Ù„ÙŠ Ø§Ù„Ø¥ÙŠØ±Ø§Ø¯Ø§Øª
    total_revenue = Order.objects.filter(
        shop_owner=shop_owner,
        status='delivered'
    ).aggregate(total=Sum('total_amount'))['total'] or 0
    
    # Ø¥Ø¬Ù…Ø§Ù„ÙŠ Ø§Ù„Ø·Ù„Ø¨Ø§Øª
    total_orders = Order.objects.filter(shop_owner=shop_owner).count()
    
    # Ø§Ù„Ø·Ù„Ø¨Ø§Øª Ø­Ø³Ø¨ Ø§Ù„Ø­Ø§Ù„Ø©
    orders_by_status = Order.objects.filter(shop_owner=shop_owner).values('status').annotate(
        count=Count('id')
    )
    
    # Ø¹Ø¯Ø¯ Ø§Ù„Ø¹Ù…Ù„Ø§Ø¡
    total_customers = Customer.objects.filter(shop_owner=shop_owner).count()
    
    # Ø¹Ø¯Ø¯ Ø§Ù„Ø³Ø§Ø¦Ù‚ÙŠÙ†
    total_drivers = Driver.objects.filter(shop_owner=shop_owner).count()
    available_drivers = Driver.objects.filter(shop_owner=shop_owner, status='available').count()
    
    # Ø§Ù„Ø·Ù„Ø¨Ø§Øª Ø§Ù„Ø¬Ø¯ÙŠØ¯Ø©
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


# Employee Login View
@api_view(['POST'])
@permission_classes([AllowAny])
def employee_login_view(request):
    """
    ØªØ³Ø¬ÙŠÙ„ Ø¯Ø®ÙˆÙ„ Ø§Ù„Ù…ÙˆØ¸Ù ÙˆØ¥Ø±Ø¬Ø§Ø¹ JWT Token
    POST /api/employee/login/
    Body: {
        "phone_number": "Ø±Ù‚Ù… Ø§Ù„Ù‡Ø§ØªÙ",
        "password": "ÙƒÙ„Ù…Ø© Ø§Ù„Ù…Ø±ÙˆØ±"
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
    ØªØ³Ø¬ÙŠÙ„ Ø¯Ø®ÙˆÙ„ Ø§Ù„Ø³Ø§Ø¦Ù‚ ÙˆØ¥Ø±Ø¬Ø§Ø¹ JWT Token
    POST /api/driver/login/
    Body: {
        "phone_number": "Ø±Ù‚Ù… Ø§Ù„Ù‡Ø§ØªÙ",
        "password": "ÙƒÙ„Ù…Ø© Ø§Ù„Ù…Ø±ÙˆØ±"
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
    ØªØ³Ø¬ÙŠÙ„ Ø¹Ù…ÙŠÙ„ Ø¬Ø¯ÙŠØ¯
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
    ØªØ³Ø¬ÙŠÙ„ Ø¯Ø®ÙˆÙ„ Ø§Ù„Ø¹Ù…ÙŠÙ„
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
    """Ø§Ù„Ø¹Ù…ÙŠÙ„ Ù…Ù† Ø§Ù„Ø·Ù„Ø¨ (Ù„Ù€ JWT Ø¹Ù…ÙŠÙ„)"""
    user = request.user
    if isinstance(user, Customer):
        return user
    try:
        return Customer.objects.get(id=user.id)
    except (Customer.DoesNotExist, AttributeError):
        return None


def _normalize_order_items(items):
    normalized_items = []
    for item in items or []:
        item_text = str(item).strip()
        if item_text:
            normalized_items.append(item_text)
    return normalized_items


def _build_customer_order_request_message(customer, address, items, phone_number=None):
    lines = ["فاتورة الطلب", f"العميل: {customer.name}"]
    if phone_number:
        lines.append(f"رقم الهاتف: {phone_number}")
    if address:
        lines.append(f"العنوان: {address}")
    for item in _normalize_order_items(items):
        lines.append(f"- {item}")
    return "\n".join(lines)


def _chat_message_payload(message):
    return {
        'id': message.id,
        'sender_type': message.sender_type,
        'sender_name': message.sender_name,
        'message_type': message.message_type,
        'content': message.content,
        'is_read': message.is_read,
        'created_at': message.created_at.isoformat(),
        'audio_file_url': message.audio_file.url if message.audio_file else None,
        'image_file_url': message.image_file.url if message.image_file else None,
        'latitude': str(message.latitude) if message.latitude is not None else None,
        'longitude': str(message.longitude) if message.longitude is not None else None,
    }


# ==================== Shop Categories (master data for shop type) ====================

@api_view(['GET', 'POST'])
@permission_classes([IsShopOwner])
def shop_category_list_view(request):
    """
    List/Create shop categories used by ShopOwner.shop_category.
    GET /api/shop/shop-categories/
    POST /api/shop/shop-categories/
    """
    if request.method == 'GET':
        categories = ShopCategory.objects.all().order_by('name')
        serializer = ShopCategorySerializer(categories, many=True)
        return success_response(
            data=serializer.data,
            message='shop_categories_retrieved_successfully',
            status_code=status.HTTP_200_OK
        )

    serializer = ShopCategorySerializer(data=request.data)
    if serializer.is_valid():
        serializer.save()
        return success_response(
            data=serializer.data,
            message='shop_category_created_successfully',
            status_code=status.HTTP_201_CREATED
        )
    return error_response(
        message=t(request, 'invalid_data'),
        errors=serializer.errors,
        status_code=status.HTTP_400_BAD_REQUEST
    )


@api_view(['GET', 'PUT', 'DELETE'])
@permission_classes([IsShopOwner])
def shop_category_detail_view(request, category_id):
    """
    Retrieve/Update/Delete shop category.
    GET/PUT/DELETE /api/shop/shop-categories/{id}/
    """
    category = ShopCategory.objects.filter(id=category_id).first()
    if not category:
        return error_response(
            message=t(request, 'not_found'),
            errors={'shop_category': 'shop category not found.'},
            status_code=status.HTTP_404_NOT_FOUND
        )

    if request.method == 'GET':
        serializer = ShopCategorySerializer(category)
        return success_response(data=serializer.data, message='shop_category_retrieved_successfully')

    if request.method == 'PUT':
        serializer = ShopCategorySerializer(category, data=request.data, partial=True)
        if serializer.is_valid():
            serializer.save()
            return success_response(data=serializer.data, message='shop_category_updated_successfully')
        return error_response(
            message=t(request, 'invalid_data'),
            errors=serializer.errors,
            status_code=status.HTTP_400_BAD_REQUEST
        )

    category.delete()
    return success_response(message='shop_category_deleted_successfully')


# ==================== Public Shops (for Customer selection) ====================

@api_view(['GET'])
@permission_classes([AllowAny])
def public_shops_list_view(request):
    """
    List active shops (public).
    GET /api/shops/
    """
    shops = ShopOwner.objects.filter(is_active=True).select_related('shop_category').order_by('shop_name', 'shop_number')
    data = [
        {
            'id': s.id,
            'shop_number': s.shop_number,
            'shop_name': s.shop_name,
            'shop_category': (
                {'id': s.shop_category.id, 'name': s.shop_category.name}
                if s.shop_category else None
            )
        }
        for s in shops
    ]
    return success_response(
        data=data,
        message='shops_retrieved_successfully',
        status_code=status.HTTP_200_OK
    )


@api_view(['GET'])
@permission_classes([AllowAny])
def public_shop_categories_list_view(request):
    """
    List all available shop categories.
    GET /api/shops/shop-categories/
    """
    categories = ShopCategory.objects.filter(is_active=True).order_by('name')
    return success_response(
        data=[{'id': c.id, 'name': c.name} for c in categories],
        message='shop_categories_retrieved_successfully',
        status_code=status.HTTP_200_OK
    )


@api_view(['GET'])
@permission_classes([AllowAny])
def public_products_by_shop_category_view(request):
    """
    List products for all shops in a specific shop category.
    GET /api/shops/products/by-shop-category/?shop_category_id=1
    """
    shop_category_id = request.query_params.get('shop_category_id')
    shop_category_name = request.query_params.get('shop_category_name')
    product_category_id = request.query_params.get('category_id')
    has_offer = request.query_params.get('has_offer')
    search_query = request.query_params.get('search')

    if not shop_category_id and not shop_category_name:
        return error_response(
            message=t(request, 'invalid_data'),
            errors={'shop_category': 'shop_category_id or shop_category_name is required.'},
            status_code=status.HTTP_400_BAD_REQUEST
        )

    shop_category = None
    if shop_category_id:
        shop_category = ShopCategory.objects.filter(id=shop_category_id, is_active=True).first()
    elif shop_category_name:
        shop_category = ShopCategory.objects.filter(name__iexact=shop_category_name, is_active=True).first()

    if not shop_category:
        return error_response(
            message=t(request, 'not_found'),
            errors={'shop_category': 'shop category not found.'},
            status_code=status.HTTP_404_NOT_FOUND
        )

    products = Product.objects.filter(
        shop_owner__is_active=True,
        shop_owner__shop_category=shop_category,
        is_available=True
    ).select_related('shop_owner', 'category', 'shop_owner__shop_category')

    if product_category_id:
        products = products.filter(category_id=product_category_id)
    if _is_true_query_value(has_offer):
        products = products.filter(discount_price__isnull=False, discount_price__lt=F('price'))
    if search_query:
        products = products.filter(
            Q(name__icontains=search_query) | Q(description__icontains=search_query)
        )

    serializer = PublicProductSerializer(products, many=True, context={'request': request})
    return success_response(
        data={
            'shop_category': {'id': shop_category.id, 'name': shop_category.name},
            'total_products': products.count(),
            'products': serializer.data
        },
        message=t(request, 'product_list_retrieved_successfully'),
        status_code=status.HTTP_200_OK
    )


@api_view(['GET'])
@permission_classes([AllowAny])
def public_offers_view(request):
    """
    List current offers (fixed logic = discounted products only).
    GET /api/shops/offers/?shop_id=1&shop_category_id=1&category_id=2
    """
    shop_id = request.query_params.get('shop_id')
    shop_category_id = request.query_params.get('shop_category_id')
    category_id = request.query_params.get('category_id')
    search_query = request.query_params.get('search')

    offers = Product.objects.filter(
        shop_owner__is_active=True,
        is_available=True,
        discount_price__isnull=False,
        discount_price__lt=F('price')
    ).select_related('shop_owner', 'category', 'shop_owner__shop_category')

    if shop_id:
        offers = offers.filter(shop_owner_id=shop_id)
    if shop_category_id:
        offers = offers.filter(shop_owner__shop_category_id=shop_category_id)
    if category_id:
        offers = offers.filter(category_id=category_id)
    if search_query:
        offers = offers.filter(
            Q(name__icontains=search_query) | Q(description__icontains=search_query)
        )

    serializer = PublicOfferProductSerializer(offers, many=True, context={'request': request})
    return success_response(
        data=serializer.data,
        message='offers_retrieved_successfully',
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
        shop = ShopOwner.objects.filter(id=shop_owner_id, is_active=True).select_related('shop_category').first()
    elif shop_number:
        shop = ShopOwner.objects.filter(shop_number=shop_number, is_active=True).select_related('shop_category').first()
    else:
        return error_response(
            message=t(request, 'invalid_data'),
            errors={'shop': 'shop_owner_id or shop_number is required.'},
            status_code=status.HTTP_400_BAD_REQUEST
        )

    if not shop:
        return error_response(
            message=t(request, 'not_found'),
            errors={'shop': 'shop not found.'},
            status_code=status.HTTP_404_NOT_FOUND
        )

    customer.shop_owner = shop
    customer.save(update_fields=['shop_owner'])

    return success_response(
        data={
            'shop_owner_id': shop.id,
            'shop_number': shop.shop_number,
            'shop_name': shop.shop_name,
            'shop_category': (
                {'id': shop.shop_category.id, 'name': shop.shop_category.name}
                if shop.shop_category else None
            )
        },
        message='shop selected successfully.',
        status_code=status.HTTP_200_OK
    )


# ==================== Customer Orders (Ø·Ù„Ø¨Ø§Øª Ø§Ù„Ø¹Ù…ÙŠÙ„ - Ø§Ù„Ø·Ù„Ø¨ ÙƒØ£ÙˆÙ„ Ø±Ø³Ø§Ù„Ø©) ====================

@api_view(['GET', 'POST'])
@permission_classes([IsCustomer])
def customer_orders_list_create_view(request):
    """
    Ù‚Ø§Ø¦Ù…Ø© Ø·Ù„Ø¨Ø§Øª Ø§Ù„Ø¹Ù…ÙŠÙ„ ÙˆØ¥Ù†Ø´Ø§Ø¡ Ø·Ù„Ø¨ Ø¬Ø¯ÙŠØ¯ (Ø§Ù„Ø±Ø³Ø§Ù„Ø© Ø§Ù„Ø£ÙˆÙ„Ù‰ = Ø§Ù„ÙØ§ØªÙˆØ±Ø©: Ø§Ø³Ù…ØŒ Ø¹Ù†ÙˆØ§Ù†ØŒ Ø¨Ù†Ø¯ 1ØŒ 2ØŒ 3ØŒ ...)
    GET /api/customer/orders/ - Ù‚Ø§Ø¦Ù…Ø© Ø·Ù„Ø¨Ø§ØªÙŠ
    POST /api/customer/orders/ - Ø¥Ù†Ø´Ø§Ø¡ Ø·Ù„Ø¨ (ÙŠÙ…Ù„Ø£ Ø§Ù„Ù†Ù…ÙˆØ°Ø¬ ÙˆÙŠØ¨Ø¹Ø« Ù„Ù„Ù…Ø­Ù„)
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
            requested_phone = (serializer.validated_data.get('phone_number') or '').strip()
            requested_phone = normalize_phone(requested_phone) if requested_phone else ''
            phone_for_message = requested_phone or (customer.phone_number or '')
            order = serializer.save()

            # First chat message in the order thread (request/invoice draft card content).
            try:
                request_message = _build_customer_order_request_message(
                    customer=customer,
                    phone_number=phone_for_message,
                    address=order.address,
                    items=serializer.validated_data.get('items', [])
                )
                first_msg = ChatMessage.objects.create(
                    order=order,
                    chat_type='shop_customer',
                    sender_type='customer',
                    sender_customer=customer,
                    message_type='text',
                    content=request_message,
                )
                order.unread_messages_count = order.messages.filter(
                    chat_type='shop_customer',
                    is_read=False,
                    sender_type='customer'
                ).count()
                order.save(update_fields=['unread_messages_count'])
                broadcast_chat_message_to_order(order.id, _chat_message_payload(first_msg))
            except Exception as e:
                print(f"initial chat message broadcast error: {e}")

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
    ØªØ£ÙƒÙŠØ¯ Ø§Ù„Ø·Ù„Ø¨ Ø¨Ø¹Ø¯ Ø§Ù„ØªØ³Ø¹ÙŠØ± (Ø§Ù„Ø¹Ù…ÙŠÙ„ ÙŠØ¶ØºØ· Ø²Ø±Ø§Ø± ØªØ£ÙƒÙŠØ¯)
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

    try:
        accepted_msg = ChatMessage.objects.create(
            order=order,
            chat_type='shop_customer',
            sender_type='customer',
            sender_customer=customer,
            message_type='text',
            content='تمت الموافقة على الفاتورة من العميل',
        )
        broadcast_chat_message_to_order(order.id, _chat_message_payload(accepted_msg))
    except Exception as e:
        print(f"confirm order chat message error: {e}")
    
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


@api_view(['POST'])
@permission_classes([IsCustomer])
def customer_order_reject_view(request, order_id):
    """
    Customer rejects priced invoice/order.
    POST /api/customer/orders/{id}/reject/
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

    order.status = 'cancelled'
    order.save()

    try:
        rejected_msg = ChatMessage.objects.create(
            order=order,
            chat_type='shop_customer',
            sender_type='customer',
            sender_customer=customer,
            message_type='text',
            content='تم رفض الفاتورة من العميل',
        )
        broadcast_chat_message_to_order(order.id, _chat_message_payload(rejected_msg))
    except Exception as e:
        print(f"reject order chat message error: {e}")

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
        message='تم رفض الفاتورة والطلب',
        status_code=status.HTTP_200_OK
    )


@api_view(['GET', 'PUT'])
@permission_classes([IsCustomer])
def customer_profile_view(request):
    """
    Ø¹Ø±Ø¶ ÙˆØªØ­Ø¯ÙŠØ« Ù…Ù„Ù Ø§Ù„Ø¹Ù…ÙŠÙ„
    GET/PUT /api/customer/profile/
    """
    # Ø§Ù„ØªØ­Ù‚Ù‚ Ù…Ù† Ø£Ù† Ø§Ù„Ù…Ø³ØªØ®Ø¯Ù… Ù‡Ùˆ Ø¹Ù…ÙŠÙ„
    user = request.user
    
    # Ø¥Ø°Ø§ ÙƒØ§Ù† Ø§Ù„Ù…Ø³ØªØ®Ø¯Ù… Customer Ù…Ø¨Ø§Ø´Ø±Ø© Ù…Ù† Ø§Ù„Ù€ authentication
    if isinstance(user, Customer):
        customer = user
    else:
        # Ù…Ø­Ø§ÙˆÙ„Ø© Ø¬Ù„Ø¨ Ø§Ù„Ø¹Ù…ÙŠÙ„ Ø¨Ø§Ù„Ù€ ID
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
            data.pop('password')  # ØªØºÙŠÙŠØ± ÙƒÙ„Ù…Ø© Ø§Ù„Ù…Ø±ÙˆØ± Ù„Ù‡ endpoint Ù…Ù†ÙØµÙ„
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
    Ù‚Ø§Ø¦Ù…Ø© Ø¹Ù†Ø§ÙˆÙŠÙ† Ø§Ù„Ø¹Ù…ÙŠÙ„ ÙˆØ¥Ø¶Ø§ÙØ© Ø¹Ù†ÙˆØ§Ù† Ø¬Ø¯ÙŠØ¯
    GET /api/customer/addresses/
    POST /api/customer/addresses/
    """
    customer_id = request.user.id  # Ø£Ùˆ Ù…Ù† JWT
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
    Ø¹Ø±Ø¶ØŒ ØªØ­Ø¯ÙŠØ«ØŒ Ø­Ø°Ù Ø¹Ù†ÙˆØ§Ù†
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
    Ù‚Ø§Ø¦Ù…Ø© Ø§Ù„ØªØµÙ†ÙŠÙØ§Øª
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
    Ø¹Ø±Ø¶ØŒ ØªØ­Ø¯ÙŠØ«ØŒ Ø­Ø°Ù ØªØµÙ†ÙŠÙ
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
    ØªÙ‚ÙŠÙŠÙ… Ø·Ù„Ø¨
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
    
    # ØªØ­Ø¯ÙŠØ« ØªÙ‚ÙŠÙŠÙ… Ø§Ù„Ø³Ø§Ø¦Ù‚ Ø¥Ù† ÙˆØ¬Ø¯
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
    Ø¹Ø±Ø¶ ØªÙ‚ÙŠÙŠÙ… Ø·Ù„Ø¨
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
    Ù‚Ø§Ø¦Ù…Ø© Ø·Ø±Ù‚ Ø§Ù„Ø¯ÙØ¹ ÙˆØ¥Ø¶Ø§ÙØ© Ø·Ø±ÙŠÙ‚Ø© Ø¬Ø¯ÙŠØ¯Ø©
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
    Ø­Ø°Ù Ø·Ø±ÙŠÙ‚Ø© Ø¯ÙØ¹
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
    Ù‚Ø§Ø¦Ù…Ø© Ø§Ù„Ø¥Ø´Ø¹Ø§Ø±Ø§Øª
    GET /api/notifications/
    """
    user = request.user
    # ØªØ­Ø¯ÙŠØ¯ Ù†ÙˆØ¹ Ø§Ù„Ù…Ø³ØªØ®Ø¯Ù…
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
        # Ù…Ø­Ø§ÙˆÙ„Ø© Ù…Ù† customer_id ÙÙŠ JWT
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
    ØªØ­Ø¯ÙŠØ¯ Ø¥Ø´Ø¹Ø§Ø± ÙƒÙ…Ù‚Ø±ÙˆØ¡
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
    ØªØ­Ø¯ÙŠØ¯ Ø¬Ù…ÙŠØ¹ Ø§Ù„Ø¥Ø´Ø¹Ø§Ø±Ø§Øª ÙƒÙ…Ù‚Ø±ÙˆØ¡Ø©
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
    Ø¹Ø±Ø¶ Ø³Ù„Ø© Ø§Ù„ØªØ³ÙˆÙ‚ Ù„Ù…Ø­Ù„ Ù…Ø¹ÙŠÙ†
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
    Ø¥Ø¶Ø§ÙØ© Ù…Ù†ØªØ¬ Ù„Ù„Ø³Ù„Ø©
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
    ØªØ­Ø¯ÙŠØ« Ø£Ùˆ Ø­Ø°Ù Ø¹Ù†ØµØ± Ù…Ù† Ø§Ù„Ø³Ù„Ø©
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
    ØªÙØ±ÙŠØº Ø§Ù„Ø³Ù„Ø©
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
    ØªØ­Ø¯ÙŠØ« Ù…ÙˆÙ‚Ø¹ Ø§Ù„Ø³Ø§Ø¦Ù‚
    PUT /api/driver/location/
    Body: { "latitude": 24.7136, "longitude": 46.6753 }
    """
    # Ù†ÙØªØ±Ø¶ Ø£Ù† Ø§Ù„Ø³Ø§Ø¦Ù‚ Ù…Ø³Ø¬Ù„ Ø¯Ø®ÙˆÙ„
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
    ØªØªØ¨Ø¹ Ø§Ù„Ø·Ù„Ø¨ (Ù…ÙˆÙ‚Ø¹ Ø§Ù„Ø³Ø§Ø¦Ù‚)
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



