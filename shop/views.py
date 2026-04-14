from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework.response import Response
from rest_framework.pagination import PageNumberPagination
import json
from django.apps import apps as django_apps
from django.conf import settings
from django.shortcuts import render
from django.core.cache import cache
from django.db import IntegrityError, transaction
from django.db.models import Q, Count, Sum, F, Avg, Prefetch
from django.utils import timezone
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from rest_framework_simplejwt.tokens import RefreshToken
from .models import (
    ShopStatus, Customer, CustomerAddress, Driver, Order, ChatMessage,
    CustomerSupportConversation, CustomerSupportMessage,
    Invoice, Employee, Product, Category, Offer, OfferLike, OrderRating, ShopReview, PaymentMethod,
    Notification, Cart, CartItem, ShopDriver
)
from gallery.models import WorkSchedule, GalleryImage, ImageLike
from .serializers import (
    ShopCategorySerializer,
    ShopStatusSerializer,
    CustomerSerializer,
    CustomerAppProfileSerializer,
    CustomerProfileUpdateSerializer,
    CustomerCreateSerializer,
    CustomerAddressSerializer,
    CustomerAppAddressSerializer,
    DriverSerializer,
    DriverAppSerializer,
    DriverProfileSerializer,
    DriverProfileResponseSerializer,
    DriverProfileUpdateSerializer,
    DriverCreateSerializer,
    DriverRegisterSerializer,
    OrderSerializer,
    ShopOrderListSerializer,
    OrderCreateSerializer,
    CustomerOrderCreateSerializer,
    CustomerSupportConversationCreateSerializer,
    CustomerSupportConversationSerializer,
    CustomerSupportMessageSerializer,
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
    PublicOfferSerializer,
    OfferManagementSerializer,
    OfferCreateUpdateSerializer,
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
    AppStatusSerializer,
)
from .permissions import IsShopOwner, IsCustomer, IsDriver, IsEmployee, IsShopOwnerOrEmployee
from user.models import (
    ShopCategory,
    ShopOwner,
    WORK_SCHEDULE_DAYS,
    WORK_SCHEDULE_DAY_LABELS,
    default_work_schedule,
)
from user.utils import success_response, error_response, build_message_fields, t, localize_message, build_absolute_file_url
from user.otp_service import send_otp as otp_send, verify_otp as otp_verify, normalize_phone
from .websocket_utils import (
    notify_order_update,
    notify_driver_assigned,
    notify_new_order,
    broadcast_chat_message_to_order,
    broadcast_chat_message_to_customer,
    broadcast_chat_message,
    notify_support_conversation_update,
    notify_support_message,
    notify_shop_status_updated,
    notify_driver_status_updated,
)
from .customer_app_realtime import broadcast_customer_order_removed
from .presence import format_utc_iso8601
from .driver_chat_service import request_transfer_for_order, sync_order_assignment_change
from .driver_realtime import (
    build_driver_order_payload,
    clear_all_driver_rejections,
    clear_driver_rejection,
    emit_assigned_order_upsert,
    emit_available_order_remove,
    emit_order_accepted,
    emit_order_rejected,
    emit_order_transferred,
    get_available_order_for_driver,
    record_driver_rejection,
    sync_driver_order_state,
)


def shop_dashboard_ui_view(request):
    """واجهة تجريبية/تشغيلية للوحة المحل (Shop frontend)."""
    return render(request, 'shop/dashboard_ui.html')


def driver_dashboard_ui_view(request):
    """Experimental operational UI for the delivery dashboard."""
    return render(request, 'shop/driver_dashboard_ui.html')


def driver_store_chats_ui_view(request):
    """Experimental UI for driver-side shop chats."""
    return render(request, 'shop/driver_store_chats_ui.html')


def customer_dashboard_ui_view(request):
    """Experimental operational UI for the customer dashboard."""
    return render(request, 'shop/customer_dashboard_ui.html')


def driver_chats_ui_view(request):
    """Operational UI for shop-side driver chats."""
    return render(request, 'shop/driver_chats_ui.html')


def _app_status_bool(value):
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    return str(value).strip().lower() in {'1', 'true', 'yes', 'on'}


def _app_status_text(value, default=''):
    if value is None:
        return default
    text = str(value).strip()
    return text if text else default


def _app_status_int(value):
    if value in (None, ''):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _build_app_status_payload():
    current_version = _app_status_text(
        getattr(settings, 'APP_STATUS_FORCE_UPDATE_CURRENT_VERSION', ''),
        '',
    )
    required_version = _app_status_text(
        getattr(settings, 'APP_STATUS_FORCE_UPDATE_REQUIRED_VERSION', current_version),
        current_version,
    )

    return {
        'maintenance_mode': _app_status_bool(
            getattr(settings, 'APP_STATUS_MAINTENANCE_MODE', False)
        ),
        'maintenance': {
            'title_ar': _app_status_text(
                getattr(settings, 'APP_STATUS_MAINTENANCE_TITLE_AR', ''),
                'التطبيق تحت الصيانة حاليًا',
            ),
            'title_en': _app_status_text(
                getattr(settings, 'APP_STATUS_MAINTENANCE_TITLE_EN', ''),
                'The app is currently under maintenance',
            ),
            'message_ar': _app_status_text(
                getattr(settings, 'APP_STATUS_MAINTENANCE_MESSAGE_AR', ''),
                'نقوم الآن بتنفيذ تحديثات وتحسينات مهمة. نعتذر عن الإزعاج وسيعود التطبيق قريبًا.',
            ),
            'message_en': _app_status_text(
                getattr(settings, 'APP_STATUS_MAINTENANCE_MESSAGE_EN', ''),
                'We are applying important updates and improvements. Sorry for the interruption.',
            ),
            'window_label_ar': _app_status_text(
                getattr(settings, 'APP_STATUS_MAINTENANCE_WINDOW_LABEL_AR', ''),
                '',
            ),
            'window_label_en': _app_status_text(
                getattr(settings, 'APP_STATUS_MAINTENANCE_WINDOW_LABEL_EN', ''),
                '',
            ),
            'show_contact_support': _app_status_bool(
                getattr(settings, 'APP_STATUS_SHOW_CONTACT_SUPPORT', False)
            ),
            'support_whatsapp': _app_status_text(
                getattr(settings, 'APP_STATUS_SUPPORT_WHATSAPP', ''),
                '',
            ),
            'estimated_minutes': _app_status_int(
                getattr(settings, 'APP_STATUS_ESTIMATED_MINUTES', None)
            ),
        },
        'force_update': {
            'enabled': _app_status_bool(
                getattr(settings, 'APP_STATUS_FORCE_UPDATE_ENABLED', False)
            ),
            'current_version': current_version,
            'required_version': required_version,
        },
    }


@api_view(['GET'])
@permission_classes([AllowAny])
def app_status_view(request):
    """Public splash endpoint for maintenance mode and optional force-update flags."""
    serializer = AppStatusSerializer(instance=_build_app_status_payload())
    response = Response(
        {
            'success': True,
            'data': serializer.data,
        },
        status=status.HTTP_200_OK,
    )
    response['Cache-Control'] = 'no-store'
    return response


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


class OfferPagination(PageNumberPagination):
    """Pagination for offer feeds."""

    page_size = 20
    page_size_query_param = 'page_size'
    max_page_size = 100

    def get_paginated_response(self, data):
        response_data = {
            "status": status.HTTP_200_OK,
            **build_message_fields(
                t(getattr(self, "request", None), "offers_retrieved_successfully"),
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


def _cleanup_expired_offers():
    grace_cutoff = timezone.localdate() - timedelta(days=7)
    Offer.objects.filter(end_date__lt=grace_cutoff).delete()


def _apply_offer_status_filter(queryset, status_filter):
    today = timezone.localdate()
    grace_cutoff = today - timedelta(days=7)

    if status_filter == 'all':
        return queryset
    if status_filter == 'active':
        return queryset.filter(
            is_active=True,
            start_date__lte=today,
            end_date__gte=today,
        )
    if status_filter == 'scheduled':
        return queryset.filter(
            is_active=True,
            start_date__gt=today,
        )
    if status_filter == 'expired':
        return queryset.filter(
            is_active=True,
            end_date__lt=today,
            end_date__gte=grace_cutoff,
        )
    return None


def _apply_offer_sorting(queryset, sort_by):
    sort_options = {
        'newest': ('-created_at', '-id'),
        'oldest': ('created_at', 'id'),
        'most_viewed': ('-views_count', '-created_at', '-id'),
    }
    ordering = sort_options.get(sort_by)
    if ordering is None:
        return None
    return queryset.order_by(*ordering)


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
DRIVER_APP_ORDER_STATUSES = {'confirmed', 'preparing', 'on_way'}
DRIVER_TRANSFER_REASONS = [
    {'key': 'vehicle_issue', 'label': '??? ?? ???????', 'requires_note': False},
    {'key': 'emergency', 'label': '??? ???? / ????', 'requires_note': False},
    {'key': 'store_delay', 'label': '????? ???? ?? ??????', 'requires_note': False},
    {'key': 'other', 'label': '??? ???', 'requires_note': True},
]
PY_WEEKDAY_TO_WORK_DAY = {
    0: 'monday',
    1: 'tuesday',
    2: 'wednesday',
    3: 'thursday',
    4: 'friday',
    5: 'saturday',
    6: 'sunday',
}

# Shop schedules are entered in Egypt local time, so availability checks
# should not use the project's UTC default timezone.
SHOP_SCHEDULE_TIMEZONE = ZoneInfo('Africa/Cairo')


def _shop_schedule_localdate():
    return timezone.localdate(timezone=SHOP_SCHEDULE_TIMEZONE)


def _shop_schedule_localtime():
    return timezone.localtime(timezone=SHOP_SCHEDULE_TIMEZONE)


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

    today_key = PY_WEEKDAY_TO_WORK_DAY.get(_shop_schedule_localdate().weekday(), 'monday')
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


def _active_shop_drivers_queryset(shop_owner):
    return (
        Driver.objects
        .filter(driver_shops__shop_owner=shop_owner, driver_shops__status='active')
        .distinct()
    )


def _get_shop_driver_relation(shop_owner, staff_id, relation_statuses=None):
    queryset = ShopDriver.objects.select_related('driver').filter(
        shop_owner=shop_owner,
        driver_id=staff_id,
    )
    if relation_statuses is not None:
        queryset = queryset.filter(status__in=relation_statuses)
    return queryset.first()


def _get_staff_member(shop_owner, staff_type, staff_id):
    if staff_type == STAFF_TYPE_EMPLOYEE:
        try:
            return Employee.objects.get(id=staff_id, shop_owner=shop_owner), None
        except Employee.DoesNotExist:
            return None, 'employee_not_found'

    relation = _get_shop_driver_relation(shop_owner, staff_id, relation_statuses=['active'])
    if relation:
        return relation.driver, None
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


def _find_driver_by_phone(phone_number):
    normalized_phone = normalize_phone(phone_number)
    if not normalized_phone:
        return None

    return (
        Driver.objects
        .filter(phone_number__in=_driver_phone_variants(normalized_phone))
        .order_by('-updated_at')
        .first()
    )


def _get_driver_from_request(request):
    user = request.user
    if isinstance(user, Driver):
        return user
    try:
        return Driver.objects.get(id=user.id)
    except (Driver.DoesNotExist, AttributeError):
        return None


DRIVER_PHONE_CHANGE_OTP_TTL_SECONDS = 600


def _driver_phone_change_cache_key(driver_id):
    return f"driver_phone_change:{driver_id}"


def _coerce_bool(value):
    if isinstance(value, bool):
        return value
    if value is None:
        return None

    normalized = str(value).strip().lower()
    if normalized in {'1', 'true', 'yes', 'on'}:
        return True
    if normalized in {'0', 'false', 'no', 'off'}:
        return False
    return None


def _humanize_elapsed_label(dt_value):
    if not dt_value:
        return None

    now_value = timezone.now()
    if timezone.is_naive(dt_value):
        dt_value = timezone.make_aware(dt_value, timezone.get_current_timezone())
    delta = now_value - dt_value
    total_minutes = max(int(delta.total_seconds() // 60), 0)

    if total_minutes < 1:
        return 'الآن'
    if total_minutes < 60:
        return f'منذ {total_minutes} دقيقة'

    total_hours = total_minutes // 60
    if total_hours < 24:
        return f'منذ {total_hours} ساعة'

    total_days = total_hours // 24
    if total_days < 7:
        return f'منذ {total_days} يوم'

    return dt_value.strftime('%Y-%m-%d')


def _build_driver_branch_label(shop_owner):
    description = str(getattr(shop_owner, 'description', '') or '').strip()
    if description:
        return description

    if getattr(shop_owner, 'shop_category', None):
        return shop_owner.shop_category.name

    if getattr(shop_owner, 'phone_number', None):
        return shop_owner.phone_number

    return shop_owner.shop_number


def _build_driver_status_panel(driver, active_orders_count):
    is_online = driver.status != 'offline'
    can_receive_orders = driver.status == 'available'

    if driver.status == 'busy':
        title = 'أنت مشغول الآن'
        subtitle = 'لديك طلبات جارية حتى الآن.'
    elif is_online:
        title = 'أنت متصل الآن'
        subtitle = 'جاهز لاستقبال الطلبات الجديدة.'
    else:
        title = 'أنت غير متصل الآن'
        subtitle = 'فعّل الاتصال لتبدأ استقبال الطلبات.'

    return {
        'is_online': is_online,
        'can_receive_orders': can_receive_orders,
        'status': driver.status,
        'status_display': driver.get_status_display(),
        'active_orders_count': active_orders_count,
        'title': title,
        'subtitle': subtitle,
    }


def _build_driver_invitation_item(shop_driver, request):
    shop_owner = shop_driver.shop_owner
    category = getattr(shop_owner, 'shop_category', None)

    return {
        'invitation_id': shop_driver.id,
        'status': shop_driver.status,
        'message': 'دعوة للانضمام كمندوب توصيل معتمد للطلبات عبر التطبيق.',
        'invited_at': shop_driver.joined_at.isoformat() if shop_driver.joined_at else None,
        'invited_since_label': _humanize_elapsed_label(shop_driver.joined_at),
        'shop': {
            'id': shop_owner.id,
            'shop_name': shop_owner.shop_name,
            'shop_number': shop_owner.shop_number,
            'shop_logo_url': _build_file_url(request, shop_owner.profile_image),
            'branch_label': _build_driver_branch_label(shop_owner),
            'category': (
                {'id': category.id, 'name': category.name}
                if category else None
            ),
        },
    }


def _build_driver_shop_overview_item(shop_owner, request):
    new_orders_count = int(getattr(shop_owner, 'new_orders_count', 0) or 0)
    status_obj = _safe_shop_status(shop_owner)

    if new_orders_count <= 0:
        new_orders_label = 'لا توجد طلبات'
    elif new_orders_count == 1:
        new_orders_label = '1 طلب جديد'
    else:
        new_orders_label = f'{new_orders_count} طلبات جديدة'

    return {
        'shop_id': shop_owner.id,
        'shop_name': shop_owner.shop_name,
        'shop_number': shop_owner.shop_number,
        'shop_logo_url': _build_file_url(request, shop_owner.profile_image),
        'branch_label': _build_driver_branch_label(shop_owner),
        'new_orders_count': new_orders_count,
        'new_orders_label': new_orders_label,
        'has_new_orders': new_orders_count > 0,
        'shop_status': {
            'key': status_obj.status if status_obj else 'closed',
            'label': status_obj.get_status_display() if status_obj else 'مغلق',
        },
    }


def _get_driver_order_status_label(order):
    if order.status in DRIVER_APP_ORDER_STATUSES:
        return 'قيد التوصيل'
    return order.get_status_display()


def _to_float_or_none(value):
    try:
        if value is None or value == '':
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _parse_driver_order_items(items_value):
    parsed_items = items_value
    if isinstance(items_value, str):
        try:
            parsed_items = json.loads(items_value)
        except (TypeError, ValueError):
            parsed_items = [items_value]

    if not isinstance(parsed_items, list):
        parsed_items = [parsed_items]

    results = []
    for index, item in enumerate(parsed_items, start=1):
        if isinstance(item, dict):
            name = str(
                item.get('name')
                or item.get('title')
                or item.get('product_name')
                or item.get('item_name')
                or f'بند {index}'
            ).strip()
            quantity = item.get('quantity', item.get('qty', item.get('count', 1)))
            try:
                quantity = int(float(quantity))
            except (TypeError, ValueError):
                quantity = 1

            line_total = _to_float_or_none(
                item.get('line_total', item.get('total_price', item.get('subtotal', item.get('total'))))
            )
            if line_total is None:
                unit_price = _to_float_or_none(item.get('unit_price', item.get('price')))
                if unit_price is not None:
                    line_total = round(unit_price * quantity, 2)
        else:
            name = str(item or '').strip()
            if not name:
                continue
            quantity = 1
            line_total = None

        results.append({
            'name': name,
            'quantity': quantity,
            'line_total': line_total,
        })

    return results


def _build_driver_order_address_text(order):
    raw_address = str(getattr(order, 'address', '') or '').strip()
    if raw_address:
        return raw_address

    delivery_address = getattr(order, 'delivery_address', None)
    if not delivery_address:
        return ''

    address_parts = [
        str(delivery_address.full_address or '').strip(),
        str(delivery_address.city or '').strip(),
        str(delivery_address.area or '').strip(),
        str(delivery_address.street_name or '').strip(),
    ]
    return next((part for part in address_parts if part), '')


def _build_driver_order_invoice_payload(order):
    return {
        'items': _parse_driver_order_items(order.items),
        'payment_method': order.payment_method,
        'amount_to_collect': _to_float_or_none(order.total_amount) or 0.0,
    }


def _get_driver_order_or_none(driver, order_id, statuses=None):
    queryset = Order.objects.select_related('shop_owner', 'customer', 'delivery_address').filter(
        id=order_id,
        driver=driver,
    )
    if statuses is not None:
        queryset = queryset.filter(status__in=statuses)
    return queryset.first()


def _respond_to_driver_invitation(request, shop_driver, driver, action, normalized_phone=None):
    shop_owner = shop_driver.shop_owner
    normalized_phone = normalize_phone(normalized_phone or driver.phone_number or '')

    if action == 'reject':
        shop_driver.status = 'rejected'
        shop_driver.save(update_fields=['status'])
        return success_response(
            data={
                'action': 'reject',
                'invitation_id': shop_driver.id,
                'shop': {
                    'id': shop_owner.id,
                    'shop_name': shop_owner.shop_name,
                    'shop_number': shop_owner.shop_number,
                },
                'pending_invitations_count': ShopDriver.objects.filter(driver=driver, status='pending').count(),
            },
            message=t(request, 'driver_invitation_rejected_successfully'),
            status_code=status.HTTP_200_OK,
        )

    if not driver.password:
        return error_response(
            message=t(request, 'driver_account_not_ready_contact_support'),
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    driver_update_fields = []
    if normalized_phone and driver.phone_number != normalized_phone:
        driver.phone_number = normalized_phone
        driver_update_fields.append('phone_number')
    if driver.status == 'offline':
        driver.status = 'available'
        driver_update_fields.append('status')
    if driver_update_fields:
        driver.save(update_fields=driver_update_fields)

    shop_driver.status = 'active'
    shop_driver.save(update_fields=['status'])
    try:
        notify_driver_status_updated(driver)
    except Exception as e:
        print(f"driver_status_updated WebSocket error: {e}")

    return success_response(
        data={
            'action': 'accept',
            'invitation_id': shop_driver.id,
            'shop': {
                'id': shop_owner.id,
                'shop_name': shop_owner.shop_name,
                'shop_number': shop_owner.shop_number,
            },
            'driver': DriverAppSerializer(driver, context={'request': request}).data,
            'pending_invitations_count': ShopDriver.objects.filter(driver=driver, status='pending').count(),
            'active_shops_count': ShopDriver.objects.filter(driver=driver, status='active').count(),
        },
        message=t(request, 'driver_invitation_accepted_successfully'),
        status_code=status.HTTP_200_OK,
    )


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
            errors={'phone_number': [t(request, 'invalid_phone_number')]},
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
    response_data['invitation_note'] = 'Driver should respond using /api/driver/invitations/{invitation_id}/respond/'
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
        driver_base_queryset = _active_shop_drivers_queryset(shop_owner)

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
            try:
                notify_driver_status_updated(staff_member)
            except Exception as e:
                print(f"driver_status_updated WebSocket error: {e}")

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
        if staff_type == STAFF_TYPE_DRIVER:
            pending_or_non_active_relation = _get_shop_driver_relation(
                request.user,
                staff_id,
                relation_statuses=['pending', 'blocked', 'rejected'],
            )
            if pending_or_non_active_relation:
                pending_or_non_active_relation.delete()
                return success_response(
                    data={
                        'driver_id': staff_id,
                        'shop_id': request.user.id,
                        'remaining_active_shops_count': ShopDriver.objects.filter(
                            driver_id=staff_id,
                            status='active',
                        ).count(),
                    },
                    message=t(request, 'driver_removed_from_shop_successfully'),
                    status_code=status.HTTP_200_OK
                )
        return error_response(
            message=t(request, not_found_message),
            status_code=status.HTTP_404_NOT_FOUND
        )

    if staff_type == STAFF_TYPE_DRIVER:
        active_orders_count = Order.objects.filter(
            shop_owner=request.user,
            driver=staff_member,
            status__in=['confirmed', 'preparing', 'on_way'],
        ).count()
        if active_orders_count > 0:
            return error_response(
                message=t(request, 'driver_cannot_be_removed_from_shop_with_active_orders'),
                status_code=status.HTTP_400_BAD_REQUEST,
            )

        shop_driver_relation = ShopDriver.objects.filter(
            shop_owner=request.user,
            driver=staff_member,
        ).first()
        if shop_driver_relation:
            shop_driver_relation.delete()

        remaining_active_shops_count = ShopDriver.objects.filter(
            driver=staff_member,
            status='active',
        ).count()
        if remaining_active_shops_count == 0 and staff_member.status != 'offline':
            staff_member.status = 'offline'
            staff_member.save(update_fields=['status', 'updated_at'])
            try:
                notify_driver_status_updated(staff_member)
            except Exception as e:
                print(f"driver_status_updated WebSocket error: {e}")

        return success_response(
            data={
                'driver_id': staff_member.id,
                'shop_id': request.user.id,
                'remaining_active_shops_count': remaining_active_shops_count,
            },
            message=t(request, 'driver_removed_from_shop_successfully'),
            status_code=status.HTTP_200_OK
        )

    staff_member.delete()
    return success_response(
        message=t(request, 'employee_deleted_successfully'),
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
        active_orders_count = staff_member.orders.filter(status__in=['confirmed', 'preparing', 'on_way']).count()
        if blocked:
            staff_member.status = 'offline'
        elif staff_member.status == 'offline':
            staff_member.status = 'busy' if active_orders_count > 0 else 'available'
        staff_member.save()
        try:
            notify_driver_status_updated(staff_member)
        except Exception as e:
            print(f"driver_status_updated WebSocket error: {e}")

    response_data = _serialize_staff_member(staff_member, staff_type, request)
    response_data['blocked'] = blocked
    return success_response(
        data=response_data,
        message=t(request, 'staff_block_status_updated_successfully'),
        status_code=status.HTTP_200_OK
    )


@api_view(['GET'])
@permission_classes([IsDriver])
def driver_invitations_view(request):
    """
    List pending invitations for the logged-in driver.
    GET /api/driver/invitations/
    """
    driver = _get_driver_from_request(request)
    if not driver:
        return error_response(message=t(request, 'driver_not_found'), status_code=status.HTTP_404_NOT_FOUND)

    invitations = (
        ShopDriver.objects
        .filter(driver=driver, status='pending')
        .select_related('shop_owner', 'shop_owner__shop_category')
        .order_by('-joined_at', '-id')
    )

    return success_response(
        data={
            'pending_count': invitations.count(),
            'invitations': [_build_driver_invitation_item(item, request) for item in invitations],
        },
        message=t(request, 'driver_invitations_retrieved_successfully'),
        status_code=status.HTTP_200_OK,
    )


@api_view(['POST'])
@permission_classes([IsDriver])
def driver_invitation_action_view(request, invitation_id):
    """
    Accept or reject a pending invitation for the logged-in driver.
    POST /api/driver/invitations/{invitation_id}/respond/
    Body: { "action": "accept|reject" }
    """
    driver = _get_driver_from_request(request)
    if not driver:
        return error_response(message=t(request, 'driver_not_found'), status_code=status.HTTP_404_NOT_FOUND)

    action = str(request.data.get('action', '')).strip().lower()
    if action not in {'accept', 'reject'}:
        return error_response(
            message=t(request, 'invalid_data'),
            errors={'action': [t(request, 'driver_invitation_action_must_be_accept_or_reject')]},
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    try:
        shop_driver = ShopDriver.objects.select_related('shop_owner').get(
            id=invitation_id,
            driver=driver,
            status='pending',
        )
    except ShopDriver.DoesNotExist:
        return error_response(
            message=t(request, 'driver_invitation_not_found'),
            status_code=status.HTTP_404_NOT_FOUND,
        )

    return _respond_to_driver_invitation(
        request=request,
        shop_driver=shop_driver,
        driver=driver,
        action=action,
    )


@api_view(['GET'])
@permission_classes([IsDriver])
def driver_dashboard_view(request):
    """
    Driver home dashboard payload.
    GET /api/driver/home/
    """
    driver = _get_driver_from_request(request)
    if not driver:
        return error_response(message=t(request, 'driver_not_found'), status_code=status.HTTP_404_NOT_FOUND)

    active_orders_qs = driver.orders.filter(status__in=['confirmed', 'preparing', 'on_way'])
    in_delivery_orders_qs = driver.orders.filter(status__in=['preparing', 'on_way'])
    completed_orders_qs = driver.orders.filter(status='delivered')
    pending_invitations_count = ShopDriver.objects.filter(driver=driver, status='pending').count()
    unread_notifications_count = Notification.objects.filter(driver=driver, is_read=False).count()

    active_shops = (
        ShopOwner.objects
        .filter(shop_drivers__driver=driver, shop_drivers__status='active')
        .select_related('shop_category')
        .annotate(new_orders_count=Count('orders', filter=Q(orders__status='new'), distinct=True))
        .distinct()
        .order_by('-new_orders_count', 'shop_name')
    )

    return success_response(
        data={
            'driver': DriverAppSerializer(driver, context={'request': request}).data,
            'notifications': {
                'unread_count': unread_notifications_count,
            },
            'availability': _build_driver_status_panel(driver, active_orders_qs.count()),
            'stats': {
                'current_deliveries_count': in_delivery_orders_qs.count(),
                'active_orders_count': active_orders_qs.count(),
                'completed_orders_count': completed_orders_qs.count(),
            },
            'counts': {
                'active_shops_count': active_shops.count(),
                'pending_invitations_count': pending_invitations_count,
            },
            'shops': [_build_driver_shop_overview_item(shop, request) for shop in active_shops],
        },
        message=t(request, 'driver_dashboard_retrieved_successfully'),
        status_code=status.HTTP_200_OK,
    )


@api_view(['PATCH'])
@permission_classes([IsDriver])
def driver_status_view(request):
    """
    Toggle driver online/offline status from the delivery app.
    PATCH /api/driver/status/
    Body: { "is_online": true|false } or { "status": "available|offline" }
    """
    driver = _get_driver_from_request(request)
    if not driver:
        return error_response(message=t(request, 'driver_not_found'), status_code=status.HTTP_404_NOT_FOUND)

    requested_status = request.data.get('status')
    requested_online = _coerce_bool(request.data.get('is_online'))

    if requested_status is None and requested_online is None:
        return error_response(
            message=t(request, 'invalid_data'),
            errors={'is_online': [t(request, 'driver_status_or_is_online_is_required')]},
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    if requested_status is not None:
        target_status = str(requested_status).strip().lower()
        if target_status not in {'available', 'busy', 'offline'}:
            return error_response(
                message=t(request, 'invalid_driver_status'),
                status_code=status.HTTP_400_BAD_REQUEST,
            )
    else:
        target_status = 'available' if requested_online else 'busy'

    active_orders_count = driver.orders.filter(status__in=['confirmed', 'preparing', 'on_way']).count()
    in_delivery_count = driver.orders.filter(status__in=['preparing', 'on_way']).count()

    if target_status == 'offline' and active_orders_count > 0:
        return error_response(
            message=t(request, 'driver_cannot_go_offline_with_active_orders'),
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    new_status = target_status
    if target_status == 'available' and in_delivery_count > 0:
        new_status = 'busy'
    elif target_status == 'busy' and active_orders_count == 0:
        new_status = 'offline'

    driver.status = new_status
    driver.save(update_fields=['status', 'updated_at'])

    try:
        notify_driver_status_updated(driver)
    except Exception as e:
        print(f"driver_status_updated WebSocket error: {e}")

    return success_response(
        data={
            'driver_id': driver.id,
            'status': driver.status,
            'status_display': driver.get_status_display(),
            'is_online': driver.status != 'offline',
            'can_receive_orders': driver.status == 'available',
        },
        message=t(request, 'driver_status_updated_successfully'),
        status_code=status.HTTP_200_OK,
    )


@api_view(['GET', 'PATCH'])
@permission_classes([IsDriver])
def driver_profile_view(request):
    """
    Load and update the authenticated driver's profile.
    GET/PATCH /api/user/profile/
    """
    driver = _get_driver_from_request(request)
    if not driver:
        return error_response(
            message=t(request, 'driver_not_found'),
            status_code=status.HTTP_404_NOT_FOUND,
            request=request,
        )

    if request.method == 'GET':
        completed_orders_count = driver.orders.filter(status='delivered').count()
        serializer = DriverProfileSerializer(
            driver,
            context={
                'request': request,
                'completed_orders_count': completed_orders_count,
                'overall_rating': driver.rating,
            },
        )
        return success_response(
            data=serializer.data,
            message=t(request, 'profile_loaded_successfully'),
            status_code=status.HTTP_200_OK,
            request=request,
        )

    payload = {}

    name_value = request.data.get('name', request.data.get('full_name'))
    if name_value is not None:
        payload['name'] = name_value

    phone_value = request.data.get('phone_number', request.data.get('phone'))
    if phone_value is not None:
        normalized_phone = normalize_phone(phone_value)
        payload['phone_number'] = normalized_phone
        if normalized_phone and len(normalized_phone) >= 12 and normalized_phone != driver.phone_number:
            return error_response(
                message=t(request, 'phone_number_change_requires_otp_verification'),
                errors={
                    'phone_number': [
                        t(request, 'phone_number_change_requires_otp_verification')
                    ]
                },
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                request=request,
            )

    vehicle_type = request.data.get('vehicle_type', request.data.get('vehicle'))
    if vehicle_type is not None:
        payload['vehicle_type'] = vehicle_type

    remove_profile_image = request.data.get('remove_profile_image', request.data.get('delete_profile_image'))
    if remove_profile_image is not None:
        payload['remove_profile_image'] = remove_profile_image

    profile_image = (
        request.FILES.get('profile_image')
        or request.FILES.get('avatar')
        or request.FILES.get('image')
    )
    if profile_image is not None:
        payload['profile_image'] = profile_image

    serializer = DriverProfileUpdateSerializer(
        driver,
        data=payload,
        partial=True,
        context={'request': request},
    )
    if not serializer.is_valid():
        return error_response(
            message=t(request, 'invalid_data'),
            errors=serializer.errors,
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            request=request,
        )

    serializer.save()
    response_serializer = DriverProfileResponseSerializer(driver, context={'request': request})
    return success_response(
        data=response_serializer.data,
        message=t(request, 'profile_updated_successfully'),
        status_code=status.HTTP_200_OK,
        request=request,
    )


@api_view(['POST'])
@permission_classes([IsDriver])
def driver_profile_phone_send_otp_view(request):
    """
    Request OTP before changing the driver's phone number.
    POST /api/user/profile/phone/send-otp/
    """
    driver = _get_driver_from_request(request)
    if not driver:
        return error_response(
            message=t(request, 'driver_not_found'),
            status_code=status.HTTP_404_NOT_FOUND,
            request=request,
        )

    new_phone_number = request.data.get('new_phone_number', request.data.get('phone_number'))
    if not new_phone_number:
        return error_response(
            message=t(request, 'phone_number_is_required'),
            errors={'phone_number': [t(request, 'phone_number_is_required')]},
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            request=request,
        )

    normalized_phone = normalize_phone(new_phone_number)
    if not normalized_phone or len(normalized_phone) < 12:
        return error_response(
            message=t(request, 'invalid_data'),
            errors={'phone_number': [t(request, 'invalid_phone_number')]},
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            request=request,
        )

    if normalized_phone == driver.phone_number:
        return error_response(
            message=t(request, 'new_phone_number_matches_current_phone_number'),
            errors={'phone_number': [t(request, 'new_phone_number_matches_current_phone_number')]},
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            request=request,
        )

    phone_variants = DriverProfileUpdateSerializer._phone_variants(new_phone_number)
    existing_driver = Driver.objects.filter(phone_number__in=phone_variants).exclude(pk=driver.pk)
    if existing_driver.exists():
        return error_response(
            message=t(request, 'phone_number_is_already_registered'),
            errors={'phone_number': [t(request, 'phone_number_is_already_registered')]},
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            request=request,
        )

    send_ok, send_msg = otp_send(normalized_phone)
    if not send_ok:
        return error_response(
            message=localize_message(request, send_msg),
            status_code=status.HTTP_400_BAD_REQUEST,
            request=request,
        )

    cache.set(
        _driver_phone_change_cache_key(driver.id),
        {'phone_number': normalized_phone},
        DRIVER_PHONE_CHANGE_OTP_TTL_SECONDS,
    )

    return success_response(
        data={'phone_number': normalized_phone},
        message=t(request, 'otp_sent_successfully'),
        status_code=status.HTTP_200_OK,
        request=request,
    )


@api_view(['POST'])
@permission_classes([IsDriver])
def driver_profile_phone_verify_otp_view(request):
    """
    Verify OTP and complete the driver's phone number change.
    POST /api/user/profile/phone/verify-otp/
    """
    driver = _get_driver_from_request(request)
    if not driver:
        return error_response(
            message=t(request, 'driver_not_found'),
            status_code=status.HTTP_404_NOT_FOUND,
            request=request,
        )

    new_phone_number = request.data.get('new_phone_number', request.data.get('phone_number'))
    otp_code = request.data.get('otp')

    errors = {}
    if not new_phone_number:
        errors['phone_number'] = [t(request, 'phone_number_is_required')]
    if not otp_code:
        errors['otp'] = [t(request, 'verification_code_is_required')]
    if errors:
        return error_response(
            message=t(request, 'invalid_data'),
            errors=errors,
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            request=request,
        )

    normalized_phone = normalize_phone(new_phone_number)
    if not normalized_phone or len(normalized_phone) < 12:
        return error_response(
            message=t(request, 'invalid_data'),
            errors={'phone_number': [t(request, 'invalid_phone_number')]},
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            request=request,
        )

    pending_change = cache.get(_driver_phone_change_cache_key(driver.id))
    if not pending_change:
        return error_response(
            message=t(request, 'phone_number_change_otp_request_not_found'),
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            request=request,
        )

    if normalized_phone != pending_change.get('phone_number'):
        return error_response(
            message=t(request, 'phone_number_change_otp_phone_mismatch'),
            errors={'phone_number': [t(request, 'phone_number_change_otp_phone_mismatch')]},
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            request=request,
        )

    phone_variants = DriverProfileUpdateSerializer._phone_variants(normalized_phone)
    existing_driver = Driver.objects.filter(phone_number__in=phone_variants).exclude(pk=driver.pk)
    if existing_driver.exists():
        return error_response(
            message=t(request, 'phone_number_is_already_registered'),
            errors={'phone_number': [t(request, 'phone_number_is_already_registered')]},
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            request=request,
        )

    if not otp_verify(normalized_phone, otp_code):
        return error_response(
            message=t(request, 'verification_code_is_invalid_or_expired'),
            status_code=status.HTTP_401_UNAUTHORIZED,
            request=request,
        )

    driver.phone_number = normalized_phone
    driver.save(update_fields=['phone_number', 'updated_at'])
    cache.delete(_driver_phone_change_cache_key(driver.id))

    return success_response(
        data={'phone_number': normalized_phone},
        message=t(request, 'phone_number_verified_successfully'),
        status_code=status.HTTP_200_OK,
        request=request,
    )


@api_view(['POST'])
@permission_classes([IsDriver])
def driver_change_password_view(request):
    """
    Change password for the authenticated driver.
    POST /api/driver/password/change/
    """
    driver = _get_driver_from_request(request)
    if not driver:
        return error_response(
            message=t(request, 'driver_not_found'),
            status_code=status.HTTP_404_NOT_FOUND,
            request=request,
        )

    current_password = (
        request.data.get('current_password')
        or request.data.get('old_password')
        or request.data.get('password')
    )
    new_password = request.data.get('new_password')
    confirm_password = (
        request.data.get('confirm_password')
        or request.data.get('confirm_new_password')
        or request.data.get('new_password_confirmation')
    )

    errors = {}
    if not current_password:
        errors['current_password'] = [t(request, 'current_password_is_required')]
    if not new_password:
        errors['new_password'] = [t(request, 'new_password_is_required')]
    elif len(str(new_password)) < 6:
        errors['new_password'] = [t(request, 'password_must_be_at_least_6_characters')]
    if not confirm_password:
        errors['confirm_password'] = [t(request, 'confirm_password_is_required')]
    elif new_password and str(confirm_password) != str(new_password):
        errors['confirm_password'] = [t(request, 'new_password_confirmation_does_not_match')]
    if current_password and not driver.check_password(current_password):
        errors['current_password'] = [t(request, 'current_password_is_incorrect')]

    if errors:
        return error_response(
            message=t(request, 'invalid_data'),
            errors=errors,
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            request=request,
        )

    driver.set_password(new_password)
    driver.save(update_fields=['password', 'updated_at'])
    return success_response(
        data={},
        message=t(request, 'password_changed_successfully'),
        status_code=status.HTTP_200_OK,
        request=request,
    )


@api_view(['POST'])
@permission_classes([IsDriver])
def driver_logout_view(request):
    """
    Log out the authenticated driver.
    POST /api/driver/logout/
    """
    driver = _get_driver_from_request(request)
    if not driver:
        return error_response(
            message=t(request, 'driver_not_found'),
            status_code=status.HTTP_404_NOT_FOUND,
            request=request,
        )

    refresh_token = request.data.get('refresh') or request.data.get('refresh_token')
    if refresh_token and django_apps.is_installed('rest_framework_simplejwt.token_blacklist'):
        try:
            RefreshToken(refresh_token).blacklist()
        except Exception:
            pass

    update_fields = ['last_seen_at', 'updated_at']
    driver.last_seen_at = timezone.now()

    active_orders_count = driver.orders.filter(status__in=['confirmed', 'preparing', 'on_way']).count()
    if active_orders_count == 0 and driver.status != 'offline':
        driver.status = 'offline'
        update_fields.append('status')

    driver.save(update_fields=update_fields)

    if 'status' in update_fields:
        try:
            notify_driver_status_updated(driver)
        except Exception as e:
            print(f"driver_status_updated WebSocket error: {e}")

    return success_response(
        data={},
        message=t(request, 'logged_out_successfully'),
        status_code=status.HTTP_200_OK,
        request=request,
    )


@api_view(['POST'])
@permission_classes([IsDriver])
def driver_order_accept_view(request, order_id):
    """
    Driver accepts an available delivery order.
    POST /api/driver/orders/{id}/accept/
    """
    driver = _get_driver_from_request(request)
    if not driver:
        return error_response(message=t(request, 'driver_not_found'), status_code=status.HTTP_404_NOT_FOUND)

    with transaction.atomic():
        order = get_available_order_for_driver(driver, order_id, lock=True)
        if not order:
            return error_response(
                message=t(request, 'driver_order_not_available'),
                status_code=status.HTTP_404_NOT_FOUND,
            )

        order.driver = driver
        order.save(update_fields=['driver', 'updated_at'])
        clear_driver_rejection(order, driver)

    driver.current_orders_count = driver.orders.filter(status__in=['new', 'confirmed', 'preparing', 'on_way']).count()
    driver.save(update_fields=['current_orders_count'])

    try:
        order_data = OrderSerializer(order, context={'request': request}).data
        notify_order_update(
            shop_owner_id=order.shop_owner_id,
            customer_id=order.customer_id,
            driver_id=order.driver_id,
            order_data=order_data,
        )
    except Exception as e:
        print(f"driver_order_accept websocket sync error: {e}")

    order_payload = build_driver_order_payload(order, request=request)
    active_driver_ids = list(order.shop_owner.shop_drivers.filter(status='active').values_list('driver_id', flat=True).distinct())
    for target_driver_id in active_driver_ids:
        emit_available_order_remove(
            target_driver_id,
            order.id,
            'accepted_by_you' if target_driver_id == driver.id else 'accepted_by_another_driver',
        )
    emit_assigned_order_upsert(driver.id, order_payload)
    emit_order_accepted(driver.id, order_payload)

    return success_response(
        data={'order': order_payload},
        message=t(request, 'driver_order_accepted_successfully'),
        status_code=status.HTTP_200_OK,
    )


@api_view(['POST'])
@permission_classes([IsDriver])
def driver_order_reject_view(request, order_id):
    """
    Driver rejects an available delivery order for himself only.
    POST /api/driver/orders/{id}/reject/
    """
    driver = _get_driver_from_request(request)
    if not driver:
        return error_response(message=t(request, 'driver_not_found'), status_code=status.HTTP_404_NOT_FOUND)

    with transaction.atomic():
        order = get_available_order_for_driver(driver, order_id, lock=True)
        if not order:
            return error_response(
                message=t(request, 'driver_order_not_available'),
                status_code=status.HTTP_404_NOT_FOUND,
            )

        reject_reason = str(request.data.get('reason') or '').strip()
        record_driver_rejection(order, driver, reject_reason)

    emit_available_order_remove(driver.id, order.id, 'rejected_by_you')
    emit_order_rejected(driver.id, order.id)

    return success_response(
        data={
            'order_id': order.id,
            'status': order.status,
            'driver_status': 'rejected',
        },
        message=t(request, 'driver_order_rejected_successfully'),
        status_code=status.HTTP_200_OK,
    )


@api_view(['GET'])
@permission_classes([IsDriver])
def driver_order_detail_view(request, order_id):
    """
    Driver order detail with the unified realtime payload.
    GET /api/driver/orders/{id}/
    """
    driver = _get_driver_from_request(request)
    if not driver:
        return error_response(message=t(request, 'driver_not_found'), status_code=status.HTTP_404_NOT_FOUND)

    order = _get_driver_order_or_none(driver, order_id, statuses=DRIVER_APP_ORDER_STATUSES)
    if not order:
        return error_response(
            message=t(request, 'driver_order_not_found'),
            status_code=status.HTTP_404_NOT_FOUND,
        )

    return success_response(
        data=build_driver_order_payload(order, request=request),
        message=t(request, 'driver_order_details_retrieved_successfully'),
        status_code=status.HTTP_200_OK,
    )


@api_view(['POST'])
@permission_classes([IsDriver])
def driver_order_transfer_view(request, order_id):
    """
    Driver transfers an assigned order back for reassignment.
    POST /api/driver/orders/{id}/transfer/
    Body: { "reason_key": "...", "note": "..." }
    """
    driver = _get_driver_from_request(request)
    if not driver:
        return error_response(message=t(request, 'driver_not_found'), status_code=status.HTTP_404_NOT_FOUND)

    order = _get_driver_order_or_none(driver, order_id, statuses=DRIVER_APP_ORDER_STATUSES)
    if not order:
        return error_response(
            message=t(request, 'driver_order_not_found'),
            status_code=status.HTTP_404_NOT_FOUND,
        )

    reason_key = str(request.data.get('reason_key') or request.data.get('reason') or '').strip()
    if not reason_key:
        return error_response(
            message=t(request, 'driver_transfer_reason_is_required'),
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    selected_reason = next((item for item in DRIVER_TRANSFER_REASONS if item['key'] == reason_key), None)
    if not selected_reason:
        return error_response(
            message=t(request, 'invalid_driver_transfer_reason'),
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    note = str(request.data.get('note') or '').strip()
    if selected_reason.get('requires_note') and not note:
        return error_response(
            message=t(request, 'driver_transfer_note_is_required'),
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    if order.status not in DRIVER_APP_ORDER_STATUSES:
        return error_response(
            message=t(request, 'driver_order_cannot_be_transferred_in_current_status'),
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    old_driver = order.driver
    old_status = order.status
    if order.status in {'preparing', 'on_way'}:
        order.status = 'confirmed'
    order.driver = None
    order.save(update_fields=['driver', 'status', 'updated_at'])
    clear_all_driver_rejections(order)

    transfer_reason = selected_reason['label']
    if note:
        transfer_reason = f'{transfer_reason}: {note}'

    if old_driver:
        try:
            request_transfer_for_order(
                order=order,
                driver=old_driver,
                reason=transfer_reason,
                request=request,
            )
        except Exception as e:
            print(f"driver_chat transfer request sync error: {e}")

    if old_driver:
        old_driver.current_orders_count = old_driver.orders.filter(status__in=['new', 'preparing', 'on_way']).count()
        old_driver.save(update_fields=['current_orders_count'])

    Notification.objects.create(
        shop_owner=order.shop_owner,
        notification_type='system',
        title='تحويل طلب',
        message=f'الطلب #{order.order_number} يحتاج إعادة تعيين لمندوب آخر.',
        data={
            'order_id': order.id,
            'order_number': order.order_number,
            'reason_key': selected_reason['key'],
            'reason_label': selected_reason['label'],
            'note': note or None,
            'driver_id': driver.id,
        },
    )

    try:
        order_data = OrderSerializer(order, context={'request': request}).data
        notify_order_update(
            shop_owner_id=order.shop_owner_id,
            customer_id=order.customer_id,
            driver_id=None,
            order_data=order_data,
        )
        if old_driver:
            notify_driver_status_updated(old_driver)
    except Exception as e:
        print(f"driver_order_transfer WebSocket error: {e}")

    if old_driver:
        emit_order_transferred(old_driver.id, order.id, reason_key=selected_reason['key'], note=note or None)
    sync_driver_order_state(
        order,
        previous_status=old_status,
        previous_driver_id=old_driver.id if old_driver else None,
        request=request,
    )

    return success_response(
        data={},
        message=t(request, 'driver_order_transferred_successfully'),
        status_code=status.HTTP_200_OK,
    )


@api_view(['POST'])
@permission_classes([IsDriver])
def driver_order_chat_open_view(request, order_id):
    """
    Prepare the driver-customer chat session without auto-starting it on accept.
    POST /api/driver/orders/{id}/chat/open/
    """
    driver = _get_driver_from_request(request)
    if not driver:
        return error_response(message=t(request, 'driver_not_found'), status_code=status.HTTP_404_NOT_FOUND)

    order = _get_driver_order_or_none(driver, order_id, statuses=DRIVER_APP_ORDER_STATUSES)
    if not order:
        return error_response(
            message=t(request, 'driver_order_not_found'),
            status_code=status.HTTP_404_NOT_FOUND,
        )

    conversation_id = f'order_{order.id}_driver_customer'
    has_messages = ChatMessage.objects.filter(order=order, chat_type='driver_customer').exists()
    ws_path = f'/ws/chat/order/{order.id}/?chat_type=driver_customer&lang={request.query_params.get("lang", "ar")}'

    return success_response(
        data={
            'conversation_id': conversation_id,
            'order_id': order.id,
            'chat_type': 'driver_customer',
            'is_existing': has_messages,
            'is_new': not has_messages,
            'ws_url': ws_path,
        },
        message=t(request, 'driver_chat_opened_successfully'),
        status_code=status.HTTP_200_OK,
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
            try:
                notify_shop_status_updated(
                    shop_owner.id,
                    {
                        'shop_owner_id': shop_owner.id,
                        **serializer.data,
                    }
                )
            except Exception as e:
                print(f"store_status_updated WebSocket error: {e}")
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


@api_view(['GET', 'POST'])
@permission_classes([IsShopOwnerOrEmployee])
def offer_list_view(request):
    """List or create independent offers for a shop."""
    _cleanup_expired_offers()

    shop_owner = _resolve_owner_for_owner_or_employee(request.user)
    if not shop_owner:
        return _owner_or_employee_forbidden(request)

    if request.method == 'GET':
        status_filter = str(request.query_params.get('status', 'all') or 'all').strip().lower()
        sort_by = str(request.query_params.get('sort_by', 'newest') or 'newest').strip().lower()
        search_query = str(request.query_params.get('search') or '').strip()

        if status_filter not in {'all', 'active', 'scheduled', 'expired'}:
            return error_response(
                message=t(request, 'invalid_offer_status_available_values_all_active_scheduled_expired'),
                status_code=status.HTTP_400_BAD_REQUEST
            )

        queryset = Offer.objects.filter(shop_owner=shop_owner).select_related('shop_owner')
        queryset = _apply_offer_status_filter(queryset, status_filter)
        queryset = queryset if queryset is not None else Offer.objects.none()

        if search_query:
            queryset = queryset.filter(
                Q(title__icontains=search_query) |
                Q(description__icontains=search_query)
            )

        queryset = _apply_offer_sorting(queryset, sort_by)
        if queryset is None:
            return error_response(
                message=t(request, 'invalid_offer_sort_available_values_newest_oldest_most_viewed'),
                status_code=status.HTTP_400_BAD_REQUEST
            )

        paginator = OfferPagination()
        page = paginator.paginate_queryset(queryset, request)
        if page is not None:
            serializer = OfferManagementSerializer(page, many=True, context={'request': request})
            response = paginator.get_paginated_response(serializer.data)
            response.data['data'].pop('next', None)
            response.data['data'].pop('previous', None)
            return response

        serializer = OfferManagementSerializer(queryset, many=True, context={'request': request})
        return success_response(
            data=serializer.data,
            message=t(request, 'offers_retrieved_successfully'),
            status_code=status.HTTP_200_OK
        )

    if not _is_shop_owner_user(request.user):
        return error_response(
            message=t(request, 'permission_only_shop_owner_edit_content'),
            status_code=status.HTTP_403_FORBIDDEN
        )

    serializer = OfferCreateUpdateSerializer(data=request.data, context={'request': request})
    if serializer.is_valid():
        offer = serializer.save(shop_owner=shop_owner)
        response_serializer = OfferManagementSerializer(offer, context={'request': request})
        return success_response(
            data=response_serializer.data,
            message=t(request, 'offer_added_successfully'),
            status_code=status.HTTP_201_CREATED
        )

    return error_response(
        message=t(request, 'invalid_data'),
        errors=serializer.errors,
        status_code=status.HTTP_400_BAD_REQUEST
    )


@api_view(['GET', 'PUT', 'DELETE'])
@permission_classes([IsShopOwnerOrEmployee])
def offer_detail_view(request, offer_id):
    """Retrieve, update, or delete a shop offer."""
    _cleanup_expired_offers()

    shop_owner = _resolve_owner_for_owner_or_employee(request.user)
    if not shop_owner:
        return _owner_or_employee_forbidden(request)

    try:
        offer = Offer.objects.select_related('shop_owner').get(id=offer_id, shop_owner=shop_owner)
    except Offer.DoesNotExist:
        return error_response(
            message=t(request, 'offer_not_found'),
            status_code=status.HTTP_404_NOT_FOUND
        )

    if request.method == 'GET':
        serializer = OfferManagementSerializer(offer, context={'request': request})
        return success_response(
            data=serializer.data,
            message=t(request, 'offer_data_retrieved_successfully'),
            status_code=status.HTTP_200_OK
        )

    if not _is_shop_owner_user(request.user):
        return error_response(
            message=t(request, 'permission_only_shop_owner_edit_content'),
            status_code=status.HTTP_403_FORBIDDEN
        )

    if request.method == 'PUT':
        serializer = OfferCreateUpdateSerializer(
            offer,
            data=request.data,
            partial=True,
            context={'request': request}
        )
        if serializer.is_valid():
            serializer.save()
            response_serializer = OfferManagementSerializer(offer, context={'request': request})
            return success_response(
                data=response_serializer.data,
                message=t(request, 'offer_updated_successfully'),
                status_code=status.HTTP_200_OK
            )
        return error_response(
            message=t(request, 'invalid_data'),
            errors=serializer.errors,
            status_code=status.HTTP_400_BAD_REQUEST
        )

    offer.delete()
    return success_response(
        message=t(request, 'offer_deleted_successfully'),
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
    if not shop_owner:
        return _owner_or_employee_forbidden(request)
    
    if request.method == 'GET':
        status_filter = request.query_params.get('status')
        search_query = request.query_params.get('search')
        
        queryset = Order.objects.filter(shop_owner=shop_owner).select_related('customer')
        
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
            serializer = ShopOrderListSerializer(page, many=True, context={'request': request})
            return paginator.get_paginated_response(serializer.data)
        
        serializer = ShopOrderListSerializer(queryset, many=True, context={'request': request})
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
    return _resolve_owner_for_owner_or_employee(request.user)


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
    if not shop_owner:
        return _owner_or_employee_forbidden(request)
    
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

        cancellation_locked_statuses = {'preparing', 'on_way', 'delivered'}
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

        if new_status == 'cancelled' and old_status in cancellation_locked_statuses:
            return error_response(
                message='لا يمكن إلغاء الفاتورة بعد بدء التجهيز أو خروج الطلب للتوصيل أو بعد اكتماله.',
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
                    relation = ShopDriver.objects.select_related('driver').get(
                        shop_owner=shop_owner,
                        driver_id=driver_id,
                        status='active',
                    )
                    order.driver = relation.driver
                except ShopDriver.DoesNotExist:
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
                elif old_status == 'confirmed':
                    msg_content = 'تم إلغاء الطلب من المتجر بعد تأكيد الفاتورة.'
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
                broadcast_chat_message_to_order(order.id, _chat_message_payload(sys_msg, request=request), request=request)
            elif new_status == 'pending_customer_confirm':
                if old_status == 'pending_customer_confirm':
                    msg_content = 'invoice_modified_waiting_for_confirmation'
                else:
                    msg_content = 'order_priced_please_confirm'
                sys_msg = ChatMessage.objects.create(
                    order=order,
                    chat_type='shop_customer',
                    sender_type=sender_type,
                    sender_shop_owner=shop_owner if sender_type == 'shop_owner' else None,
                    sender_employee=request.user if sender_type == 'employee' else None,
                    message_type='text',
                    content=msg_content,
                )
                broadcast_chat_message_to_order(order.id, _chat_message_payload(sys_msg, request=request), request=request)

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
                broadcast_chat_message_to_order(order.id, _chat_message_payload(driver_msg, request=request), request=request)
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

        try:
            sync_order_assignment_change(order, old_driver=old_driver, new_driver=order.driver, request=request)
        except Exception as e:
            print(f"driver_chat sync error: {e}")
        
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

            notified_driver_ids = set()
            if old_driver:
                notify_driver_status_updated(old_driver.id)
                notified_driver_ids.add(old_driver.id)
            if order.driver and order.driver.id not in notified_driver_ids:
                notify_driver_status_updated(order.driver.id)
        except Exception as e:
            print(f"WebSocket notification error: {e}")

        sync_driver_order_state(
            order,
            previous_status=old_status,
            previous_driver_id=old_driver.id if old_driver else None,
            request=request,
        )
        
        return success_response(
            data=response_serializer.data,
            message=t(request, 'order_updated_successfully'),
            status_code=status.HTTP_200_OK
        )
    
    elif request.method == 'DELETE':
        deleted_order_id = order.id
        deleted_customer_id = order.customer_id
        deleted_shop_owner_id = order.shop_owner_id
        order.delete()
        try:
            broadcast_customer_order_removed(
                deleted_customer_id,
                deleted_order_id,
                shop_owner_id=deleted_shop_owner_id,
                include_shop=True,
                include_on_way=True,
                include_history=True,
                base_url=request.build_absolute_uri('/').rstrip('/'),
            )
        except Exception as e:
            print(f"customer realtime remove broadcast error: {e}")
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
    active_shop_drivers = _active_shop_drivers_queryset(shop_owner)
    total_drivers = active_shop_drivers.count()
    available_drivers = active_shop_drivers.filter(status='available').count()

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
    serializer = DriverTokenObtainPairSerializer(data=request.data, context={'request': request})
    
    try:
        serializer.is_valid(raise_exception=True)
    except Exception as e:
        errors = serializer.errors if hasattr(serializer, 'errors') else {'detail': str(e)}
        detail_message = None
        if isinstance(errors, dict):
            detail_value = errors.get('detail')
            if isinstance(detail_value, list) and detail_value:
                detail_message = detail_value[0]
            elif isinstance(detail_value, str):
                detail_message = detail_value
        return error_response(
            message=detail_message or t(request, 'login_failed'),
            errors=errors,
            status_code=status.HTTP_401_UNAUTHORIZED if detail_message else status.HTTP_400_BAD_REQUEST
        )
    
    return success_response(
        data=serializer.validated_data,
        message=t(request, 'login_successful'),
        status_code=status.HTTP_200_OK
    )


@api_view(['POST'])
@permission_classes([AllowAny])
def driver_register_view(request):
    """
    Create a delivery-app driver account.
    POST /api/driver/register/
    """
    payload = request.data.copy()

    profile_image = (
        request.FILES.get('profile_image')
        or request.FILES.get('avatar')
        or request.FILES.get('image')
    )
    if profile_image is not None:
        payload['profile_image'] = profile_image

    serializer = DriverRegisterSerializer(data=payload, context={'request': request})
    if not serializer.is_valid():
        return error_response(
            message=t(request, 'invalid_data'),
            errors=serializer.errors,
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    driver = serializer.save()
    response_serializer = DriverAppSerializer(driver, context={'request': request})
    return success_response(
        data={'driver': response_serializer.data},
        message=t(request, 'account_created_successfully_complete_otp_verification'),
        status_code=status.HTTP_201_CREATED,
    )


@api_view(['POST'])
@permission_classes([AllowAny])
def driver_register_send_otp_view(request):
    """
    Send OTP to activate a newly created driver account.
    POST /api/driver/register/send-otp/
    """
    phone_number = request.data.get('phone_number')
    if not phone_number:
        return error_response(
            message=t(request, 'phone_number_is_required'),
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    driver = _find_driver_by_phone(phone_number)
    if not driver:
        return error_response(
            message=t(request, 'phone_number_is_not_registered_please_register_first'),
            status_code=status.HTTP_404_NOT_FOUND,
        )
    if driver.is_verified:
        return error_response(
            message=t(request, 'account_is_already_verified_use_login'),
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    normalized_phone = normalize_phone(phone_number)
    send_ok, send_msg = otp_send(normalized_phone)
    if not send_ok:
        return error_response(
            message=localize_message(request, send_msg),
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    return success_response(
        message=t(request, 'verification_code_sent_to_your_whatsapp'),
        status_code=status.HTTP_200_OK,
    )


@api_view(['POST'])
@permission_classes([AllowAny])
def driver_register_verify_otp_view(request):
    """
    Verify OTP and activate the driver account.
    POST /api/driver/register/verify-otp/
    """
    phone_number = request.data.get('phone_number')
    otp_code = request.data.get('otp')

    if not phone_number:
        return error_response(
            message=t(request, 'phone_number_is_required'),
            status_code=status.HTTP_400_BAD_REQUEST,
        )
    if not otp_code:
        return error_response(
            message=t(request, 'verification_code_is_required'),
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    driver = _find_driver_by_phone(phone_number)
    if not driver:
        return error_response(
            message=t(request, 'phone_number_is_not_registered_please_register_first'),
            status_code=status.HTTP_404_NOT_FOUND,
        )
    if driver.is_verified:
        return error_response(
            message=t(request, 'account_is_already_verified_use_login'),
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    normalized_phone = normalize_phone(phone_number)
    if not otp_verify(normalized_phone, otp_code):
        return error_response(
            message=t(request, 'verification_code_is_invalid_or_expired'),
            status_code=status.HTTP_401_UNAUTHORIZED,
        )

    driver.is_verified = True
    driver.save(update_fields=['is_verified', 'updated_at'])

    refresh = DriverTokenObtainPairSerializer.get_token(driver)
    response_serializer = DriverAppSerializer(driver, context={'request': request})
    return success_response(
        data={
            'refresh': str(refresh),
            'access': str(refresh.access_token),
            'driver': response_serializer.data,
        },
        message=t(request, 'verification_successful'),
        status_code=status.HTTP_200_OK,
    )


@api_view(['POST'])
@permission_classes([AllowAny])
def driver_password_send_otp_view(request):
    """
    Send OTP before resetting the driver's password.
    POST /api/driver/password/send-otp/
    """
    phone_number = request.data.get('phone_number')
    if not phone_number:
        return error_response(
            message=t(request, 'phone_number_is_required'),
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    driver = _find_driver_by_phone(phone_number)
    if not driver:
        return error_response(
            message=t(request, 'phone_number_is_not_registered_please_register_first'),
            status_code=status.HTTP_404_NOT_FOUND,
        )
    if not driver.is_verified:
        return error_response(
            message=t(request, 'account_is_not_verified_complete_otp_verification'),
            status_code=status.HTTP_401_UNAUTHORIZED,
        )

    normalized_phone = normalize_phone(phone_number)
    send_ok, send_msg = otp_send(normalized_phone)
    if not send_ok:
        return error_response(
            message=localize_message(request, send_msg),
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    return success_response(
        message=t(request, 'verification_code_sent_to_your_whatsapp'),
        status_code=status.HTTP_200_OK,
    )


@api_view(['POST'])
@permission_classes([AllowAny])
def driver_password_reset_view(request):
    """
    Reset the driver's password using OTP.
    POST /api/driver/password/reset/
    """
    phone_number = request.data.get('phone_number')
    otp_code = request.data.get('otp')
    new_password = request.data.get('new_password')
    confirm_password = (
        request.data.get('confirm_password')
        or request.data.get('confirm_new_password')
        or request.data.get('new_password_confirmation')
    )

    errors = {}
    if not phone_number:
        errors['phone_number'] = [t(request, 'phone_number_is_required')]
    if not otp_code:
        errors['otp'] = [t(request, 'verification_code_is_required')]
    if not new_password:
        errors['new_password'] = [t(request, 'new_password_is_required')]
    elif len(new_password) < 6:
        errors['new_password'] = [t(request, 'password_must_be_at_least_6_characters')]
    if not confirm_password:
        errors['confirm_password'] = [t(request, 'confirm_password_is_required')]
    elif new_password and confirm_password != new_password:
        errors['confirm_password'] = [t(request, 'new_password_confirmation_does_not_match')]
    if errors:
        return error_response(
            message=t(request, 'invalid_data'),
            errors=errors,
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    driver = _find_driver_by_phone(phone_number)
    if not driver:
        return error_response(
            message=t(request, 'phone_number_is_not_registered_please_register_first'),
            status_code=status.HTTP_404_NOT_FOUND,
        )
    if not driver.is_verified:
        return error_response(
            message=t(request, 'account_is_not_verified_complete_otp_verification'),
            status_code=status.HTTP_401_UNAUTHORIZED,
        )

    normalized_phone = normalize_phone(phone_number)
    if not otp_verify(normalized_phone, otp_code):
        return error_response(
            message=t(request, 'verification_code_is_invalid_or_expired'),
            status_code=status.HTTP_401_UNAUTHORIZED,
        )

    driver.set_password(new_password)
    driver.save()
    return success_response(
        message=t(request, 'password_changed_successfully'),
        status_code=status.HTTP_200_OK,
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
                    'is_online': bool(customer.is_online),
                    'last_seen': format_utc_iso8601(customer.last_seen),
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


CUSTOMER_PHONE_CHANGE_OTP_TTL_SECONDS = 600


def _customer_phone_change_cache_key(customer_id):
    return f"customer_phone_change:{customer_id}"


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
    context = {'request': request} if request is not None else {}
    serialized = ChatMessageSerializer(message, context=context).data
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
        'invoice': serialized.get('invoice'),
    }


def _get_prefetched_latest_message(order):
    prefetched_messages = getattr(order, 'prefetched_messages', None)
    if prefetched_messages is not None:
        return prefetched_messages[0] if prefetched_messages else None
    return order.messages.order_by('-created_at').first()


def _build_customer_shop_summary_payload(shop, request):
    status_obj = _safe_shop_status(shop)
    status_value = status_obj.status if status_obj else 'closed'
    status_display = status_obj.get_status_display() if status_obj else 'مغلق'
    category = shop.shop_category

    return {
        'id': shop.id,
        'shop_name': shop.shop_name,
        'shop_number': shop.shop_number,
        'owner_name': shop.owner_name,
        'phone_number': shop.phone_number,
        'profile_image_url': _build_file_url(request, shop.profile_image),
        'shop_category': (
            {'id': category.id, 'name': category.name}
            if category else None
        ),
        'status': {
            'key': status_value,
            'label': status_display,
        },
    }


def _build_customer_message_summary_payload(message, request):
    if not message:
        return None

    serialized = ChatMessageSerializer(message, context={'request': request}).data
    return {
        'id': serialized.get('id'),
        'chat_type': serialized.get('chat_type'),
        'sender_type': serialized.get('sender_type'),
        'sender_name': serialized.get('sender_name'),
        'message_type': serialized.get('message_type'),
        'content': serialized.get('content'),
        'audio_file_url': serialized.get('audio_file_url'),
        'image_file_url': serialized.get('image_file_url'),
        'latitude': serialized.get('latitude'),
        'longitude': serialized.get('longitude'),
        'is_read': serialized.get('is_read'),
        'created_at': serialized.get('created_at'),
    }


def _build_support_message_payload(message, request=None, base_url=None):
    serializer = CustomerSupportMessageSerializer(
        message,
        context={'request': request, 'base_url': base_url} if request is not None or base_url else {}
    )
    serialized = serializer.data
    return {
        'id': serialized.get('id'),
        'thread_id': serialized.get('thread_id'),
        'support_conversation_id': serialized.get('support_conversation_id'),
        'chat_type': serialized.get('chat_type'),
        'conversation_type': serialized.get('conversation_type'),
        'conversation_type_display': serialized.get('conversation_type_display'),
        'sender_type': serialized.get('sender_type'),
        'sender_name': serialized.get('sender_name'),
        'sender_id': serialized.get('sender_id'),
        'customer_profile_image_url': serialized.get('customer_profile_image_url'),
        'message_type': serialized.get('message_type'),
        'content': serialized.get('content'),
        'is_read': serialized.get('is_read'),
        'created_at': serialized.get('created_at'),
        'audio_file_url': serialized.get('audio_file_url'),
        'image_file_url': serialized.get('image_file_url'),
        'latitude': serialized.get('latitude'),
        'longitude': serialized.get('longitude'),
    }


def _build_customer_order_brief_payload(order):
    return {
        'id': order.id,
        'order_number': order.order_number,
        'status': order.status,
        'status_display': order.get_status_display(),
        'created_at': order.created_at.isoformat() if order.created_at else None,
        'updated_at': order.updated_at.isoformat() if order.updated_at else None,
    }


def _get_customer_friendly_delivery_status(order):
    mapping = {
        'confirmed': 'تم الاستلام',
        'preparing': 'تم الاستلام',
        'on_way': 'في الطريق',
    }
    return mapping.get(order.status, order.get_status_display())


def _build_customer_driver_payload(order, request):
    driver = order.driver
    if not driver:
        return None

    return {
        'id': driver.id,
        'name': driver.name,
        'phone_number': driver.phone_number,
        'profile_image_url': _build_file_url(request, driver.profile_image),
        'status': driver.status,
        'status_display': driver.get_status_display(),
        'current_latitude': str(driver.current_latitude) if driver.current_latitude is not None else None,
        'current_longitude': str(driver.current_longitude) if driver.current_longitude is not None else None,
        'location_updated_at': driver.location_updated_at.isoformat() if driver.location_updated_at else None,
    }


def _build_customer_shop_conversation_item(order, request, base_url=None):
    last_message = _get_prefetched_latest_message(order)
    return {
        'shop_id': order.shop_owner_id,
        'shop_name': order.shop_owner.shop_name,
        'shop_logo_url': _build_file_url(request, order.shop_owner.profile_image, base_url=base_url),
        'subtitle': 'تم التواصل مؤخراً' if last_message else 'لا يوجد تواصل بعد',
        'chat': {
            'thread_id': str(order.id),
            'order_id': order.id,
            'chat_type': 'shop_customer',
            'shop_id': order.shop_owner_id,
        },
    }


def _build_customer_support_shop_conversation_item(conversation, request, base_url=None):
    payload = CustomerSupportConversationSerializer(
        conversation,
        context={'request': request, 'base_url': base_url} if request is not None or base_url else {}
    ).data
    return {
        'shop_id': payload.get('shop_id'),
        'shop_name': payload.get('shop_name'),
        'shop_logo_url': payload.get('shop_logo_url'),
        'subtitle': payload.get('subtitle'),
        'chat': payload.get('chat'),
        'support_conversation': payload,
    }


def _build_support_message_notification_payload(conversation, message, request=None, base_url=None):
    conversation_payload = CustomerSupportConversationSerializer(
        conversation,
        context={'request': request, 'base_url': base_url} if request is not None or base_url else {}
    ).data
    return {
        'support_conversation_id': conversation.public_id,
        'thread_id': conversation.public_id,
        'chat_type': 'support_customer',
        'conversation_type': conversation.conversation_type,
        'message': _build_support_message_payload(message, request=request, base_url=base_url),
        'conversation': conversation_payload,
        'shop_id': conversation.shop_owner_id,
        'shop_name': conversation.shop_owner.shop_name,
        'customer_id': conversation.customer_id,
        'customer_name': conversation.customer.name,
        'customer_profile_image_url': conversation_payload.get('customer_profile_image_url'),
        'customer': conversation_payload.get('customer'),
    }


def _build_customer_on_way_order_item(order, request, base_url=None):
    driver = order.driver
    can_chat_with_driver = bool(order.driver_id and order.status in {'preparing', 'on_way'})

    return {
        'order_id': order.id,
        'status_key': order.status,
        'status_label': _get_customer_friendly_delivery_status(order),
        'shop_id': order.shop_owner_id,
        'shop_name': order.shop_owner.shop_name,
        'shop_logo_url': _build_file_url(request, order.shop_owner.profile_image, base_url=base_url),
        'driver_id': driver.id if driver else None,
        'driver_name': driver.name if driver else None,
        'driver_image_url': _build_file_url(request, driver.profile_image, base_url=base_url) if driver else None,
        'driver_role_label': 'مندوب التوصيل' if driver else None,
        'chat': (
            {
                'thread_id': str(order.id),
                'order_id': order.id,
                'chat_type': 'driver_customer',
                'driver_id': driver.id,
            }
            if can_chat_with_driver and driver else None
        ),
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


def _support_sender_kwargs_for_user(user, user_type):
    sender_kwargs = {'sender_type': user_type}
    if user_type == 'customer':
        sender_kwargs['sender_customer'] = user
    elif user_type == 'shop_owner':
        sender_kwargs['sender_shop_owner'] = user
    elif user_type == 'employee':
        sender_kwargs['sender_employee'] = user
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


def _can_user_access_support_conversation(conversation, user, user_type):
    if user_type == 'shop_owner':
        return conversation.shop_owner_id == getattr(user, 'id', None)
    if user_type == 'employee':
        return conversation.shop_owner_id == getattr(user, 'shop_owner_id', None)
    if user_type == 'customer':
        return conversation.customer_id == getattr(user, 'id', None)
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
    broadcast_chat_message(order.id, chat_type, payload, request=request)
    serialized = ChatMessageSerializer(message, context={'request': request}).data
    return success_response(
        data=serialized,
        message='تم إرسال الوسائط بنجاح',
        status_code=status.HTTP_201_CREATED
    )


@api_view(['GET', 'POST'])
@permission_classes([IsCustomer])
def customer_support_conversations_view(request):
    """
    Create or list standalone customer support chats.
    GET /api/customer/support-chats/
    POST /api/customer/support-chats/
    """
    customer = _get_customer_from_request(request)
    if not customer:
        return error_response(message=t(request, 'customer_not_found'), status_code=status.HTTP_404_NOT_FOUND)

    if request.method == 'GET':
        conversations = (
            CustomerSupportConversation.objects
            .filter(customer=customer)
            .select_related('shop_owner', 'customer')
            .order_by('-updated_at', '-created_at')
        )
        serializer = CustomerSupportConversationSerializer(conversations, many=True, context={'request': request})
        return success_response(
            data={
                'count': len(serializer.data),
                'results': serializer.data,
            },
            message='support_conversations_retrieved_successfully',
            status_code=status.HTTP_200_OK,
            request=request,
        )

    serializer = CustomerSupportConversationCreateSerializer(
        data=request.data,
        context={'customer': customer, 'request': request},
    )
    if not serializer.is_valid():
        return error_response(
            message=t(request, 'invalid_data'),
            errors=serializer.errors,
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    conversation = serializer.save()
    initial_message = str(serializer.validated_data.get('initial_message') or '').strip()
    if initial_message:
        message = CustomerSupportMessage.objects.create(
            conversation=conversation,
            sender_type='customer',
            sender_customer=customer,
            message_type='text',
            content=initial_message,
        )
        conversation.last_message_preview = initial_message
        conversation.last_message_at = message.created_at
        conversation.unread_for_shop_count = conversation.messages.filter(
            is_read=False,
            sender_type='customer',
        ).count()
        conversation.unread_for_customer_count = conversation.messages.filter(
            is_read=False,
        ).exclude(sender_type='customer').count()
        conversation.save(update_fields=[
            'last_message_preview',
            'last_message_at',
            'unread_for_shop_count',
            'unread_for_customer_count',
            'updated_at',
        ])
        support_payload = _build_support_message_notification_payload(conversation, message, request=request)
        notify_support_message(conversation.shop_owner_id, conversation.customer_id, support_payload)

    response_serializer = CustomerSupportConversationSerializer(conversation, context={'request': request})
    notify_support_conversation_update(
        conversation.shop_owner_id,
        conversation.customer_id,
        response_serializer.data,
    )
    return success_response(
        data=response_serializer.data,
        message='تم فتح المحادثة بنجاح',
        status_code=status.HTTP_201_CREATED,
        request=request,
    )


@api_view(['GET'])
@permission_classes([IsShopOwnerOrEmployee])
def shop_support_conversations_view(request):
    """
    List standalone customer support chats for a shop.
    GET /api/shop/support-chats/
    """
    shop_owner = _get_shop_owner_from_request(request)
    if not shop_owner:
        return error_response(message=t(request, 'shop_not_found'), status_code=status.HTTP_404_NOT_FOUND)

    conversations = (
        CustomerSupportConversation.objects
        .filter(shop_owner=shop_owner)
        .select_related('shop_owner', 'customer')
        .order_by('-updated_at', '-created_at')
    )
    serializer = CustomerSupportConversationSerializer(conversations, many=True, context={'request': request})
    return success_response(
        data={
            'count': len(serializer.data),
            'results': serializer.data,
        },
        message='support_conversations_retrieved_successfully',
        status_code=status.HTTP_200_OK,
        request=request,
    )


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def support_chat_media_upload_view(request, conversation_id):
    """
    Upload support chat media then broadcast instantly to WebSocket subscribers.
    POST /api/chat/support/{conversation_id}/send-media/
    """
    try:
        conversation = (
            CustomerSupportConversation.objects
            .select_related('shop_owner', 'customer')
            .get(public_id=conversation_id)
        )
    except CustomerSupportConversation.DoesNotExist:
        return error_response(
            message='محادثة الدعم غير موجودة.',
            status_code=status.HTTP_404_NOT_FOUND,
        )

    user = request.user
    user_type = _resolve_user_type(user)
    if not user_type or not _can_user_access_support_conversation(conversation, user, user_type):
        return error_response(
            message='ليس لديك صلاحية للوصول إلى هذه المحادثة.',
            status_code=status.HTTP_403_FORBIDDEN,
        )

    image_file = request.FILES.get('image_file')
    audio_file = request.FILES.get('audio_file')
    if bool(image_file) == bool(audio_file):
        return error_response(
            message=t(request, 'invalid_data'),
            errors={'file': 'Send exactly one file: image_file or audio_file.'},
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    requested_type = str(request.data.get('message_type') or '').strip().lower()
    if image_file:
        if requested_type and requested_type != 'image':
            return error_response(
                message=t(request, 'invalid_data'),
                errors={'message_type': 'message_type must be image when image_file is provided.'},
                status_code=status.HTTP_400_BAD_REQUEST,
            )
        message_type = 'image'
        default_preview = 'صورة'
    else:
        if requested_type and requested_type != 'audio':
            return error_response(
                message=t(request, 'invalid_data'),
                errors={'message_type': 'message_type must be audio when audio_file is provided.'},
                status_code=status.HTTP_400_BAD_REQUEST,
            )
        message_type = 'audio'
        default_preview = 'رسالة صوتية'

    sender_kwargs = _support_sender_kwargs_for_user(user, user_type)
    if not sender_kwargs:
        return error_response(
            message='ليس لديك صلاحية للإرسال في هذه المحادثة.',
            status_code=status.HTTP_403_FORBIDDEN,
        )

    content = str(request.data.get('content') or '').strip() or None
    message = CustomerSupportMessage.objects.create(
        conversation=conversation,
        message_type=message_type,
        content=content,
        audio_file=audio_file,
        image_file=image_file,
        **sender_kwargs,
    )
    conversation.last_message_preview = content or default_preview
    conversation.last_message_at = message.created_at
    conversation.unread_for_shop_count = conversation.messages.filter(
        is_read=False,
        sender_type='customer',
    ).count()
    conversation.unread_for_customer_count = conversation.messages.filter(
        is_read=False,
    ).exclude(sender_type='customer').count()
    conversation.save(update_fields=[
        'last_message_preview',
        'last_message_at',
        'unread_for_shop_count',
        'unread_for_customer_count',
        'updated_at',
    ])

    payload = _build_support_message_payload(message, request=request)
    from .websocket_utils import broadcast_support_chat_message
    broadcast_support_chat_message(conversation.public_id, payload)
    notify_support_message(
        conversation.shop_owner_id,
        conversation.customer_id,
        _build_support_message_notification_payload(conversation, message, request=request),
    )

    serialized = CustomerSupportMessageSerializer(message, context={'request': request}).data
    return success_response(
        data=serialized,
        message='تم إرسال الوسائط بنجاح',
        status_code=status.HTTP_201_CREATED,
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


def _build_file_url(request, file_field, base_url=None):
    return build_absolute_file_url(file_field, request=request, base_url=base_url)


def _to_hhmm_time(value):
    if not value or not isinstance(value, str):
        return None
    try:
        return datetime.strptime(value, '%H:%M').time()
    except ValueError:
        return None


def _is_within_today_schedule(today_schedule):
    if not today_schedule.get('is_working'):
        return False
    start_time = _to_hhmm_time(today_schedule.get('start_time'))
    end_time = _to_hhmm_time(today_schedule.get('end_time'))
    if not start_time or not end_time:
        return False

    now_time = _shop_schedule_localtime().time().replace(second=0, microsecond=0)
    return start_time <= now_time <= end_time


def _is_open_now(status_value, today_schedule):
    _ = today_schedule
    return status_value in {'open', 'busy'}


def _build_today_hours_label(today_schedule):
    if not today_schedule.get('is_working'):
        return 'مغلق'
    start_time = today_schedule.get('start_time')
    end_time = today_schedule.get('end_time')
    if not start_time or not end_time:
        return 'غير محدد'
    return f'{start_time} - {end_time}'


def _build_live_shop_status_label(status_value, is_open_now):
    if not is_open_now:
        return 'مغلق الآن'
    if status_value == 'busy':
        return 'مشغول الآن'
    if status_value == 'open':
        return 'مفتوح الآن'
    return 'مفتوح الآن'


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


def _build_public_offer_serializer_context(request, offers):
    shop_ids = sorted({offer.shop_owner_id for offer in offers if offer.shop_owner_id})
    offer_ids = sorted({offer.id for offer in offers if offer.id})
    if not shop_ids:
        return {'request': request, 'shop_rating_map': {}, 'liked_offer_ids': set()}

    order_stats = {
        row['order__shop_owner_id']: row
        for row in (
            OrderRating.objects
            .filter(order__shop_owner_id__in=shop_ids)
            .values('order__shop_owner_id')
            .annotate(avg=Avg('shop_rating'), count=Count('id'))
        )
    }
    review_stats = {
        row['shop_owner_id']: row
        for row in (
            ShopReview.objects
            .filter(shop_owner_id__in=shop_ids)
            .values('shop_owner_id')
            .annotate(avg=Avg('shop_rating'), count=Count('id'))
        )
    }

    shop_rating_map = {}
    for offer in offers:
        shop_id = offer.shop_owner_id
        if shop_id not in shop_rating_map:
            order_row = order_stats.get(shop_id, {})
            review_row = review_stats.get(shop_id, {})

            order_count = int(order_row.get('count') or 0)
            review_count = int(review_row.get('count') or 0)
            total_count = order_count + review_count

            if total_count:
                order_avg = float(order_row.get('avg') or 0)
                review_avg = float(review_row.get('avg') or 0)
                weighted_avg = ((order_avg * order_count) + (review_avg * review_count)) / total_count
                average = round(weighted_avg, 1)
            else:
                average = 0.0

            shop_rating_map[shop_id] = {
                'average': average,
                'count': total_count,
            }

    actor_identifier = _resolve_like_actor_identifier(request)
    liked_offer_ids = set()
    if actor_identifier and offer_ids:
        liked_offer_ids = set(
            OfferLike.objects.filter(
                user_identifier=actor_identifier,
                offer_id__in=offer_ids,
            ).values_list('offer_id', flat=True)
        )

    return {
        'request': request,
        'shop_rating_map': shop_rating_map,
        'liked_offer_ids': liked_offer_ids,
    }


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
    within_schedule_now = _is_within_today_schedule(today_schedule)
    live_status_label = _build_live_shop_status_label(status_value, is_open_now)

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
            'label': live_status_label,
            'is_open_now': is_open_now,
            'within_schedule_now': within_schedule_now,
       
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
    within_schedule_now = _is_within_today_schedule(today_schedule)
    live_status_label = _build_live_shop_status_label(status_value, is_open_now)
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
                'label': live_status_label,
                'is_open_now': is_open_now,
                'within_schedule_now': within_schedule_now,
                 
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
@permission_classes([AllowAny])
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
    schedule_payload['within_schedule_now'] = _is_within_today_schedule(schedule_payload.get('today', {}))

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


@api_view(['POST', 'DELETE'])
@permission_classes([IsCustomer])
def public_offer_like_view(request, offer_id):
    """
    Like/unlike a public offer.
    POST/DELETE /api/shops/offers/{offer_id}/like/
    """
    today = timezone.localdate()
    offer = Offer.objects.filter(
        id=offer_id,
        shop_owner__is_active=True,
        is_active=True,
        start_date__lte=today,
        end_date__gte=today,
    ).first()
    if not offer:
        return error_response(
            message=t(request, 'offer_not_found'),
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
        try:
            _, created = OfferLike.objects.get_or_create(
                offer=offer,
                user_identifier=actor_identifier,
            )
        except IntegrityError:
            created = False

        if not created:
            return error_response(
                message=t(request, 'this_offer_has_already_been_liked'),
                status_code=status.HTTP_400_BAD_REQUEST,
                request=request
            )

        Offer.objects.filter(id=offer.id).update(likes_count=F('likes_count') + 1)
        offer.refresh_from_db(fields=['likes_count'])
        return success_response(
            data={'offer_id': offer.id, 'liked': True, 'likes_count': offer.likes_count},
            message=t(request, 'offer_liked_successfully'),
            status_code=status.HTTP_201_CREATED,
            request=request
        )

    deleted_count, _ = OfferLike.objects.filter(
        offer=offer,
        user_identifier=actor_identifier,
    ).delete()
    if deleted_count == 0:
        return error_response(
            message=t(request, 'this_offer_was_not_liked'),
            status_code=status.HTTP_404_NOT_FOUND,
            request=request
        )

    Offer.objects.filter(id=offer.id, likes_count__gt=0).update(likes_count=F('likes_count') - 1)
    offer.refresh_from_db(fields=['likes_count'])
    return success_response(
        data={'offer_id': offer.id, 'liked': False, 'likes_count': offer.likes_count},
        message=t(request, 'offer_like_removed_successfully'),
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
    List active independent offers for customers.
    GET /api/shops/offers/?shop_id=1&shop_category_id=1&page=1&page_size=20
    """
    _cleanup_expired_offers()

    today = timezone.localdate()
    shop_id = request.query_params.get('shop_id')
    shop_category_id = request.query_params.get('shop_category_id')
    search_query = request.query_params.get('search')

    offers = Offer.objects.filter(
        shop_owner__is_active=True,
        is_active=True,
        start_date__lte=today,
        end_date__gte=today,
    ).select_related('shop_owner', 'shop_owner__shop_category').prefetch_related(
        Prefetch(
            'shop_owner__gallery_images',
            queryset=GalleryImage.objects.filter(status='published').order_by('-uploaded_at'),
            to_attr='published_gallery_images',
        )
    )

    if shop_id:
        offers = offers.filter(shop_owner_id=shop_id)
    if shop_category_id:
        offers = offers.filter(shop_owner__shop_category_id=shop_category_id)
    if search_query:
        offers = offers.filter(
            Q(title__icontains=search_query) | Q(description__icontains=search_query)
        )

    offers = offers.order_by('-created_at', '-id')

    paginator = OfferPagination()
    page = paginator.paginate_queryset(offers, request)

    if page is not None:
        page = list(page)
        offer_ids = [offer.id for offer in page]
        if offer_ids:
            Offer.objects.filter(id__in=offer_ids).update(views_count=F('views_count') + 1)
            for offer in page:
                offer.views_count += 1
        serializer = PublicOfferSerializer(
            page,
            many=True,
            context=_build_public_offer_serializer_context(request, page),
        )
        return paginator.get_paginated_response(serializer.data)

    offers = list(offers)
    offer_ids = [offer.id for offer in offers]
    if offer_ids:
        Offer.objects.filter(id__in=offer_ids).update(views_count=F('views_count') + 1)
        for offer in offers:
            offer.views_count += 1

    serializer = PublicOfferSerializer(
        offers,
        many=True,
        context=_build_public_offer_serializer_context(request, offers),
    )
    return success_response(
        data=serializer.data,
        message=t(request, 'offers_retrieved_successfully'),
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

@api_view(['POST'])
@permission_classes([IsCustomer])
def customer_orders_list_create_view(request):
    """
    Create a customer order.
    POST /api/customer/orders/
    """
    customer = _get_customer_from_request(request)
    if not customer:
        return error_response(message=t(request, 'customer_not_found'), status_code=status.HTTP_404_NOT_FOUND)
    
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
            broadcast_chat_message_to_order(order.id, _chat_message_payload(first_msg, request=request), request=request)
        except Exception as e:
            print(f"initial chat message broadcast error: {e}")

        response_serializer = OrderSerializer(order, context={'request': request})
        try:
            notify_new_order(order.shop_owner_id, response_serializer.data)
        except Exception as e:
            print(f"new_order WebSocket error: {e}")

        try:
            received_msg = ChatMessage.objects.create(
                order=order,
                chat_type='shop_customer',
                sender_type='shop_owner',
                sender_shop_owner=order.shop_owner,
                message_type='text',
                content='order_received_wait_for_invoice',
            )
            broadcast_chat_message_to_customer(
                order.id,
                'shop_customer',
                _chat_message_payload(received_msg, request=request),
                request=request
            )
        except Exception as e:
            print(f"order received chat message error: {e}")

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
    
    old_status = order.status
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
        broadcast_chat_message_to_order(order.id, _chat_message_payload(accepted_msg, request=request), request=request)
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

    sync_driver_order_state(
        order,
        previous_status=old_status,
        previous_driver_id=order.driver_id,
        request=request,
    )
    
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

    old_status = order.status
    current_driver_id = order.driver_id
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
        broadcast_chat_message_to_order(order.id, _chat_message_payload(rejected_msg, request=request), request=request)
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

    sync_driver_order_state(
        order,
        previous_status=old_status,
        previous_driver_id=current_driver_id,
        request=request,
    )

    return success_response(
        data=response_serializer.data,
        message='تم رفض الفاتورة والطلب',
        status_code=status.HTTP_200_OK
    )


@api_view(['GET', 'PUT', 'PATCH'])
@permission_classes([IsCustomer])
def customer_profile_view(request):
    """
    عرض وتحديث ملف العميل
    GET/PUT/PATCH /api/customer/profile/
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
        serializer = CustomerAppProfileSerializer(customer, context={'request': request})
        return success_response(data=serializer.data, message=t(request, 'profile_retrieved_successfully'))
    
    elif request.method in ('PUT', 'PATCH'):
        payload = {}

        name_value = request.data.get('name', request.data.get('full_name'))
        if name_value is not None:
            payload['name'] = name_value

        phone_value = request.data.get('phone_number', request.data.get('phone'))
        if phone_value is not None:
            normalized_phone = normalize_phone(phone_value)
            if normalized_phone != customer.phone_number:
                return error_response(
                    message=t(request, 'phone_number_change_requires_otp_verification'),
                    errors={
                        'phone_number': [
                            t(request, 'phone_number_change_requires_otp_verification')
                        ]
                    },
                    status_code=status.HTTP_400_BAD_REQUEST,
                )
            payload['phone_number'] = normalized_phone

        current_password = (
            request.data.get('current_password')
            or request.data.get('old_password')
            or request.data.get('password')
        )
        if current_password is not None:
            payload['current_password'] = current_password

        new_password = request.data.get('new_password')
        if new_password is not None:
            payload['new_password'] = new_password

        confirm_password = (
            request.data.get('confirm_password')
            or request.data.get('confirm_new_password')
            or request.data.get('new_password_confirmation')
        )
        if confirm_password is not None:
            payload['confirm_password'] = confirm_password

        remove_profile_image = request.data.get('remove_profile_image', request.data.get('delete_profile_image'))
        if remove_profile_image is not None:
            payload['remove_profile_image'] = remove_profile_image

        profile_image = (
            request.FILES.get('profile_image')
            or request.FILES.get('avatar')
            or request.FILES.get('image')
        )
        if profile_image is not None:
            payload['profile_image'] = profile_image

        serializer = CustomerProfileUpdateSerializer(
            customer,
            data=payload,
            partial=True,
            context={'request': request},
        )
        if not serializer.is_valid():
            return error_response(
                message=t(request, 'invalid_data'),
                errors=serializer.errors,
                status_code=status.HTTP_400_BAD_REQUEST,
            )

        serializer.save()
        response_serializer = CustomerAppProfileSerializer(customer, context={'request': request})
        return success_response(data=response_serializer.data, message=t(request, 'profile_updated_successfully'))


@api_view(['POST'])
@permission_classes([IsCustomer])
def customer_profile_phone_send_otp_view(request):
    """
    Request OTP before changing the customer's phone number.
    POST /api/customer/profile/phone/send-otp/
    """
    customer = _get_customer_from_request(request)
    if not customer:
        return error_response(message=t(request, 'customer_not_found'), status_code=status.HTTP_404_NOT_FOUND)

    new_phone_number = request.data.get('new_phone_number', request.data.get('phone_number'))
    if not new_phone_number:
        return error_response(
            message=t(request, 'phone_number_is_required'),
            errors={'phone_number': [t(request, 'phone_number_is_required')]},
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    normalized_phone = normalize_phone(new_phone_number)
    if normalized_phone == customer.phone_number:
        return error_response(
            message=t(request, 'new_phone_number_matches_current_phone_number'),
            errors={'phone_number': [t(request, 'new_phone_number_matches_current_phone_number')]},
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    phone_variants = CustomerProfileUpdateSerializer._phone_variants(new_phone_number)
    existing_customer = Customer.objects.filter(phone_number__in=phone_variants).exclude(pk=customer.pk)
    if existing_customer.exists():
        return error_response(
            message=t(request, 'phone_number_is_already_registered'),
            errors={'phone_number': [t(request, 'phone_number_is_already_registered')]},
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    send_ok, send_msg = otp_send(normalized_phone)
    if not send_ok:
        return error_response(
            message=localize_message(request, send_msg),
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    cache.set(
        _customer_phone_change_cache_key(customer.id),
        {'phone_number': normalized_phone},
        CUSTOMER_PHONE_CHANGE_OTP_TTL_SECONDS,
    )

    return success_response(
        data={
            'new_phone_number': normalized_phone,
            'expires_in_seconds': CUSTOMER_PHONE_CHANGE_OTP_TTL_SECONDS,
        },
        message=t(request, 'phone_number_change_otp_sent_successfully'),
        status_code=status.HTTP_200_OK,
    )


@api_view(['POST'])
@permission_classes([IsCustomer])
def customer_profile_phone_verify_otp_view(request):
    """
    Verify OTP and complete the customer's phone number change.
    POST /api/customer/profile/phone/verify-otp/
    """
    customer = _get_customer_from_request(request)
    if not customer:
        return error_response(message=t(request, 'customer_not_found'), status_code=status.HTTP_404_NOT_FOUND)

    otp_code = request.data.get('otp')
    new_phone_number = request.data.get('new_phone_number', request.data.get('phone_number'))
    if not new_phone_number:
        return error_response(
            message=t(request, 'phone_number_is_required'),
            errors={'phone_number': [t(request, 'phone_number_is_required')]},
            status_code=status.HTTP_400_BAD_REQUEST,
        )
    if not otp_code:
        return error_response(
            message=t(request, 'verification_code_is_required'),
            errors={'otp': [t(request, 'verification_code_is_required')]},
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    normalized_phone = normalize_phone(new_phone_number)
    pending_change = cache.get(_customer_phone_change_cache_key(customer.id))
    if not pending_change:
        return error_response(
            message=t(request, 'phone_number_change_otp_request_not_found'),
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    if normalized_phone != pending_change.get('phone_number'):
        return error_response(
            message=t(request, 'phone_number_change_otp_phone_mismatch'),
            errors={'phone_number': [t(request, 'phone_number_change_otp_phone_mismatch')]},
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    phone_variants = CustomerProfileUpdateSerializer._phone_variants(normalized_phone)
    existing_customer = Customer.objects.filter(phone_number__in=phone_variants).exclude(pk=customer.pk)
    if existing_customer.exists():
        return error_response(
            message=t(request, 'phone_number_is_already_registered'),
            errors={'phone_number': [t(request, 'phone_number_is_already_registered')]},
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    if not otp_verify(normalized_phone, otp_code):
        return error_response(
            message=t(request, 'verification_code_is_invalid_or_expired'),
            status_code=status.HTTP_401_UNAUTHORIZED,
        )

    customer.phone_number = normalized_phone
    customer.save(update_fields=['phone_number', 'updated_at'])
    cache.delete(_customer_phone_change_cache_key(customer.id))

    refresh = CustomerTokenObtainPairSerializer.get_token(customer)
    serializer = CustomerAppProfileSerializer(customer, context={'request': request})
    return success_response(
        data={
            'refresh': str(refresh),
            'access': str(refresh.access_token),
            'customer': serializer.data,
        },
        message=t(request, 'phone_number_updated_successfully_after_otp_verification'),
        status_code=status.HTTP_200_OK,
    )


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
        serializer = CustomerAppAddressSerializer(addresses, many=True, context={'request': request})
        return success_response(data=serializer.data, message=t(request, 'addresses_retrieved_successfully'))
    
    elif request.method == 'POST':
        serializer = CustomerAddressSerializer(data=request.data, context={'request': request})
        if serializer.is_valid():
            address = serializer.save(customer=customer)
            response_serializer = CustomerAppAddressSerializer(address, context={'request': request})
            return success_response(data=response_serializer.data, message=t(request, 'address_added_successfully'), status_code=status.HTTP_201_CREATED)
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
        serializer = CustomerAppAddressSerializer(address, context={'request': request})
        return success_response(data=serializer.data, message=t(request, 'address_retrieved_successfully'))
    
    elif request.method == 'PUT':
        serializer = CustomerAddressSerializer(address, data=request.data, partial=True, context={'request': request})
        if serializer.is_valid():
            serializer.save()
            response_serializer = CustomerAppAddressSerializer(address, context={'request': request})
            return success_response(data=response_serializer.data, message=t(request, 'address_updated_successfully'))
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
