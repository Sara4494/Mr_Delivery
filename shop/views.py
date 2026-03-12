from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework.response import Response
from rest_framework.pagination import PageNumberPagination
import json
from django.db import IntegrityError
from django.db.models import Q, Count, Sum, F, Avg, Prefetch
from django.utils import timezone
from datetime import datetime, timedelta
from .models import (
    ShopStatus, Customer, CustomerAddress, Driver, Order, ChatMessage, 
    Invoice, Employee, Product, Category, OrderRating, ShopReview, PaymentMethod, 
    Notification, Cart, CartItem, ShopDriver
)
from gallery.models import WorkSchedule, GalleryImage, ImageLike
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
    ShopRatingCreateSerializer,
    PaymentMethodSerializer,
    PaymentMethodCreateSerializer,
    NotificationSerializer,
    CartSerializer,
    CartItemSerializer,
    AddToCartSerializer,
    UpdateCartItemSerializer,
    ChatMessageSerializer,
)
from .permissions import IsShopOwner, IsCustomer, IsDriver, IsEmployee, IsShopOwnerOrEmployee
from user.models import (
    ShopCategory,
    ShopOwner,
    WORK_SCHEDULE_DAYS,
    WORK_SCHEDULE_DAY_LABELS,
    default_work_schedule,
)
from user.utils import success_response, error_response, build_message_fields, t
from user.otp_service import send_otp as otp_send, verify_otp as otp_verify, normalize_phone
from .websocket_utils import (
    notify_order_update,
    notify_driver_assigned,
    notify_new_order,
    broadcast_chat_message_to_order,
    broadcast_chat_message,
)


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


class PublicShopsPagination(PageNumberPagination):
    """Pagination for customer-facing public shops list."""

    page_size = 20
    page_size_query_param = 'page_size'
    max_page_size = 100

    def get_paginated_response(self, data):
        response_data = {
            "status": status.HTTP_200_OK,
            **build_message_fields(
                t(getattr(self, "request", None), "shops_retrieved_successfully"),
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


class PublicGalleryPagination(PageNumberPagination):
    """Pagination for customer-facing portfolio feed."""

    page_size = 12
    page_size_query_param = 'page_size'
    max_page_size = 100

    def get_paginated_response(self, data):
        response_data = {
            "status": status.HTTP_200_OK,
            **build_message_fields(
                t(getattr(self, "request", None), "images_retrieved_successfully"),
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
    """تحويل قيمة query param إلى bool."""
    return str(value).lower() in {'1', 'true', 'yes', 'on'}


def _is_shop_owner_user(user):
    user_type = getattr(user, 'user_type', None)
    return user_type == 'shop_owner' or isinstance(user, ShopOwner)


def _is_employee_user(user):
    user_type = getattr(user, 'user_type', None)
    return user_type == 'employee' or isinstance(user, Employee)


def _is_cashier_user(user):
    return _is_employee_user(user) and getattr(user, 'role', None) == 'cashier'


def _resolve_owner_for_owner_or_cashier(user):
    if _is_shop_owner_user(user):
        return user
    if _is_cashier_user(user):
        return getattr(user, 'shop_owner', None)
    return None


def _owner_or_cashier_forbidden(request):
    return error_response(
        message=t(request, 'permission_only_shop_owner_or_cashier'),
        status_code=status.HTTP_403_FORBIDDEN
    )


def _resolve_owner_for_owner_or_employee(user):
    if _is_shop_owner_user(user):
        return user
    if _is_employee_user(user):
        return getattr(user, 'shop_owner', None)
    return None


def _owner_or_employee_forbidden(request):
    return error_response(
        message=t(request, 'permission_only_shop_owner_or_employees'),
        status_code=status.HTTP_403_FORBIDDEN
    )


def _get_dashboard_period_ranges(period):
    today = timezone.localdate()

    if period == 'daily':
        current_start = today
        current_end = today
        previous_start = today - timedelta(days=1)
        previous_end = today - timedelta(days=1)
    elif period == 'weekly':
        current_start = today - timedelta(days=today.weekday())
        current_end = today
        previous_start = current_start - timedelta(days=7)
        previous_end = current_start - timedelta(days=1)
    elif period in {'monthly', 'month'}:
        current_start = today.replace(day=1)
        current_end = today
        previous_end = current_start - timedelta(days=1)
        previous_start = previous_end.replace(day=1)
    else:
        current_start = None
        current_end = None
        previous_start = None
        previous_end = None

    return current_start, current_end, previous_start, previous_end


def _apply_created_date_range(queryset, start_date=None, end_date=None):
    if start_date:
        queryset = queryset.filter(created_at__date__gte=start_date)
    if end_date:
        queryset = queryset.filter(created_at__date__lte=end_date)
    return queryset


def _growth_percentage(current_value, previous_value):
    if previous_value <= 0:
        return 100.0 if current_value > 0 else 0.0
    return round(((current_value - previous_value) / previous_value) * 100, 1)


def _format_dashboard_number(value):
    if isinstance(value, float):
        if value.is_integer():
            return f"{value:,.0f}"
        return f"{value:,.2f}"
    return f"{value:,}"


def _format_dashboard_currency(amount):
    amount = float(amount)
    return f"ر.س {_format_dashboard_number(amount)}"


def _build_dashboard_card(*, key, label, value, trend_percentage, is_currency=False):
    rounded_trend = round(float(trend_percentage), 1)
    if rounded_trend > 0:
        trend_direction = 'up'
        trend_display = f"+{_format_dashboard_number(rounded_trend)}%"
    elif rounded_trend < 0:
        trend_direction = 'down'
        trend_display = f"{_format_dashboard_number(rounded_trend)}%"
    else:
        trend_direction = 'stable'
        trend_display = "0%"

    return {
        'key': key,
        'label': label,
        'value': float(value) if is_currency else int(value),
        'display_value': _format_dashboard_currency(value) if is_currency else _format_dashboard_number(int(value)),
        'trend_percentage': rounded_trend,
        'trend_display': trend_display,
        'trend_direction': trend_direction,
    }


STAFF_TYPE_EMPLOYEE = 'employee'
STAFF_TYPE_DRIVER = 'driver'
VALID_STAFF_TYPES = {STAFF_TYPE_EMPLOYEE, STAFF_TYPE_DRIVER}
PY_WEEKDAY_TO_WORK_DAY = {
    0: 'monday',
    1: 'tuesday',
    2: 'wednesday',
    3: 'thursday',
    4: 'friday',
    5: 'saturday',
    6: 'sunday',
}


def _parse_schedule_time(value):
    if value in (None, ''):
        return None
    if not isinstance(value, str):
        return None
    try:
        parsed_time = datetime.strptime(value.strip(), '%H:%M')
    except ValueError:
        return None
    return parsed_time.strftime('%H:%M')


def _is_valid_schedule_range(start_time, end_time):
    if not start_time or not end_time:
        return False
    return start_time < end_time


def _normalize_work_schedule(raw_schedule):
    normalized_schedule = default_work_schedule()
    if not isinstance(raw_schedule, dict):
        return normalized_schedule

    for day in WORK_SCHEDULE_DAYS:
        day_data = raw_schedule.get(day)
        if not isinstance(day_data, dict):
            continue

        current_day = normalized_schedule[day]
        is_working = day_data.get('is_working')
        if isinstance(is_working, bool):
            current_day['is_working'] = is_working

        start_time = _parse_schedule_time(day_data.get('start_time'))
        end_time = _parse_schedule_time(day_data.get('end_time'))

        if current_day['is_working']:
            if start_time:
                current_day['start_time'] = start_time
            if end_time:
                current_day['end_time'] = end_time
            if not _is_valid_schedule_range(current_day.get('start_time'), current_day.get('end_time')):
                current_day['start_time'] = '09:00'
                current_day['end_time'] = '17:00'
        else:
            current_day['start_time'] = None
            current_day['end_time'] = None

    return normalized_schedule


def _merge_work_schedule(current_schedule, updates):
    errors = {}
    if not isinstance(updates, dict):
        return None, {'schedule': ['schedule must be an object keyed by day.']}

    merged_schedule = _normalize_work_schedule(current_schedule)

    for day_key, day_update in updates.items():
        if day_key not in WORK_SCHEDULE_DAYS:
            errors.setdefault('schedule', []).append(f'Unsupported day: {day_key}.')
            continue
        if not isinstance(day_update, dict):
            errors.setdefault(day_key, []).append('Each day must be an object.')
            continue

        day_data = merged_schedule[day_key]

        if 'is_working' in day_update:
            if isinstance(day_update['is_working'], bool):
                day_data['is_working'] = day_update['is_working']
            else:
                errors.setdefault(day_key, []).append('is_working must be true or false.')

        if 'start_time' in day_update:
            if not day_data.get('is_working'):
                day_data['start_time'] = None
            else:
                parsed_start = _parse_schedule_time(day_update['start_time'])
                if day_update['start_time'] not in (None, '') and not parsed_start:
                    errors.setdefault(day_key, []).append('start_time must be in HH:MM format.')
                else:
                    day_data['start_time'] = parsed_start

        if 'end_time' in day_update:
            if not day_data.get('is_working'):
                day_data['end_time'] = None
            else:
                parsed_end = _parse_schedule_time(day_update['end_time'])
                if day_update['end_time'] not in (None, '') and not parsed_end:
                    errors.setdefault(day_key, []).append('end_time must be in HH:MM format.')
                else:
                    day_data['end_time'] = parsed_end

    for day_key in WORK_SCHEDULE_DAYS:
        day_data = merged_schedule[day_key]
        if day_data.get('is_working'):
            if not day_data.get('start_time') or not day_data.get('end_time'):
                errors.setdefault(day_key, []).append('start_time and end_time are required when is_working is true.')
                continue
            if not _is_valid_schedule_range(day_data['start_time'], day_data['end_time']):
                errors.setdefault(day_key, []).append('end_time must be later than start_time.')
        else:
            day_data['start_time'] = None
            day_data['end_time'] = None

    if errors:
        return None, errors

    return merged_schedule, None


def _build_work_schedule_response(schedule):
    normalized_schedule = _normalize_work_schedule(schedule)
    days = []

    for day_key in WORK_SCHEDULE_DAYS:
        day_data = normalized_schedule[day_key]
        days.append({
            'day_key': day_key,
            'day_name': WORK_SCHEDULE_DAY_LABELS.get(day_key, day_key),
            'is_working': day_data.get('is_working', False),
            'is_holiday': not day_data.get('is_working', False),
            'start_time': day_data.get('start_time'),
            'end_time': day_data.get('end_time'),
        })

    today_key = PY_WEEKDAY_TO_WORK_DAY.get(timezone.localdate().weekday(), 'monday')
    today_data = normalized_schedule.get(today_key, {'is_working': False, 'start_time': None, 'end_time': None})

    return {
        'schedule': normalized_schedule,
        'days': days,
        'today': {
            'day_key': today_key,
            'day_name': WORK_SCHEDULE_DAY_LABELS.get(today_key, today_key),
            'is_working': today_data.get('is_working', False),
            'is_holiday': not today_data.get('is_working', False),
            'start_time': today_data.get('start_time'),
            'end_time': today_data.get('end_time'),
        },
    }


def _build_legacy_work_schedule_fields(schedule):
    """
    Build text fields for legacy gallery.WorkSchedule admin rows.
    """
    normalized_schedule = _normalize_work_schedule(schedule)
    working_days = [
        WORK_SCHEDULE_DAY_LABELS.get(day_key, day_key)
        for day_key in WORK_SCHEDULE_DAYS
        if normalized_schedule[day_key].get('is_working')
    ]

    if working_days:
        work_days = '، '.join(working_days)
    else:
        work_days = 'إجازة طوال الأسبوع'

    working_ranges = {
        (day_data.get('start_time'), day_data.get('end_time'))
        for day_data in normalized_schedule.values()
        if day_data.get('is_working') and day_data.get('start_time') and day_data.get('end_time')
    }

    if not working_ranges:
        work_hours = 'إجازة'
    elif len(working_ranges) == 1:
        start_time, end_time = next(iter(working_ranges))
        work_hours = f'{start_time} - {end_time}'
    else:
        work_hours = 'مواعيد مختلفة حسب اليوم'

    return {
        'work_days': work_days,
        'work_hours': work_hours,
    }


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
        return Driver.objects.get(id=staff_id, shops=shop_owner), None
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
    excluded_keys = {'staff_type', 'staff_id', 'blocked'}
    payload = {}

    for key in request.data.keys():
        if key in excluded_keys or key in request.FILES:
            continue
        values = request.data.getlist(key) if hasattr(request.data, 'getlist') else None
        payload[key] = values if values and len(values) > 1 else request.data.get(key)

    for key in request.FILES:
        if key not in excluded_keys:
            payload[key] = request.FILES[key]

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

    # Driver must already have an account before invitation.
    existing_account = (
        Driver.objects
        .filter(phone_number__in=phone_candidates)
        .exclude(password__isnull=True)
        .exclude(password='')
        .order_by('-updated_at')
        .first()
    )
    if not existing_account:
        return error_response(
            message='Driver account not found. Driver must register first.',
            status_code=status.HTTP_400_BAD_REQUEST
        )

    relation, created = ShopDriver.objects.get_or_create(
        shop_owner=shop_owner,
        driver=existing_account,
        defaults={'status': 'pending'}
    )
    if not created:
        if relation.status == 'active':
            return error_response(
                message='Driver is already active in this shop.',
                status_code=status.HTTP_400_BAD_REQUEST
            )
        if relation.status == 'blocked':
            return error_response(
                message='Driver is blocked in this shop.',
                status_code=status.HTTP_400_BAD_REQUEST
            )
        relation.status = 'pending'
        relation.save(update_fields=['status'])

    if existing_account.phone_number != normalized_phone:
        existing_account.phone_number = normalized_phone
        existing_account.save(update_fields=['phone_number'])

    send_ok, send_msg = otp_send(normalized_phone)
    if not send_ok:
        return error_response(
            message=str(send_msg),
            status_code=status.HTTP_400_BAD_REQUEST
        )

    response_data = _serialize_staff_member(existing_account, STAFF_TYPE_DRIVER, request)
    response_data['invitation_sent'] = True
    response_data['invitation_channel'] = 'whatsapp_otp'
    response_data['invitation_note'] = 'Driver should respond using /api/driver/invitation/respond/'
    response_data['shop_link_status'] = relation.status
    return success_response(
        data=response_data,
        message='Driver invitation sent successfully.',
        status_code=status.HTTP_201_CREATED
    )


@api_view(['GET', 'POST', 'PUT'])
@permission_classes([IsShopOwner])
def staff_view(request):
    """
    Endpoint موحد للموظفين والسائقين.
    GET /api/shop/staff/ -> القائمة (staff_type=all|employee|driver) أو تفاصيل عنصر واحد (staff_id)
    POST /api/shop/staff/ -> إضافة موظف/سائق جديد
      - Invite driver by phone only: { "phone_number": "..." }  # staff_type optional
      - Create employee: staff_type=employee
      - Create driver via explicit type: staff_type=driver
    PUT /api/shop/staff/ -> تحديث موظف/سائق (staff_type + staff_id)
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
        driver_base_queryset = Driver.objects.filter(shops=shop_owner).distinct()

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
            driver_queryset = driver_base_queryset.order_by('-updated_at')
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
            'total_drivers': driver_base_queryset.count(),
            'available_drivers': driver_base_queryset.filter(status='available').count(),
            'active_drivers': driver_base_queryset.filter(status__in=['available', 'busy']).count(),
            'blocked_drivers': driver_base_queryset.filter(status='offline').count(),
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
        payload = _clean_staff_payload(request)
        staff_type = _normalize_staff_type(request.data.get('staff_type'))
        if not staff_type:
            if payload.get('phone_number'):
                return _invite_driver(request, shop_owner, payload)
            return _staff_type_validation_error(request)

        if staff_type == STAFF_TYPE_DRIVER:
            return _invite_driver(request, shop_owner, payload)

        if staff_type == STAFF_TYPE_EMPLOYEE:
            serializer = EmployeeCreateSerializer(
                data=payload,
                context={'shop_owner': shop_owner, 'request': request}
            )
            success_message = 'employee_added_successfully'

        if serializer.is_valid():
            try:
                staff_member = serializer.save()
            except IntegrityError:
                return error_response(
                    message=t(request, 'invalid_data'),
                    errors={
                        'phone_number': [
                            t(request, 'phone_number_is_already_used_for_this_shop')
                        ]
                    },
                    status_code=status.HTTP_400_BAD_REQUEST
                )
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
      "otp": "123456",
      "action": "accept|reject"
    }
    """
    phone_number = request.data.get('phone_number')
    raw_shop_number = request.data.get('shop_number')
    shop_number = str(raw_shop_number).strip() if raw_shop_number is not None else ''
    otp_code = request.data.get('otp')
    action = str(request.data.get('action', '')).strip().lower()

    errors = {}
    if not phone_number:
        errors['phone_number'] = ['phone_number is required.']
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
    if not normalized_phone:
        return error_response(
            message=t(request, 'invalid_data'),
            errors={'phone_number': ['Invalid phone number.']},
            status_code=status.HTTP_400_BAD_REQUEST
        )

    if not otp_verify(normalized_phone, otp_code):
        return error_response(
            message=t(request, 'verification_code_is_invalid_or_expired'),
            status_code=status.HTTP_401_UNAUTHORIZED
        )

    driver = Driver.objects.filter(phone_number__in=_driver_phone_variants(normalized_phone)).first()
    if not driver:
        return error_response(
            message='No pending driver invitation found.',
            status_code=status.HTTP_404_NOT_FOUND
        )

    pending_links = ShopDriver.objects.filter(
        driver=driver,
        status='pending',
    ).select_related('shop_owner').order_by('-joined_at', '-id')

    if shop_number:
        if not ShopOwner.objects.filter(shop_number=shop_number).exists():
            return error_response(
                message=t(request, 'shop_number_or_password_is_incorrect'),
                status_code=status.HTTP_404_NOT_FOUND
            )
        pending_links = pending_links.filter(shop_owner__shop_number=shop_number)

    shop_driver = pending_links.first()
    if not shop_driver:
        return error_response(
            message='No pending driver invitation found.',
            status_code=status.HTTP_404_NOT_FOUND
        )
    shop_owner = shop_driver.shop_owner

    if action == 'reject':
        shop_driver.status = 'rejected'
        shop_driver.save(update_fields=['status'])
        return success_response(
            data={
                'action': 'reject',
                'phone_number': normalized_phone,
                'shop_number': shop_owner.shop_number
            },
            message='Driver invitation rejected successfully.',
            status_code=status.HTTP_200_OK
        )

    if not driver.password:
        return error_response(
            message='Driver account not ready. Please contact support.',
            status_code=status.HTTP_400_BAD_REQUEST
        )

    driver_update_fields = []
    if driver.phone_number != normalized_phone:
        driver.phone_number = normalized_phone
        driver_update_fields.append('phone_number')
    if driver.status == 'offline':
        driver.status = 'available'
        driver_update_fields.append('status')
    if driver_update_fields:
        driver.save(update_fields=driver_update_fields)

    shop_driver.status = 'active'
    shop_driver.save(update_fields=['status'])

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
@permission_classes([IsShopOwnerOrEmployee])
def shop_status_view(request):
    """
    عرض وتحديث حالة المتجر
    GET /api/shop/status/ - عرض حالة المتجر
    PUT /api/shop/status/ - تحديث حالة المتجر
    """
    shop_owner = _resolve_owner_for_owner_or_cashier(request.user)
    if not shop_owner:
        return _owner_or_cashier_forbidden(request)

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


@api_view(['GET', 'PUT'])
@permission_classes([IsShopOwnerOrEmployee])
def shop_work_schedule_view(request):
    """
    عرض وتحديث مواعيد العمل الأسبوعية
    GET /api/shop/work-schedule/ - عرض المواعيد
    PUT /api/shop/work-schedule/ - تحديث المواعيد (true/false لكل يوم)
    """
    shop_owner = _resolve_owner_for_owner_or_cashier(request.user)
    if not shop_owner:
        return _owner_or_cashier_forbidden(request)

    current_schedule = _normalize_work_schedule(shop_owner.work_schedule)

    # Keep legacy WorkSchedule row available in Django admin.
    WorkSchedule.objects.update_or_create(
        shop_owner=shop_owner,
        defaults=_build_legacy_work_schedule_fields(current_schedule)
    )

    if request.method == 'GET':
        return success_response(
            data=_build_work_schedule_response(current_schedule),
            message=t(request, 'work_schedule_retrieved_successfully'),
            status_code=status.HTTP_200_OK
        )

    updates = request.data.get('schedule', request.data)
    if isinstance(updates, str):
        try:
            updates = json.loads(updates)
        except ValueError:
            return error_response(
                message=t(request, 'invalid_data'),
                errors={'schedule': ['Invalid JSON string.']},
                status_code=status.HTTP_400_BAD_REQUEST
            )
    merged_schedule, errors = _merge_work_schedule(current_schedule, updates)
    if errors:
        return error_response(
            message=t(request, 'invalid_data'),
            errors=errors,
            status_code=status.HTTP_400_BAD_REQUEST
        )

    shop_owner.work_schedule = merged_schedule
    shop_owner.save()

    # Keep legacy WorkSchedule row in sync for Django admin dashboard visibility.
    WorkSchedule.objects.update_or_create(
        shop_owner=shop_owner,
        defaults=_build_legacy_work_schedule_fields(merged_schedule)
    )

    return success_response(
        data=_build_work_schedule_response(merged_schedule),
        message=t(request, 'work_schedule_updated_successfully'),
        status_code=status.HTTP_200_OK
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
        new_status = request.data.get('status', old_status)

        locked_after_customer_confirm = {'confirmed', 'preparing', 'on_way', 'delivered'}
        invoice_closed_statuses = {'cancelled', 'delivered'}
        invoice_fields = {'items', 'total_amount', 'delivery_fee'}
        has_invoice_update = any(field in request.data for field in invoice_fields)
        driver_raw_value = request.data.get('driver_id') if 'driver_id' in request.data else None
        has_driver_assignment = (
            driver_raw_value is not None and str(driver_raw_value).strip() not in {'', '0', 'null', 'None'}
        )

        if new_status == 'pending_customer_confirm' and old_status in invoice_closed_statuses:
            return error_response(
                message='لا يمكن إعادة الفاتورة بعد إلغائها أو بعد إتمام الطلب.',
                status_code=status.HTTP_400_BAD_REQUEST
            )

        if has_invoice_update and old_status in invoice_closed_statuses:
            return error_response(
                message='لا يمكن تعديل الفاتورة بعد إلغائها أو بعد إتمام الطلب.',
                status_code=status.HTTP_400_BAD_REQUEST
            )

        if new_status == 'cancelled' and old_status in locked_after_customer_confirm:
            return error_response(
                message='لا يمكن إلغاء الفاتورة بعد تأكيد العميل.',
                status_code=status.HTTP_400_BAD_REQUEST
            )

        if has_driver_assignment and old_status not in {'confirmed', 'preparing', 'on_way'}:
            return error_response(
                message='لا يمكن تحويل الأوردر للدليفري قبل تأكيد العميل على الفاتورة.',
                status_code=status.HTTP_400_BAD_REQUEST
            )

        if new_status in {'preparing', 'on_way'}:
            requested_driver_id = request.data.get('driver_id', order.driver_id)
            if not requested_driver_id:
                return error_response(
                    message='اختار الدليفري أولاً قبل تحويل حالة الأوردر.',
                    status_code=status.HTTP_400_BAD_REQUEST
                )
        
        # قبول الطلب: يجب تعبئة سعر الطلب (سعر التوصيل اختياري)
        if new_status == 'pending_customer_confirm':
            new_total = request.data.get('total_amount')
            if new_total is None:
                new_total = order.total_amount
            try:
                total_value = float(new_total)
            except (TypeError, ValueError):
                total_value = 0.0
            if new_total is None or total_value <= 0:
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
                    driver = Driver.objects.get(id=driver_id, shops=shop_owner)
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
                field_value = request.data[field]
                if field == 'items' and isinstance(field_value, list):
                    field_value = json.dumps(field_value, ensure_ascii=False)
                setattr(order, field, field_value)
        
        order.save()
        sender_type = 'employee' if getattr(request.user, 'user_type', None) == 'employee' else 'shop_owner'
        
        # رسائل تلقائية عند الرفض/الإلغاء/القبول (حسب الصور والـ PDF)
        try:
            if new_status == 'cancelled':
                if old_status == 'pending_customer_confirm':
                    msg_content = 'تم إلغاء الفاتورة.'
                else:
                    msg_content = 'نأسف لعدم استقبال اوردراتكم في الوقت الحالي يرجى المحاوله في وقت لاحق'
                sys_msg = ChatMessage.objects.create(
                    order=order,
                    chat_type='shop_customer',
                    sender_type=sender_type,
                    sender_shop_owner=shop_owner if sender_type == 'shop_owner' else None,
                    sender_employee=request.user if sender_type == 'employee' else None,
                    message_type='text',
                    content=msg_content,
                )
                broadcast_chat_message_to_order(order.id, _chat_message_payload(sys_msg))
            elif new_status == 'pending_customer_confirm':
                if old_status == 'pending_customer_confirm':
                    msg_content = 'تم تعديل الفاتورة وإعادة إرسالها للعميل بانتظار الموافقة.'
                else:
                    msg_content = t(request, 'order_priced_please_confirm')
                sys_msg = ChatMessage.objects.create(
                    order=order,
                    chat_type='shop_customer',
                    sender_type=sender_type,
                    sender_shop_owner=shop_owner if sender_type == 'shop_owner' else None,
                    sender_employee=request.user if sender_type == 'employee' else None,
                    message_type='text',
                    content=msg_content,
                )
                broadcast_chat_message_to_order(order.id, _chat_message_payload(sys_msg))

            if has_driver_assignment and order.driver and (not old_driver or old_driver.id != order.driver.id):
                driver_msg = ChatMessage.objects.create(
                    order=order,
                    chat_type='shop_customer',
                    sender_type=sender_type,
                    sender_shop_owner=shop_owner if sender_type == 'shop_owner' else None,
                    sender_employee=request.user if sender_type == 'employee' else None,
                    message_type='text',
                    content=f'تم تحويل الأوردر للدليفري {order.driver.name}.',
                )
                broadcast_chat_message_to_order(order.id, _chat_message_payload(driver_msg))
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

    period = (request.query_params.get('period') or 'all').strip().lower()
    if period not in {'daily', 'weekly', 'monthly', 'all'}:
        return error_response(
            message=t(request, 'invalid_data'),
            errors={'period': 'Invalid period. Allowed values: daily, weekly, monthly, all.'},
            status_code=status.HTTP_400_BAD_REQUEST
        )

    today = timezone.localdate()
    current_start = None
    previous_start = None
    previous_end = None

    if period == 'daily':
        current_start = today
        previous_start = today - timedelta(days=1)
        previous_end = today - timedelta(days=1)
    elif period == 'weekly':
        current_start = today - timedelta(days=today.weekday())
        previous_start = current_start - timedelta(days=7)
        previous_end = current_start - timedelta(days=1)
    elif period == 'monthly':
        current_start = today.replace(day=1)
        previous_end = current_start - timedelta(days=1)
        previous_start = previous_end.replace(day=1)

    orders_qs = Order.objects.filter(shop_owner=shop_owner)
    invoices_qs = Invoice.objects.filter(shop_owner=shop_owner)

    if current_start:
        orders_qs = orders_qs.filter(created_at__date__gte=current_start)
        invoices_qs = invoices_qs.filter(created_at__date__gte=current_start)

    previous_orders_qs = Order.objects.none()
    previous_invoices_qs = Invoice.objects.none()
    if previous_start and previous_end:
        previous_orders_qs = Order.objects.filter(
            shop_owner=shop_owner,
            created_at__date__gte=previous_start,
            created_at__date__lte=previous_end,
        )
        previous_invoices_qs = Invoice.objects.filter(
            shop_owner=shop_owner,
            created_at__date__gte=previous_start,
            created_at__date__lte=previous_end,
        )

    total_orders = orders_qs.count()
    invoices_count = invoices_qs.count()
    delivered_orders_count = orders_qs.filter(status='delivered').count()
    cancelled_orders_count = orders_qs.filter(status='cancelled').count()
    new_orders_count = orders_qs.filter(status='new').count()

    total_revenue = orders_qs.filter(status='delivered').aggregate(total=Sum('total_amount'))['total'] or 0

    # النقدية: ما تم تحصيله كاش من الطلبات المسلمة
    total_cash_collected = orders_qs.filter(
        status='delivered',
        payment_method='cash'
    ).aggregate(total=Sum('total_amount'))['total'] or 0
    # Field 'custody_amount' does not exist in Driver model.
    cash_with_drivers = 0
    cash_in_treasury = total_cash_collected - cash_with_drivers
    if cash_in_treasury < 0:
        cash_in_treasury = 0
    total_available_cash = cash_in_treasury + cash_with_drivers

    orders_by_status = orders_qs.values('status').annotate(count=Count('id'))
    total_customers = Customer.objects.filter(shop_owner=shop_owner).count()
    total_drivers = Driver.objects.filter(shops=shop_owner).distinct().count()
    available_drivers = Driver.objects.filter(shops=shop_owner, status='available').distinct().count()

    previous_total_orders = previous_orders_qs.count()
    previous_invoices_count = previous_invoices_qs.count()

    def _growth_percentage(current_value, previous_value):
        if previous_value <= 0:
            return 100.0 if current_value > 0 else 0.0
        return round(((current_value - previous_value) / previous_value) * 100, 1)

    success_rate = round((delivered_orders_count / total_orders) * 100, 1) if total_orders else 0.0
    delivered_percentage = round((delivered_orders_count / total_orders) * 100, 1) if total_orders else 0.0
    cancelled_percentage = round((cancelled_orders_count / total_orders) * 100, 1) if total_orders else 0.0

    statistics = {
        # legacy keys (kept for backward compatibility)
        'total_revenue': float(total_revenue),
        'total_orders': total_orders,
        'total_customers': total_customers,
        'total_drivers': total_drivers,
        'available_drivers': available_drivers,
        'new_orders_count': new_orders_count,
        'orders_by_status': {item['status']: item['count'] for item in orders_by_status},

        # reports/dashboard keys
        'period': period,
        'invoices_count': invoices_count,
        'delivered_orders_count': delivered_orders_count,
        'cancelled_orders_count': cancelled_orders_count,
        'success_rate': success_rate,
        'cash_summary': {
            'total_available_cash': float(total_available_cash),
            'cash_in_treasury': float(cash_in_treasury),
            'cash_with_drivers': float(cash_with_drivers),
            'total_cash_collected': float(total_cash_collected),
        },
        'delivery_status': {
            'delivered': {
                'count': delivered_orders_count,
                'percentage': delivered_percentage,
            },
            'cancelled': {
                'count': cancelled_orders_count,
                'percentage': cancelled_percentage,
            },
        },
        'trends': {
            'orders_growth_percent': _growth_percentage(total_orders, previous_total_orders),
            'invoices_growth_percent': _growth_percentage(invoices_count, previous_invoices_count),
        },
        'generated_at': timezone.now().isoformat(),
    }
    
    return success_response(
        data=statistics,
        message=t(request, 'statistics_retrieved_successfully'),
        status_code=status.HTTP_200_OK
    )


@api_view(['GET'])
@permission_classes([IsEmployee])
def shop_dashboard_summary_view(request):
    """
    Dashboard summary cards for cashier employee only.
    GET /api/shop/dashboard/summary/
    """
    current_user = request.user
    if not _is_cashier_user(current_user):
        return error_response(
            message='هذا الإجراء متاح فقط لموظف الكاشير',
            status_code=status.HTTP_403_FORBIDDEN,
            request=request,
        )

    shop_owner = getattr(current_user, 'shop_owner', None)
    if not shop_owner:
        return error_response(
            message='لا يوجد محل مرتبط بهذا الموظف',
            status_code=status.HTTP_404_NOT_FOUND,
            request=request,
        )

    all_orders_qs = Order.objects.filter(shop_owner=shop_owner)
    all_orders_qs = all_orders_qs.filter(employee=current_user)
    employee_summary = {
        'id': current_user.id,
        'name': current_user.name,
        'role': current_user.role,
    }

    delivered_orders_qs = all_orders_qs.filter(status='delivered')
    active_statuses = ['new', 'pending_customer_confirm', 'confirmed', 'preparing', 'on_way']
    active_orders_qs = all_orders_qs.filter(status__in=active_statuses)

    total_orders_value = all_orders_qs.count()
    active_orders_value = active_orders_qs.count()
    net_profit_value = delivered_orders_qs.aggregate(total=Sum('total_amount'))['total'] or 0

    current_start, current_end, previous_start, previous_end = _get_dashboard_period_ranges('month')
    current_orders_qs = _apply_created_date_range(all_orders_qs, current_start, current_end)
    previous_orders_qs = _apply_created_date_range(all_orders_qs, previous_start, previous_end)

    current_total_orders = current_orders_qs.count()
    previous_total_orders = previous_orders_qs.count()
    current_active_orders = current_orders_qs.filter(status__in=active_statuses).count()
    previous_active_orders = previous_orders_qs.filter(status__in=active_statuses).count()
    current_net_profit = current_orders_qs.filter(status='delivered').aggregate(total=Sum('total_amount'))['total'] or 0
    previous_net_profit = previous_orders_qs.filter(status='delivered').aggregate(total=Sum('total_amount'))['total'] or 0

    summary = {
        'total_orders': _build_dashboard_card(
            key='total_orders',
            label='إجمالي الطلبات',
            value=total_orders_value,
            trend_percentage=_growth_percentage(current_total_orders, previous_total_orders),
        ),
        'active_orders': _build_dashboard_card(
            key='active_orders',
            label='الطلبات النشطة',
            value=active_orders_value,
            trend_percentage=_growth_percentage(current_active_orders, previous_active_orders),
        ),
        'net_profit': _build_dashboard_card(
            key='net_profit',
            label='صافي الربح',
            value=net_profit_value,
            trend_percentage=_growth_percentage(float(current_net_profit), float(previous_net_profit)),
            is_currency=True,
        ),
    }

    return success_response(
        data={
            'employee': employee_summary,
            **summary,
            'generated_at': timezone.now().isoformat(),
        },
        message='تم جلب ملخص لوحة التحكم بنجاح',
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
    serializer = EmployeeTokenObtainPairSerializer(data=request.data, context={'request': request})
    
    try:
        serializer.is_valid(raise_exception=True)
    except Exception as e:
        errors = serializer.errors if hasattr(serializer, 'errors') else {'detail': str(e)}
        blocked_message = t(request, 'employee_account_is_blocked')
        errors_str = json.dumps(errors, ensure_ascii=False)
        is_blocked = blocked_message in errors_str
        return error_response(
            message=blocked_message if is_blocked else t(request, 'login_failed'),
            errors=errors,
            status_code=status.HTTP_403_FORBIDDEN if is_blocked else status.HTTP_400_BAD_REQUEST
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


def _normalize_order_items(items):
    normalized_items = []
    for item in items or []:
        item_text = str(item).strip()
        if item_text:
            normalized_items.append(item_text)
    return normalized_items


def _build_customer_order_request_message(customer, address, items):
    lines = ["فاتورة الطلب", f"العميل: {customer.name}"]
    if address:
        lines.append(f"العنوان: {address}")
    for item in _normalize_order_items(items):
        lines.append(f"- {item}")
    return "\n".join(lines)


def _chat_message_payload(message, request=None):
    if request is not None:
        serialized = ChatMessageSerializer(message, context={'request': request}).data
        return {
            'id': serialized.get('id'),
            'sender_type': serialized.get('sender_type'),
            'sender_name': serialized.get('sender_name'),
            'message_type': serialized.get('message_type'),
            'content': serialized.get('content'),
            'is_read': serialized.get('is_read'),
            'created_at': serialized.get('created_at'),
            'audio_file_url': serialized.get('audio_file_url'),
            'image_file_url': serialized.get('image_file_url'),
            'latitude': serialized.get('latitude'),
            'longitude': serialized.get('longitude'),
        }
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


def _resolve_user_type(user):
    user_type = getattr(user, 'user_type', None)
    if user_type in {'customer', 'shop_owner', 'employee', 'driver'}:
        return user_type
    if isinstance(user, Customer):
        return 'customer'
    if isinstance(user, ShopOwner):
        return 'shop_owner'
    if isinstance(user, Employee):
        return 'employee'
    if isinstance(user, Driver):
        return 'driver'
    return None


def _can_user_access_order(order, user, user_type):
    if user_type == 'shop_owner':
        return order.shop_owner_id == getattr(user, 'id', None)
    if user_type == 'employee':
        return order.shop_owner_id == getattr(user, 'shop_owner_id', None)
    if user_type == 'customer':
        return order.customer_id == getattr(user, 'id', None)
    if user_type == 'driver':
        return order.driver_id == getattr(user, 'id', None)
    return False


def _sender_kwargs_for_user(user, user_type):
    sender_kwargs = {'sender_type': user_type}
    if user_type == 'customer':
        sender_kwargs['sender_customer'] = user
    elif user_type == 'shop_owner':
        sender_kwargs['sender_shop_owner'] = user
    elif user_type == 'employee':
        sender_kwargs['sender_employee'] = user
    elif user_type == 'driver':
        sender_kwargs['sender_driver'] = user
    else:
        return None
    return sender_kwargs


def _can_user_access_chat(order, user, user_type, chat_type):
    if user_type == 'shop_owner':
        return chat_type == 'shop_customer' and order.shop_owner_id == user.id
    if user_type == 'employee':
        return chat_type == 'shop_customer' and order.shop_owner_id == getattr(user, 'shop_owner_id', None)
    if user_type == 'driver':
        return chat_type == 'driver_customer' and order.driver_id == user.id
    if user_type == 'customer':
        if order.customer_id != user.id:
            return False
        return chat_type in {'shop_customer', 'driver_customer'}
    return False


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def chat_order_media_upload_view(request, order_id):
    """
    Upload chat media (image/audio) then broadcast instantly to WebSocket subscribers.
    POST /api/chat/order/{order_id}/send-media/
    """
    chat_type = str(request.data.get('chat_type') or 'shop_customer').strip()
    if chat_type not in {'shop_customer', 'driver_customer'}:
        return error_response(
            message=t(request, 'invalid_data'),
            errors={'chat_type': 'chat_type must be shop_customer or driver_customer.'},
            status_code=status.HTTP_400_BAD_REQUEST
        )

    try:
        order = Order.objects.get(id=order_id)
    except Order.DoesNotExist:
        return error_response(
            message=t(request, 'order_not_found'),
            status_code=status.HTTP_404_NOT_FOUND
        )

    user = request.user
    user_type = _resolve_user_type(user)
    if not user_type or not _can_user_access_chat(order, user, user_type, chat_type):
        return error_response(
            message='ليس لديك صلاحية للوصول إلى هذه المحادثة.',
            status_code=status.HTTP_403_FORBIDDEN
        )

    image_file = request.FILES.get('image_file')
    audio_file = request.FILES.get('audio_file')
    if bool(image_file) == bool(audio_file):
        return error_response(
            message=t(request, 'invalid_data'),
            errors={'file': 'Send exactly one file: image_file or audio_file.'},
            status_code=status.HTTP_400_BAD_REQUEST
        )

    requested_type = str(request.data.get('message_type') or '').strip().lower()
    if image_file:
        if requested_type and requested_type != 'image':
            return error_response(
                message=t(request, 'invalid_data'),
                errors={'message_type': 'message_type must be image when image_file is provided.'},
                status_code=status.HTTP_400_BAD_REQUEST
            )
        message_type = 'image'
    else:
        if requested_type and requested_type != 'audio':
            return error_response(
                message=t(request, 'invalid_data'),
                errors={'message_type': 'message_type must be audio when audio_file is provided.'},
                status_code=status.HTTP_400_BAD_REQUEST
            )
        message_type = 'audio'

    sender_kwargs = _sender_kwargs_for_user(user, user_type)
    if not sender_kwargs:
        return error_response(
            message='ليس لديك صلاحية للإرسال في هذه المحادثة.',
            status_code=status.HTTP_403_FORBIDDEN
        )

    message = ChatMessage.objects.create(
        order=order,
        chat_type=chat_type,
        message_type=message_type,
        content=(str(request.data.get('content') or '').strip() or None),
        audio_file=audio_file,
        image_file=image_file,
        **sender_kwargs
    )

    if user_type == 'customer' and chat_type == 'shop_customer':
        order.unread_messages_count = order.messages.filter(
            chat_type='shop_customer',
            is_read=False,
            sender_type='customer'
        ).count()
        order.save(update_fields=['unread_messages_count'])

    payload = _chat_message_payload(message, request=request)
    broadcast_chat_message(order.id, chat_type, payload)
    serialized = ChatMessageSerializer(message, context={'request': request}).data
    return success_response(
        data=serialized,
        message='تم إرسال الوسائط بنجاح',
        status_code=status.HTTP_201_CREATED
    )


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


def _build_file_url(request, file_field):
    if not file_field:
        return None
    try:
        file_url = file_field.url
    except Exception:
        return None
    if request:
        return request.build_absolute_uri(file_url)
    return file_url


def _to_hhmm_time(value):
    if not value or not isinstance(value, str):
        return None
    try:
        return datetime.strptime(value, '%H:%M').time()
    except ValueError:
        return None


def _is_open_now(status_value, today_schedule):
    if status_value == 'closed':
        return False
    if not today_schedule.get('is_working'):
        return False

    start_time = _to_hhmm_time(today_schedule.get('start_time'))
    end_time = _to_hhmm_time(today_schedule.get('end_time'))
    if not start_time or not end_time:
        return status_value in {'open', 'busy'}

    now_time = timezone.localtime().time().replace(second=0, microsecond=0)
    return start_time <= now_time <= end_time


def _build_today_hours_label(today_schedule):
    if not today_schedule.get('is_working'):
        return 'مغلق'
    start_time = today_schedule.get('start_time')
    end_time = today_schedule.get('end_time')
    if not start_time or not end_time:
        return 'غير محدد'
    return f'{start_time} - {end_time}'


def _safe_shop_status(shop):
    try:
        return shop.shop_status
    except ShopStatus.DoesNotExist:
        return None


def _resolve_like_actor_identifier(request):
    user = getattr(request, 'user', None)
    if user and getattr(user, 'is_authenticated', False):
        user_type = _resolve_user_type(user) or 'user'
        user_id = getattr(user, 'id', None)
        if user_id:
            return f'{user_type}:{user_id}'

    identifier = None
    if hasattr(request, 'data'):
        identifier = request.data.get('user_identifier')
    if not identifier and hasattr(request, 'query_params'):
        identifier = request.query_params.get('user_identifier')
    if not identifier:
        return None

    return str(identifier).strip()[:100] or None


def _build_public_gallery_item(image, request, liked_ids=None):
    liked_ids = liked_ids or set()
    shop = image.shop_owner
    return {
        'id': image.id,
        'image_url': _build_file_url(request, image.image),
        'description': image.description or '',
        'likes_count': image.likes_count,
        'is_liked': image.id in liked_ids,
        'uploaded_at': image.uploaded_at,
        'updated_at': image.updated_at,
        'shop': {
            'id': shop.id,
            'shop_name': shop.shop_name,
            'shop_number': shop.shop_number,
            'profile_image_url': _build_file_url(request, shop.profile_image),
        }
    }


def _get_shop_rating_stats(shop):
    order_stats = OrderRating.objects.filter(order__shop_owner=shop).aggregate(
        avg=Avg('shop_rating'),
        count=Count('id')
    )
    review_stats = ShopReview.objects.filter(shop_owner=shop).aggregate(
        avg=Avg('shop_rating'),
        count=Count('id')
    )

    order_count = int(order_stats.get('count') or 0)
    review_count = int(review_stats.get('count') or 0)
    total_count = order_count + review_count
    if not total_count:
        return 0, 0

    order_avg = float(order_stats.get('avg') or 0)
    review_avg = float(review_stats.get('avg') or 0)
    weighted_avg = ((order_avg * order_count) + (review_avg * review_count)) / total_count
    return round(weighted_avg, 1), total_count


def _build_public_shop_payload(shop, request, published_images=None):
    if published_images is None:
        published_images = list(
            shop.gallery_images.filter(status='published').order_by('-uploaded_at')
        )

    status_obj = _safe_shop_status(shop)
    status_value = status_obj.status if status_obj else 'closed'
    status_display = status_obj.get_status_display() if status_obj else 'مغلق'

    schedule_payload = _build_work_schedule_response(shop.work_schedule)
    today_schedule = schedule_payload.get('today', {})
    is_open_now = _is_open_now(status_value, today_schedule)

    average_rating, ratings_count = _get_shop_rating_stats(shop)

    category = shop.shop_category
    cover_image = published_images[0] if published_images else None
    total_likes = sum(image.likes_count for image in published_images)

    return {
        'id': shop.id,
        'owner_name': shop.owner_name,
        'shop_name': shop.shop_name,
        'shop_number': shop.shop_number,
        'description': shop.description or '',
        'phone_number': shop.phone_number,
        'profile_image_url': _build_file_url(request, shop.profile_image),
        'cover_image_url': _build_file_url(request, cover_image.image if cover_image else None),
        'shop_category': (
            {'id': category.id, 'name': category.name}
            if category else None
        ),
        'status': {
            'key': status_value,
            'label': status_display,
            'is_open_now': is_open_now,
            'work_badge': 'مفتوح الآن' if is_open_now else 'مغلق الآن',
        },
        'rating': {
            'average': average_rating if ratings_count else 0,
            'count': int(ratings_count or 0),
        },
        'today_schedule': {
            'day_key': today_schedule.get('day_key'),
            'day_name': today_schedule.get('day_name'),
            'is_working': today_schedule.get('is_working'),
            'start_time': today_schedule.get('start_time'),
            'end_time': today_schedule.get('end_time'),
            'label': _build_today_hours_label(today_schedule),
        },
        'gallery': {
            'published_images_count': len(published_images),
            'total_likes': total_likes,
        },
        'subtitle': (
            f"{category.name} • رقم المحل {shop.shop_number}"
            if category else f"رقم المحل {shop.shop_number}"
        )
    }


def _build_public_shop_card_payload(shop, request, published_images=None):
    full_payload = _build_public_shop_payload(
        shop,
        request,
        published_images=published_images,
    )
    image_url = full_payload['profile_image_url'] or full_payload['cover_image_url']
    return {
        'id': full_payload['id'],
        'shop_name': full_payload['shop_name'],
        'image_url': image_url,
        'rating': full_payload['rating']['average'],
    }


def _build_relative_time_label(dt):
    if not dt:
        return None

    delta = timezone.now() - dt
    days = max(delta.days, 0)
    hours = max(int(delta.total_seconds() // 3600), 0)

    if days >= 365:
        years = days // 365
        return f'منذ {years} سنة'
    if days >= 30:
        months = days // 30
        return f'منذ {months} شهر'
    if days >= 1:
        return f'منذ {days} يوم'
    if hours >= 1:
        return f'منذ {hours} ساعة'
    return 'منذ قليل'


def _build_public_shop_profile_summary_payload(shop, request):
    status_obj = _safe_shop_status(shop)
    status_value = status_obj.status if status_obj else 'closed'
    status_label = status_obj.get_status_display() if status_obj else 'مغلق'
    schedule_payload = _build_work_schedule_response(shop.work_schedule)
    today_schedule = schedule_payload.get('today', {})
    is_open_now = _is_open_now(status_value, today_schedule)
    average_rating, ratings_count = _get_shop_rating_stats(shop)
    category_name = shop.shop_category.name if shop.shop_category else None
    created_since_label = _build_relative_time_label(shop.created_at)

    return {
        'id': shop.id,
        'header': {
            'shop_name': shop.shop_name,
            'profile_image_url': _build_file_url(request, shop.profile_image),
            'category_name': category_name,
            'created_since_label': created_since_label,
            'status': {
                'key': status_value,
                'label': 'مفتوح الآن' if is_open_now else 'مغلق الآن',
                'is_open_now': is_open_now,
                'shop_status_label': status_label,
            },
            'rating': {
                'average': average_rating if ratings_count else 0,
                'count': ratings_count,
            },
        },
       
    }


def _build_public_shop_post_item(image, request, liked_ids=None):
    liked_ids = liked_ids or set()
    return {
        'id': image.id,
        'description': image.description or image.shop_owner.description or '',
        'post_image_url': _build_file_url(request, image.image),
        'likes_count': image.likes_count,
        'is_liked': image.id in liked_ids,
        'published_at': image.uploaded_at,
        'published_since_label': _build_relative_time_label(image.uploaded_at),
    }


@api_view(['GET'])
@permission_classes([IsCustomer])
def public_shops_list_view(request):
    """
    List active shops for customer search screen.
    GET /api/shops/?search=&shop_category_name=&open_now=&with_gallery=&page=&page_size=
    """
    search_query = request.query_params.get('search', '').strip()
    shop_category_id = request.query_params.get('shop_category_id')
    shop_category_name = request.query_params.get('shop_category_name', '').strip()
    open_now_only = _is_true_query_value(request.query_params.get('open_now'))
    with_gallery_only = _is_true_query_value(request.query_params.get('with_gallery'))

    shops = (
        ShopOwner.objects
        .filter(is_active=True)
        .select_related('shop_category', 'shop_status')
        .prefetch_related(
            Prefetch(
                'gallery_images',
                queryset=GalleryImage.objects.filter(status='published').order_by('-uploaded_at'),
                to_attr='published_gallery_images'
            )
        )
        .annotate(
            avg_shop_rating=Avg('orders__rating__shop_rating'),
            ratings_count=Count('orders__rating', distinct=True),
        )
        .order_by('shop_name', 'shop_number')
    )

    if search_query:
        shops = shops.filter(
            Q(shop_name__icontains=search_query) |
            Q(owner_name__icontains=search_query) |
            Q(shop_number__icontains=search_query) |
            Q(description__icontains=search_query)
        )

    if shop_category_id:
        shops = shops.filter(shop_category_id=shop_category_id)
    elif shop_category_name:
        shops = shops.filter(shop_category__name__iexact=shop_category_name)

    if with_gallery_only:
        shops = shops.filter(gallery_images__status='published').distinct()

    payload = []
    for shop in shops:
        published_images = getattr(shop, 'published_gallery_images', [])
        shop_data = _build_public_shop_payload(
            shop,
            request,
            published_images=published_images
        )
        if open_now_only and not shop_data['status']['is_open_now']:
            continue
        payload.append(
            _build_public_shop_card_payload(
                shop,
                request,
                published_images=published_images,
            )
        )

    paginator = PublicShopsPagination()
    page = paginator.paginate_queryset(payload, request)
    if page is not None:
        return paginator.get_paginated_response(page)

    return success_response(
        data=payload,
        message='shops_retrieved_successfully',
        status_code=status.HTTP_200_OK,
        request=request
    )


@api_view(['GET'])
@permission_classes([IsCustomer])
def public_shop_categories_list_view(request):
    """
    List all available shop categories.
    GET /api/shops/shop-categories/
    """
    categories = ShopCategory.objects.filter(is_active=True).order_by('name')
    return success_response(
        data=[{'id': c.id, 'name': c.name} for c in categories],
        message='shop_categories_retrieved_successfully',
        status_code=status.HTTP_200_OK,
        request=request
    )


@api_view(['GET'])
@permission_classes([IsCustomer])
def public_shop_profile_view(request, shop_id):
    """
    Public profile for a single shop.
    GET /api/shops/{shop_id}/profile/
    """
    shop = (
        ShopOwner.objects
        .filter(id=shop_id, is_active=True)
        .select_related('shop_category', 'shop_status')
        .annotate(
            avg_shop_rating=Avg('orders__rating__shop_rating'),
            ratings_count=Count('orders__rating', distinct=True),
        )
        .first()
    )
    if not shop:
        return error_response(
            message=t(request, 'not_found'),
            errors={'shop': 'shop not found.'},
            status_code=status.HTTP_404_NOT_FOUND,
            request=request
        )

    profile_summary = _build_public_shop_profile_summary_payload(
        shop,
        request,
    )

    return Response(
        {
            "status": status.HTTP_200_OK,
            **build_message_fields(
                t(request, 'shop_profile_retrieved_successfully'),
                request=request,
            ),
            "data": {
                "id": profile_summary.get('id'),
                "header": profile_summary.get('header', {}),
            }
        },
        status=status.HTTP_200_OK,
    )


@api_view(['GET'])
@permission_classes([IsCustomer])
def public_shop_posts_view(request, shop_id):
    """
    Public posts for a single shop.
    GET /api/shops/{shop_id}/posts/?page=&page_size=
    """
    shop = ShopOwner.objects.filter(id=shop_id, is_active=True).first()
    if not shop:
        return error_response(
            message=t(request, 'not_found'),
            errors={'shop': 'shop not found.'},
            status_code=status.HTTP_404_NOT_FOUND,
            request=request
        )

    gallery_queryset = GalleryImage.objects.filter(
        shop_owner=shop,
        status='published'
    ).select_related('shop_owner').order_by('-uploaded_at')

    paginator = PublicGalleryPagination()
    page = paginator.paginate_queryset(gallery_queryset, request)
    actor_identifier = _resolve_like_actor_identifier(request)
    liked_ids = set()
    if actor_identifier and page is not None:
        page_ids = [item.id for item in page]
        liked_ids = set(
            ImageLike.objects.filter(
                image_id__in=page_ids,
                user_identifier=actor_identifier
            ).values_list('image_id', flat=True)
        )
    elif actor_identifier:
        queryset_ids = gallery_queryset.values_list('id', flat=True)
        liked_ids = set(
            ImageLike.objects.filter(
                image_id__in=queryset_ids,
                user_identifier=actor_identifier
            ).values_list('image_id', flat=True)
        )

    posts_source = page if page is not None else gallery_queryset
    posts_results = [
        _build_public_shop_post_item(item, request, liked_ids=liked_ids)
        for item in posts_source
    ]

    return Response(
        {
            "status": status.HTTP_200_OK,
            **build_message_fields(
                t(request, 'shop_posts_retrieved_successfully'),
                request=request,
            ),
            "data": {
                "shop_id": shop.id,
                "count": paginator.page.paginator.count if page is not None else gallery_queryset.count(),
                "next": paginator.get_next_link() if page is not None else None,
                "previous": paginator.get_previous_link() if page is not None else None,
                "results": posts_results,
            }
        },
        status=status.HTTP_200_OK,
    )


@api_view(['GET'])
@permission_classes([IsCustomer])
def public_shop_schedule_view(request, shop_id):
    """
    Public weekly schedule for a single shop.
    GET /api/shops/{shop_id}/schedule/
    """
    shop = ShopOwner.objects.filter(id=shop_id, is_active=True).select_related('shop_status').first()
    if not shop:
        return error_response(
            message=t(request, 'not_found'),
            errors={'shop': 'shop not found.'},
            status_code=status.HTTP_404_NOT_FOUND,
            request=request
        )

    schedule_payload = _build_work_schedule_response(shop.work_schedule)
    status_obj = _safe_shop_status(shop)
    status_value = status_obj.status if status_obj else 'closed'
    
    schedule_payload['status'] = {
        'key': status_value,
        'label': status_obj.get_status_display() if status_obj else 'مغلق',
    }
    schedule_payload['is_open_now'] = _is_open_now(status_value, schedule_payload.get('today', {}))

    return success_response(
        data=schedule_payload,
        message=t(request, 'work_schedule_retrieved_successfully'),
        status_code=status.HTTP_200_OK,
        request=request
    )


@api_view(['GET'])
@permission_classes([IsCustomer])
def public_shop_gallery_view(request, shop_id):
    """
    Public gallery posts for a single shop.
    GET /api/shops/{shop_id}/gallery/?search=&sort_by=&page=&page_size=
    """
    shop = ShopOwner.objects.filter(id=shop_id, is_active=True).first()
    if not shop:
        return error_response(
            message=t(request, 'not_found'),
            errors={'shop': 'shop not found.'},
            status_code=status.HTTP_404_NOT_FOUND,
            request=request
        )

    search_query = request.query_params.get('search', '').strip()
    sort_by = request.query_params.get('sort_by', '-uploaded_at')
    allowed_sort_fields = {'uploaded_at', 'likes_count', 'updated_at'}

    queryset = GalleryImage.objects.filter(shop_owner=shop, status='published').select_related('shop_owner')
    if search_query:
        queryset = queryset.filter(description__icontains=search_query)
    if sort_by.lstrip('-') in allowed_sort_fields:
        queryset = queryset.order_by(sort_by)
    else:
        queryset = queryset.order_by('-uploaded_at')

    paginator = PublicGalleryPagination()
    page = paginator.paginate_queryset(queryset, request)

    actor_identifier = _resolve_like_actor_identifier(request)
    liked_ids = set()
    if actor_identifier and page is not None:
        page_ids = [item.id for item in page]
        liked_ids = set(
            ImageLike.objects.filter(
                image_id__in=page_ids,
                user_identifier=actor_identifier
            ).values_list('image_id', flat=True)
        )
    elif actor_identifier:
        queryset_ids = queryset.values_list('id', flat=True)
        liked_ids = set(
            ImageLike.objects.filter(
                image_id__in=queryset_ids,
                user_identifier=actor_identifier
            ).values_list('image_id', flat=True)
        )

    if page is not None:
        data = [_build_public_gallery_item(item, request, liked_ids=liked_ids) for item in page]
        return paginator.get_paginated_response(data)

    data = [_build_public_gallery_item(item, request, liked_ids=liked_ids) for item in queryset]
    return success_response(
        data=data,
        message=t(request, 'images_retrieved_successfully'),
        status_code=status.HTTP_200_OK,
        request=request
    )


@api_view(['GET'])
@permission_classes([IsCustomer])
def public_portfolio_feed_view(request):
    """
    Public portfolio feed across all active shops.
    GET /api/shops/portfolio/?search=&shop_id=&shop_category_id=&sort_by=&page=&page_size=
    """
    search_query = request.query_params.get('search', '').strip()
    shop_id = request.query_params.get('shop_id')
    shop_category_id = request.query_params.get('shop_category_id')
    sort_by = request.query_params.get('sort_by', '-uploaded_at')
    allowed_sort_fields = {'uploaded_at', 'likes_count', 'updated_at'}

    queryset = GalleryImage.objects.filter(
        status='published',
        shop_owner__is_active=True
    ).select_related('shop_owner', 'shop_owner__shop_category')

    if shop_id:
        queryset = queryset.filter(shop_owner_id=shop_id)
    if shop_category_id:
        queryset = queryset.filter(shop_owner__shop_category_id=shop_category_id)
    if search_query:
        queryset = queryset.filter(
            Q(description__icontains=search_query) |
            Q(shop_owner__shop_name__icontains=search_query)
        )
    if sort_by.lstrip('-') in allowed_sort_fields:
        queryset = queryset.order_by(sort_by)
    else:
        queryset = queryset.order_by('-uploaded_at')

    paginator = PublicGalleryPagination()
    page = paginator.paginate_queryset(queryset, request)

    actor_identifier = _resolve_like_actor_identifier(request)
    liked_ids = set()
    if actor_identifier and page is not None:
        page_ids = [item.id for item in page]
        liked_ids = set(
            ImageLike.objects.filter(
                image_id__in=page_ids,
                user_identifier=actor_identifier
            ).values_list('image_id', flat=True)
        )
    elif actor_identifier:
        queryset_ids = queryset.values_list('id', flat=True)
        liked_ids = set(
            ImageLike.objects.filter(
                image_id__in=queryset_ids,
                user_identifier=actor_identifier
            ).values_list('image_id', flat=True)
        )

    if page is not None:
        data = [_build_public_gallery_item(item, request, liked_ids=liked_ids) for item in page]
        return paginator.get_paginated_response(data)

    data = [_build_public_gallery_item(item, request, liked_ids=liked_ids) for item in queryset]
    return success_response(
        data=data,
        message=t(request, 'images_retrieved_successfully'),
        status_code=status.HTTP_200_OK,
        request=request
    )


@api_view(['POST', 'DELETE'])
@permission_classes([IsCustomer])
def public_gallery_like_view(request, image_id):
    """
    Like/unlike a public portfolio image.
    POST/DELETE /api/shops/gallery/{image_id}/like/
    """
    image = GalleryImage.objects.filter(
        id=image_id,
        status='published',
        shop_owner__is_active=True
    ).first()
    if not image:
        return error_response(
            message=t(request, 'image_not_found'),
            status_code=status.HTTP_404_NOT_FOUND,
            request=request
        )

    actor_identifier = _resolve_like_actor_identifier(request)
    if not actor_identifier:
        return error_response(
            message=t(request, 'invalid_data'),
            errors={'user_identifier': ['user_identifier is required for guest likes.']},
            status_code=status.HTTP_400_BAD_REQUEST,
            request=request
        )

    if request.method == 'POST':
        like, created = ImageLike.objects.get_or_create(
            image=image,
            user_identifier=actor_identifier
        )
        if not created:
            return error_response(
                message=t(request, 'this_image_has_already_been_liked'),
                status_code=status.HTTP_400_BAD_REQUEST,
                request=request
            )

        GalleryImage.objects.filter(id=image.id).update(likes_count=F('likes_count') + 1)
        image.refresh_from_db(fields=['likes_count'])
        return success_response(
            data={'image_id': image.id, 'liked': True, 'likes_count': image.likes_count},
            message=t(request, 'image_liked_successfully'),
            status_code=status.HTTP_201_CREATED,
            request=request
        )

    deleted_count, _ = ImageLike.objects.filter(
        image=image,
        user_identifier=actor_identifier
    ).delete()
    if deleted_count == 0:
        return error_response(
            message=t(request, 'this_image_was_not_liked'),
            status_code=status.HTTP_404_NOT_FOUND,
            request=request
        )

    GalleryImage.objects.filter(id=image.id, likes_count__gt=0).update(likes_count=F('likes_count') - 1)
    image.refresh_from_db(fields=['likes_count'])
    return success_response(
        data={'image_id': image.id, 'liked': False, 'likes_count': image.likes_count},
        message=t(request, 'like_removed_successfully'),
        status_code=status.HTTP_200_OK,
        request=request
    )


@api_view(['GET'])
@permission_classes([IsCustomer])
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
@permission_classes([IsCustomer])
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

            # First chat message in the order thread (request/invoice draft card content).
            try:
                request_message = _build_customer_order_request_message(
                    customer=customer,
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

    if order.status in {'confirmed', 'preparing', 'on_way', 'delivered'}:
        return error_response(
            message='لا يمكن إلغاء الطلب بعد قبول الفاتورة.',
            status_code=status.HTTP_400_BAD_REQUEST
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
        if 'name' in request.data:
            customer.name = request.data.get('name')
        if request.FILES.get('profile_image'):
            customer.profile_image = request.FILES['profile_image']
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

def _update_driver_average_rating(driver):
    if not driver:
        return

    avg_rating = OrderRating.objects.filter(
        order__driver=driver
    ).aggregate(avg=Avg('driver_rating'))['avg']
    if avg_rating:
        driver.rating = round(avg_rating, 2)
        driver.save()


def _create_rating_response(request, order, data):
    if order.customer_id != request.user.id:
        return error_response(
            message=t(request, 'order_not_found'),
            status_code=status.HTTP_404_NOT_FOUND,
        )

    if order.status != 'delivered':
        return error_response(
            message=t(request, 'cannot_rate_an_incomplete_order'),
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    if hasattr(order, 'rating'):
        return error_response(
            message=t(request, 'this_order_has_already_been_rated'),
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    rating = OrderRating.objects.create(
        order=order,
        customer=order.customer,
        shop_rating=data['shop_rating'],
        comment=data.get('comment', '')
    )

    response_serializer = OrderRatingSerializer(rating)
    response_data = dict(response_serializer.data)
    response_data.pop('driver_rating', None)
    response_data.pop('food_rating', None)
    return success_response(
        data=response_data,
        message=t(request, 'rating_added_successfully'),
        status_code=status.HTTP_201_CREATED,
    )


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
    order_id = data.get('order_id')
    shop_id = data.get('shop_id')
    
    if order_id:
        try:
            order = Order.objects.get(id=order_id)
        except Order.DoesNotExist:
            return error_response(message=t(request, 'order_not_found'), status_code=status.HTTP_404_NOT_FOUND)
    else:
        order = Order.objects.filter(
            shop_owner_id=shop_id,
            customer_id=request.user.id,
            status='delivered',
            rating__isnull=True,
        ).select_related('customer', 'driver').order_by('-updated_at', '-id').first()
        if not order:
            return error_response(
                message=t(
                    request,
                    'no_delivered_order_available_for_rating',
                    default='لا يوجد طلب مكتمل متاح لتقييم هذا المحل',
                ),
                status_code=status.HTTP_404_NOT_FOUND,
            )

    if order.customer_id != request.user.id:
        return error_response(message=t(request, 'order_not_found'), status_code=status.HTTP_404_NOT_FOUND)
    
    if order.status != 'delivered':
        return error_response(message=t(request, 'cannot_rate_an_incomplete_order'), status_code=status.HTTP_400_BAD_REQUEST)
    
    if hasattr(order, 'rating'):
        return error_response(message=t(request, 'this_order_has_already_been_rated'), status_code=status.HTTP_400_BAD_REQUEST)
    
    rating = OrderRating.objects.create(
        order=order,
        customer=order.customer,
        shop_rating=data['shop_rating'],
        comment=data.get('comment', '')
    )
    
    # تحديث تقييم السائق إن وجد
    if False and order.driver and data.get('driver_rating'):
        driver = order.driver
        avg_rating = OrderRating.objects.filter(
            order__driver=driver
        ).aggregate(avg=Avg('driver_rating'))['avg']
        if avg_rating:
            driver.rating = round(avg_rating, 2)
            driver.save()
    
    response_serializer = OrderRatingSerializer(rating)
    response_data = dict(response_serializer.data)
    response_data.pop('driver_rating', None)
    response_data.pop('food_rating', None)
    return success_response(data=response_data, message=t(request, 'rating_added_successfully'), status_code=status.HTTP_201_CREATED)


@api_view(['POST'])
@permission_classes([IsCustomer])
def shop_rating_create_view(request, shop_id):
    """
    Rate a shop from the customer app.
    POST /api/shops/{shop_id}/rating/
    Body: { "shop_rating": 5, "comment": "..." }
    """
    serializer = ShopRatingCreateSerializer(data=request.data)
    if not serializer.is_valid():
        return error_response(
            message=t(request, 'invalid_data'),
            errors=serializer.errors,
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    data = serializer.validated_data
    shop = ShopOwner.objects.filter(id=shop_id, is_active=True).first()
    if not shop:
        return error_response(
            message=t(request, 'not_found'),
            status_code=status.HTTP_404_NOT_FOUND,
        )

    existing_review = (
        ShopReview.objects
        .filter(shop_owner=shop)
        .filter(
            Q(customer_id=request.user.id) |
            Q(customer__phone_number=getattr(request.user, 'phone_number', None))
        )
        .first()
    )
    if existing_review:
        return error_response(
            message=t(request, 'this_shop_has_already_been_rated'),
 
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    try:
        review = ShopReview.objects.create(
            shop_owner=shop,
            customer_id=request.user.id,
            shop_rating=data['shop_rating'],
            comment=data.get('comment', ''),
        )
    except IntegrityError:
        return error_response(
            message=t(request, 'this_shop_has_already_been_rated'),
        
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    response_data = {
        'id': review.id,
        'shop_id': shop.id,
        'customer_id': request.user.id,
        'shop_rating': review.shop_rating,
        'comment': review.comment or '',
        'created_at': review.created_at,
        'updated_at': review.updated_at,
        'is_updated': False,
    }
    return success_response(
        data=response_data,
        message=t(request, 'rating_added_successfully'),
        status_code=status.HTTP_201_CREATED,
    )
 
 
@api_view(['GET'])
@permission_classes([IsShopOwner])
def order_rating_view(request, order_id):
    """
    عرض تقييم طلب
    GET /api/orders/{id}/rating/
    """
    try:
        rating = OrderRating.objects.get(order_id=order_id, order__shop_owner=request.user)
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

    user_type = _resolve_user_type(request.user)
    if not _can_user_access_order(order, request.user, user_type):
        return error_response(
            message=t(request, 'permission_only_shop_staff'),
            status_code=status.HTTP_403_FORBIDDEN
        )
    
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
