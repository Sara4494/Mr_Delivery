from datetime import timedelta
from decimal import Decimal, InvalidOperation
from math import ceil

from django.db.models import Count, Q, Sum
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView
from rest_framework_simplejwt.tokens import RefreshToken
from django.utils import timezone
from django.utils.crypto import get_random_string
from .token_serializers import ShopOwnerTokenObtainPairSerializer
from .models import (
    ADMIN_DESKTOP_FULL_ADMIN_ROLE,
    ADMIN_DESKTOP_PERMISSION_CHOICES,
    ADMIN_DESKTOP_READONLY_ADMIN_ROLES,
    ADMIN_DESKTOP_ROLE_CHOICES,
    AdminDesktopUser,
    ShopCategory,
    ShopOwner,
    get_admin_desktop_role_permissions,
)
from .permissions import IsAdminDesktopUser
from .utils import success_response, error_response, t, localize_message
from .otp_service import send_otp as otp_send, verify_otp as otp_verify, normalize_phone


class ShopOwnerTokenObtainPairView(TokenObtainPairView):
    """
    تسجيل دخول صاحب المحل وإرجاع JWT Token
    POST /api/shop/login/
    Body: {
        "shop_number": "رقم المحل",
        "password": "كلمة المرور"
    }
    """
    serializer_class = ShopOwnerTokenObtainPairSerializer
    
    def post(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        
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


class ShopOwnerTokenRefreshView(TokenRefreshView):
    """
    تحديث JWT Token
    POST /api/shop/token/refresh/
    Body: {
        "refresh": "refresh_token"
    }
    """
    
    def post(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        
        try:
            serializer.is_valid(raise_exception=True)
        except Exception as e:
            errors = serializer.errors if hasattr(serializer, 'errors') else {'detail': str(e)}
            return error_response(
                message=t(request, 'token_refresh_failed'),
                errors=errors,
                status_code=status.HTTP_400_BAD_REQUEST
            )
        
        return success_response(
            data=serializer.validated_data,
            message=t(request, 'token_refreshed_successfully'),
            status_code=status.HTTP_200_OK
        )


def _admin_desktop_phone_variants(phone_number):
    if not phone_number:
        return []
    normalized = normalize_phone(phone_number)
    variants = [normalized, str(phone_number).strip()]
    if normalized.startswith("+20"):
        variants.extend([normalized[3:], "0" + normalized[3:]])
    return list(dict.fromkeys(v for v in variants if v))


def _serialize_admin_desktop_user(request, user):
    permissions = user.get_resolved_permissions()
    profile_image = user.profile_image.url if user.profile_image else None
    profile_image_url = request.build_absolute_uri(profile_image) if profile_image else None
    return {
        "id": user.id,
        "name": user.name,
        "phone_number": user.phone_number,
        "email": user.email,
        "role": user.role,
        "role_display": user.get_role_display(),
        "permissions": permissions,
        "is_active": user.is_active,
        "profile_image": profile_image,
        "profile_image_url": profile_image_url,
        "last_login_at": user.last_login_at,
        "created_at": user.created_at,
    }


def _build_admin_desktop_auth_payload(request, user):
    permissions = user.get_resolved_permissions()
    refresh = RefreshToken()
    refresh["admin_desktop_user_id"] = user.id
    refresh["phone_number"] = user.phone_number
    refresh["role"] = user.role
    refresh["permissions"] = permissions
    refresh["user_type"] = "admin_desktop"

    return {
        "refresh": str(refresh),
        "access": str(refresh.access_token),
        "user": _serialize_admin_desktop_user(request, user),
        "role": "admin_desktop",
    }


def _admin_desktop_permission_catalog():
    return [
        {
            "code": code,
            "label": label,
        }
        for code, label in ADMIN_DESKTOP_PERMISSION_CHOICES
    ]


def _admin_desktop_role_catalog():
    role_labels = dict(ADMIN_DESKTOP_ROLE_CHOICES)
    return [
        {
            "code": role_code,
            "label": role_labels.get(role_code, role_code),
            "default_permissions": get_admin_desktop_role_permissions(role_code),
            "capabilities": {
                "can_view_admin_users": role_code in ADMIN_DESKTOP_READONLY_ADMIN_ROLES
                or role_code == ADMIN_DESKTOP_FULL_ADMIN_ROLE,
                "can_manage_admin_users": role_code == ADMIN_DESKTOP_FULL_ADMIN_ROLE,
            },
        }
        for role_code, _ in ADMIN_DESKTOP_ROLE_CHOICES
    ]


def _normalize_admin_desktop_permissions(role, permissions):
    allowed_permissions = set(get_admin_desktop_role_permissions(role))
    base_permissions = permissions if permissions is not None else get_admin_desktop_role_permissions(role)
    normalized = []
    for permission in base_permissions:
        if permission in allowed_permissions and permission not in normalized:
            normalized.append(permission)
    return normalized


def _can_view_admin_desktop_users(user):
    if not user:
        return False
    return user.role == ADMIN_DESKTOP_FULL_ADMIN_ROLE or user.role in ADMIN_DESKTOP_READONLY_ADMIN_ROLES


def _can_manage_admin_desktop_users(user):
    if not user:
        return False
    return user.role == ADMIN_DESKTOP_FULL_ADMIN_ROLE


def _parse_bool(value, default=None):
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "on"}:
        return True
    if text in {"0", "false", "no", "off"}:
        return False
    return default


def _serialize_admin_desktop_user_list_item(user):
    role_labels = dict(ADMIN_DESKTOP_ROLE_CHOICES)
    permissions = user.get_resolved_permissions()
    return {
        "id": user.id,
        "name": user.name,
        "phone_number": user.phone_number,
        "email": user.email,
        "role": user.role,
        "role_display": role_labels.get(user.role, user.role),
        "permissions": permissions,
        "permissions_count": len(permissions),
        "permissions_preview": [
            dict(ADMIN_DESKTOP_PERMISSION_CHOICES).get(code, code)
            for code in permissions[:3]
        ],
        "is_active": user.is_active,
        "status_label": "نشط" if user.is_active else "غير نشط",
        "created_at": user.created_at,
    }


def _admin_desktop_users_summary(queryset):
    role_counts = queryset.values("role").annotate(total=Count("id"))
    active_count = queryset.filter(is_active=True).count()
    total_count = queryset.count()
    role_labels = dict(ADMIN_DESKTOP_ROLE_CHOICES)
    roles = [
        {
            "role": item["role"],
            "role_display": role_labels.get(item["role"], item["role"]),
            "users_count": item["total"],
        }
        for item in role_counts
    ]
    return {
        "cards": {
            "total_roles": len(ADMIN_DESKTOP_ROLE_CHOICES),
            "linked_users": total_count,
            "active_roles": len([item for item in role_counts if item["total"] > 0]),
            "active_users": active_count,
        },
        "roles": roles,
    }


def _validate_admin_desktop_user_payload(request, *, partial=False, instance=None):
    role_values = {code for code, _ in ADMIN_DESKTOP_ROLE_CHOICES}

    name = request.data.get("name")
    phone_number = request.data.get("phone_number")
    email = request.data.get("email")
    password = request.data.get("password")
    role = request.data.get("role")
    permissions = request.data.get("permissions")
    is_active = request.data.get("is_active")
    profile_image = request.FILES.get("profile_image")

    errors = {}
    payload = {}

    if not partial or name is not None:
        if not name:
            errors["name"] = [t(request, "name_is_required")]
        else:
            payload["name"] = str(name).strip()

    if not partial or phone_number is not None:
        if not phone_number:
            errors["phone_number"] = [t(request, "phone_number_is_required")]
        else:
            normalized_phone = normalize_phone(phone_number)
            existing = AdminDesktopUser.objects.filter(phone_number=normalized_phone)
            if instance:
                existing = existing.exclude(id=instance.id)
            if existing.exists():
                errors["phone_number"] = [t(request, "phone_number_is_already_registered")]
            else:
                payload["phone_number"] = normalized_phone

    if email is not None:
        email_value = str(email).strip() or None
        existing = AdminDesktopUser.objects.filter(email=email_value) if email_value else AdminDesktopUser.objects.none()
        if instance:
            existing = existing.exclude(id=instance.id)
        if email_value and existing.exists():
            errors["email"] = ["البريد الإلكتروني مستخدم بالفعل"]
        else:
            payload["email"] = email_value
    elif not partial and instance is None:
        payload["email"] = None

    if not partial or role is not None:
        if not role:
            errors["role"] = [t(request, "user_type_role_is_required")]
        elif role not in role_values:
            errors["role"] = ["الدور غير صحيح"]
        else:
            payload["role"] = role

    if not partial or instance is None or password is not None:
        if instance is None and not password:
            errors["password"] = [t(request, "password_is_required")]
        elif password:
            if len(str(password)) < 6:
                errors["password"] = [t(request, "password_must_be_at_least_6_characters")]
            else:
                payload["password"] = str(password)

    if permissions is not None:
        if not isinstance(permissions, list):
            errors["permissions"] = ["الصلاحيات يجب أن تكون قائمة"]
        else:
            payload["permissions"] = _normalize_admin_desktop_permissions(
                payload.get("role") or getattr(instance, "role", None),
                permissions,
            )
    elif "role" in payload:
        payload["permissions"] = get_admin_desktop_role_permissions(payload["role"])

    parsed_is_active = _parse_bool(is_active, default=None)
    if is_active is not None and parsed_is_active is None:
        errors["is_active"] = ["قيمة الحالة غير صحيحة"]
    elif parsed_is_active is not None:
        payload["is_active"] = parsed_is_active

    if profile_image is not None:
        payload["profile_image"] = profile_image

    return payload, errors


@api_view(["POST"])
@permission_classes([AllowAny])
def admin_desktop_login_view(request):
    phone_number = request.data.get("phone_number")
    password = request.data.get("password")

    if not phone_number:
        return error_response(
            message=t(request, "phone_number_is_required"),
            status_code=status.HTTP_400_BAD_REQUEST,
            request=request,
        )

    if not password:
        return error_response(
            message=t(request, "password_is_required"),
            status_code=status.HTTP_400_BAD_REQUEST,
            request=request,
        )

    user = (
        AdminDesktopUser.objects
        .filter(phone_number__in=_admin_desktop_phone_variants(phone_number))
        .order_by("-updated_at")
        .first()
    )

    if not user or not user.check_password(password):
        return error_response(
            message=t(request, "phone_number_or_password_is_incorrect"),
            status_code=status.HTTP_401_UNAUTHORIZED,
            request=request,
        )

    if not user.is_active:
        return error_response(
            message=t(request, "account_is_inactive"),
            status_code=status.HTTP_401_UNAUTHORIZED,
            request=request,
        )

    user.last_login_at = timezone.now()
    user.sync_role_permissions()
    user.save(update_fields=["last_login_at", "permissions"])

    return success_response(
        data=_build_admin_desktop_auth_payload(request, user),
        message=t(request, "login_successful"),
        request=request,
    )


@api_view(["GET"])
@permission_classes([IsAuthenticated, IsAdminDesktopUser])
def admin_desktop_me_view(request):
    return success_response(
        data={"user": _serialize_admin_desktop_user(request, request.user)},
        message=t(request, "viewer_profile_retrieved_successfully"),
        request=request,
    )


@api_view(["GET"])
@permission_classes([IsAuthenticated, IsAdminDesktopUser])
def admin_desktop_roles_permissions_view(request):
    return success_response(
        data={
            "roles": _admin_desktop_role_catalog(),
            "permissions": _admin_desktop_permission_catalog(),
        },
        message="تم جلب الأدوار والصلاحيات بنجاح",
        request=request,
    )


@api_view(["GET", "POST"])
@permission_classes([IsAuthenticated, IsAdminDesktopUser])
def admin_desktop_users_view(request):
    if request.method == "GET":
        if not _can_view_admin_desktop_users(request.user):
            return error_response(
                message="ليس لديك صلاحية لعرض المديرين",
                status_code=status.HTTP_403_FORBIDDEN,
                request=request,
            )

        search = str(request.query_params.get("search", "")).strip()
        role = str(request.query_params.get("role", "")).strip()
        is_active = _parse_bool(request.query_params.get("is_active"), default=None)
        page = max(int(request.query_params.get("page", 1) or 1), 1)
        page_size = max(min(int(request.query_params.get("page_size", 10) or 10), 100), 1)

        queryset = AdminDesktopUser.objects.all().order_by("-created_at")
        if search:
            queryset = queryset.filter(
                Q(name__icontains=search)
                | Q(phone_number__icontains=search)
                | Q(email__icontains=search)
            )
        if role:
            queryset = queryset.filter(role=role)
        if is_active is not None:
            queryset = queryset.filter(is_active=is_active)

        total_count = queryset.count()
        total_pages = ceil(total_count / page_size) if total_count else 1
        start = (page - 1) * page_size
        users = list(queryset[start:start + page_size])

        return success_response(
            data={
                "summary": _admin_desktop_users_summary(AdminDesktopUser.objects.all()),
                "filters": {
                    "search": search,
                    "role": role or None,
                    "is_active": is_active,
                },
                "pagination": {
                    "page": page,
                    "page_size": page_size,
                    "total_count": total_count,
                    "total_pages": total_pages,
                    "has_next": page < total_pages,
                    "has_previous": page > 1,
                },
                "capabilities": {
                    "can_view_admin_users": _can_view_admin_desktop_users(request.user),
                    "can_manage_admin_users": _can_manage_admin_desktop_users(request.user),
                },
                "users": [_serialize_admin_desktop_user_list_item(user) for user in users],
            },
            message="تم جلب مستخدمي الديسكتوب بنجاح",
            request=request,
        )

    if not _can_manage_admin_desktop_users(request.user):
        return error_response(
            message="إضافة المديرين متاحة فقط لمطور النظام",
            status_code=status.HTTP_403_FORBIDDEN,
            request=request,
        )

    payload, errors = _validate_admin_desktop_user_payload(request, partial=False)
    if errors:
        return error_response(
            message="بيانات المستخدم غير صحيحة",
            errors=errors,
            status_code=status.HTTP_400_BAD_REQUEST,
            request=request,
        )

    user = AdminDesktopUser(
        name=payload["name"],
        phone_number=payload["phone_number"],
        email=payload.get("email"),
        role=payload["role"],
        permissions=payload.get("permissions") or get_admin_desktop_role_permissions(payload["role"]),
        is_active=payload.get("is_active", True),
    )
    user.password = payload["password"]
    if "profile_image" in payload:
        user.profile_image = payload["profile_image"]
    user.save()

    return success_response(
        data={"user": _serialize_admin_desktop_user(request, user)},
        message="تم إضافة مستخدم الديسكتوب بنجاح",
        status_code=status.HTTP_201_CREATED,
        request=request,
    )


@api_view(["GET", "PUT", "PATCH", "DELETE"])
@permission_classes([IsAuthenticated, IsAdminDesktopUser])
def admin_desktop_user_detail_view(request, user_id):
    if request.method == "GET" and not _can_view_admin_desktop_users(request.user):
        return error_response(
            message="ليس لديك صلاحية لعرض المديرين",
            status_code=status.HTTP_403_FORBIDDEN,
            request=request,
        )

    if request.method in {"PUT", "PATCH", "DELETE"} and not _can_manage_admin_desktop_users(request.user):
        return error_response(
            message="إدارة المديرين متاحة فقط لمطور النظام",
            status_code=status.HTTP_403_FORBIDDEN,
            request=request,
        )

    try:
        target_user = AdminDesktopUser.objects.get(id=user_id)
    except AdminDesktopUser.DoesNotExist:
        return error_response(
            message="مستخدم الديسكتوب غير موجود",
            status_code=status.HTTP_404_NOT_FOUND,
            request=request,
        )

    if request.method == "GET":
        return success_response(
            data={
                "user": _serialize_admin_desktop_user(request, target_user),
                "permission_tags": [
                    {
                        "code": code,
                        "label": dict(ADMIN_DESKTOP_PERMISSION_CHOICES).get(code, code),
                    }
                    for code in target_user.get_resolved_permissions()
                ],
            },
            message="تم جلب تفاصيل مستخدم الديسكتوب بنجاح",
            request=request,
        )

    if request.method in {"PUT", "PATCH"}:
        payload, errors = _validate_admin_desktop_user_payload(
            request,
            partial=request.method == "PATCH",
            instance=target_user,
        )
        if errors:
            return error_response(
                message="بيانات المستخدم غير صحيحة",
                errors=errors,
                status_code=status.HTTP_400_BAD_REQUEST,
                request=request,
            )

        update_fields = []
        for field in ("name", "phone_number", "email", "role", "permissions", "is_active", "profile_image"):
            if field in payload:
                setattr(target_user, field, payload[field])
                update_fields.append(field)

        if "password" in payload:
            target_user.password = payload["password"]
            update_fields.append("password")

        if update_fields:
            target_user.save(update_fields=update_fields)

        return success_response(
            data={"user": _serialize_admin_desktop_user(request, target_user)},
            message="تم تحديث مستخدم الديسكتوب بنجاح",
            request=request,
        )

    if request.user.id == target_user.id:
        return error_response(
            message="لا يمكن حذف الحساب المستخدم حاليا",
            status_code=status.HTTP_400_BAD_REQUEST,
            request=request,
        )

    target_user.delete()
    return success_response(
        message="تم حذف مستخدم الديسكتوب بنجاح",
        request=request,
    )



def _has_admin_desktop_permission(user, permission_code):
    if not user or not getattr(user, "is_active", False):
        return False
    if getattr(user, "role", None) == ADMIN_DESKTOP_FULL_ADMIN_ROLE:
        return True
    return permission_code in (user.get_resolved_permissions() or [])


def _build_media_url(request, file_field):
    if not file_field:
        return None
    try:
        return request.build_absolute_uri(file_field.url)
    except Exception:
        return getattr(file_field, "url", None)


def _parse_admin_store_date_range(value):
    key = str(value or "all").strip().lower()
    today = timezone.localdate()
    if key == "today":
        return key, today, today
    if key in {"last_7_days", "7_days", "7d"}:
        return "last_7_days", today - timedelta(days=6), today
    if key in {"last_30_days", "30_days", "30d"}:
        return "last_30_days", today - timedelta(days=29), today
    return "all", None, None


def _parse_commission_rate(value):
    if value in (None, ""):
        return None, None
    try:
        commission_rate = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None, "نسبة العمولة غير صحيحة"
    if commission_rate < 0 or commission_rate > 100:
        return None, "نسبة العمولة يجب أن تكون بين 0 و 100"
    return commission_rate, None


def _generate_admin_store_number():
    while True:
        candidate = f"ST-{get_random_string(6, allowed_chars='0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ')}"
        if not ShopOwner.objects.filter(shop_number=candidate).exists():
            return candidate


def _admin_store_status_meta(shop):
    status_key = getattr(shop, "admin_status", "active") or "active"
    status_label = dict(ShopOwner.ADMIN_STATUS_CHOICES).get(status_key, status_key)
    return {
        "key": status_key,
        "label": status_label,
        "is_active": bool(getattr(shop, "is_active", False)),
    }


def _serialize_admin_store_list_item(request, shop):
    from shop.models import Employee, Order

    month_start = timezone.localdate().replace(day=1)
    orders_qs = Order.objects.filter(shop_owner=shop)
    monthly_revenue = (
        orders_qs.filter(status="delivered", created_at__date__gte=month_start)
        .aggregate(total=Sum("total_amount"))
        .get("total")
        or 0
    )
    status_meta = _admin_store_status_meta(shop)
    return {
        "id": shop.id,
        "shop_name": shop.shop_name,
        "owner_name": shop.owner_name,
        "phone_number": shop.phone_number,
        "profile_image_url": _build_media_url(request, shop.profile_image),
        "shop_category_id": shop.shop_category_id,
        "shop_category_name": shop.shop_category.name if shop.shop_category else None,
        "commission_rate": float(shop.commission_rate or 0),
        "joined_at": shop.created_at,
        "monthly_revenue": float(monthly_revenue),
        "orders_count": orders_qs.count(),
        "employees_count": Employee.objects.filter(shop_owner=shop).count(),
        "status": status_meta,
    }


def _serialize_admin_store_detail(request, shop):
    from shop.models import ChatMessage, Employee, Order

    month_start = timezone.localdate().replace(day=1)
    orders_qs = Order.objects.filter(shop_owner=shop)
    delivered_orders_qs = orders_qs.filter(status="delivered")
    monthly_revenue = (
        delivered_orders_qs.filter(created_at__date__gte=month_start)
        .aggregate(total=Sum("total_amount"))
        .get("total")
        or 0
    )

    recent_activities = []
    if shop.updated_at:
        recent_activities.append({
            "type": "store_updated",
            "title": "تم تحديث بيانات المتجر",
            "description": "آخر تحديث على معلومات المتجر والإعدادات الأساسية.",
            "created_at": shop.updated_at,
        })

    for order in orders_qs.order_by("-updated_at")[:3]:
        recent_activities.append({
            "type": "order_activity",
            "title": f"تحديث على الطلب #{order.order_number}",
            "description": f"حالة الطلب الحالية: {order.get_status_display()}",
            "created_at": order.updated_at,
        })

    for employee in Employee.objects.filter(shop_owner=shop).order_by("-updated_at")[:2]:
        recent_activities.append({
            "type": "employee_activity",
            "title": f"تحديث بيانات الموظف {employee.name}",
            "description": f"الدور: {employee.get_role_display()}",
            "created_at": employee.updated_at,
        })

    last_message = (
        ChatMessage.objects.filter(order__shop_owner=shop)
        .select_related("order")
        .order_by("-created_at")
        .first()
    )
    if last_message:
        recent_activities.append({
            "type": "chat_activity",
            "title": "آخر نشاط مراسلة",
            "description": f"على الطلب #{last_message.order.order_number}",
            "created_at": last_message.created_at,
        })

    recent_activities.sort(key=lambda item: item["created_at"] or timezone.now(), reverse=True)
    status_meta = _admin_store_status_meta(shop)
    return {
        "store": {
            "id": shop.id,
            "shop_name": shop.shop_name,
            "owner_name": shop.owner_name,
            "phone_number": shop.phone_number,
            "description": shop.description,
            "profile_image_url": _build_media_url(request, shop.profile_image),
            "shop_category_id": shop.shop_category_id,
            "shop_category_name": shop.shop_category.name if shop.shop_category else None,
            "commission_rate": float(shop.commission_rate or 0),
            "joined_at": shop.created_at,
            "updated_at": shop.updated_at,
            "status": status_meta,
            "suspension": {
                "reason": shop.suspension_reason,
                "started_at": shop.suspension_started_at,
                "ends_at": shop.suspension_ends_at,
            },
            "admin_notes": shop.admin_notes,
        },
        "stats": {
            "total_orders": orders_qs.count(),
            "monthly_revenue": float(monthly_revenue),
            "employees_count": Employee.objects.filter(shop_owner=shop).count(),
            "delivered_orders_count": delivered_orders_qs.count(),
        },
        "recent_activities": recent_activities[:6],
    }


def _validate_admin_store_payload(request, *, partial=False, instance=None):
    status_values = {code for code, _ in ShopOwner.ADMIN_STATUS_CHOICES}

    shop_name = request.data.get("shop_name")
    owner_name = request.data.get("owner_name")
    phone_number = request.data.get("phone_number")
    password = request.data.get("password")
    shop_category_id = request.data.get("shop_category_id")
    commission_rate = request.data.get("commission_rate")
    admin_status = request.data.get("admin_status")
    description = request.data.get("description")
    admin_notes = request.data.get("admin_notes")
    profile_image = request.FILES.get("profile_image")
    remove_profile_image = _parse_bool(request.data.get("remove_profile_image"), default=False)

    payload = {}
    errors = {}

    if not partial or shop_name is not None:
        if not shop_name:
            errors["shop_name"] = ["اسم المتجر مطلوب"]
        else:
            payload["shop_name"] = str(shop_name).strip()

    if owner_name is not None:
        payload["owner_name"] = str(owner_name).strip()
    elif not partial and instance is None:
        payload["owner_name"] = str(shop_name or "").strip()

    if not partial or phone_number is not None:
        if not phone_number:
            errors["phone_number"] = ["رقم الهاتف مطلوب"]
        else:
            normalized_phone = normalize_phone(phone_number)
            existing = ShopOwner.objects.filter(phone_number=normalized_phone)
            if instance:
                existing = existing.exclude(id=instance.id)
            if existing.exists():
                errors["phone_number"] = ["رقم الهاتف مستخدم بالفعل"]
            else:
                payload["phone_number"] = normalized_phone

    if not partial or instance is None or password is not None:
        if instance is None and not password:
            errors["password"] = ["كلمة المرور مطلوبة"]
        elif password:
            if len(str(password)) < 6:
                errors["password"] = ["كلمة المرور يجب أن تكون 6 أحرف على الأقل"]
            else:
                payload["password"] = str(password)

    if shop_category_id is not None:
        if str(shop_category_id).strip() in {"", "null", "None", "0"}:
            payload["shop_category"] = None
        else:
            try:
                payload["shop_category"] = ShopCategory.objects.get(id=shop_category_id, is_active=True)
            except (ValueError, ShopCategory.DoesNotExist):
                errors["shop_category_id"] = ["تصنيف المتجر غير موجود"]

    parsed_commission_rate, commission_error = _parse_commission_rate(commission_rate)
    if commission_error:
        errors["commission_rate"] = [commission_error]
    elif parsed_commission_rate is not None:
        payload["commission_rate"] = parsed_commission_rate
    elif not partial and instance is None:
        payload["commission_rate"] = Decimal("0")

    if instance is not None and admin_status is not None:
        pass
    elif admin_status is not None:
        admin_status_value = str(admin_status).strip()
        if admin_status_value not in status_values:
            errors["admin_status"] = ["الحالة الإدارية غير صحيحة"]
        elif admin_status_value == "suspended":
            errors["admin_status"] = ["تعليق المتجر يتم من خلال endpoint التعليق المخصص"]
        else:
            payload["admin_status"] = admin_status_value
            payload["is_active"] = admin_status_value == "active"
    elif not partial and instance is None:
        payload["admin_status"] = "active"
        payload["is_active"] = True

    if description is not None:
        payload["description"] = str(description).strip() or None

    if admin_notes is not None:
        payload["admin_notes"] = str(admin_notes).strip() or None

    if profile_image is not None:
        payload["profile_image"] = profile_image
    if remove_profile_image:
        payload["profile_image"] = None

    return payload, errors


@api_view(["GET"])
@permission_classes([IsAuthenticated, IsAdminDesktopUser])
def admin_desktop_store_categories_view(request):
    if not _has_admin_desktop_permission(request.user, "store_management"):
        return error_response(
            message="ليست لديك صلاحية لإدارة المتاجر",
            status_code=status.HTTP_403_FORBIDDEN,
            request=request,
        )

    categories = ShopCategory.objects.filter(is_active=True).order_by("name")
    return success_response(
        data={
            "categories": [
                {
                    "id": category.id,
                    "name": category.name,
                }
                for category in categories
            ]
        },
        message="تم جلب تصنيفات المتاجر بنجاح",
        request=request,
    )


@api_view(["GET", "POST"])
@permission_classes([IsAuthenticated, IsAdminDesktopUser])
def admin_desktop_stores_view(request):
    if not _has_admin_desktop_permission(request.user, "store_management"):
        return error_response(
            message="ليست لديك صلاحية لإدارة المتاجر",
            status_code=status.HTTP_403_FORBIDDEN,
            request=request,
        )

    if request.method == "GET":
        search = str(request.query_params.get("search", "")).strip()
        admin_status = str(request.query_params.get("status", "")).strip().lower()
        joined_range, date_from, date_to = _parse_admin_store_date_range(request.query_params.get("joined_range"))
        page = max(int(request.query_params.get("page", 1) or 1), 1)
        page_size = max(min(int(request.query_params.get("page_size", 10) or 10), 100), 1)

        queryset = ShopOwner.objects.select_related("shop_category").all().order_by("-created_at")
        if search:
            queryset = queryset.filter(
                Q(shop_name__icontains=search)
                | Q(owner_name__icontains=search)
                | Q(phone_number__icontains=search)
            )
        if admin_status and admin_status != "all":
            queryset = queryset.filter(admin_status=admin_status)
        if date_from and date_to:
            queryset = queryset.filter(created_at__date__gte=date_from, created_at__date__lte=date_to)

        total_count = queryset.count()
        total_pages = ceil(total_count / page_size) if total_count else 1
        start = (page - 1) * page_size
        stores = list(queryset[start:start + page_size])

        all_shops = ShopOwner.objects.all()
        summary = {
            "total": all_shops.count(),
            "active": all_shops.filter(admin_status="active").count(),
            "pending_review": all_shops.filter(admin_status="pending_review").count(),
            "suspended": all_shops.filter(admin_status="suspended").count(),
        }

        return success_response(
            data={
                "summary": summary,
                "filters": {
                    "search": search,
                    "status": admin_status or "all",
                    "joined_range": joined_range,
                },
                "pagination": {
                    "page": page,
                    "page_size": page_size,
                    "total_count": total_count,
                    "total_pages": total_pages,
                    "has_next": page < total_pages,
                    "has_previous": page > 1,
                },
                "stores": [_serialize_admin_store_list_item(request, shop) for shop in stores],
            },
            message="تم جلب المتاجر بنجاح",
            request=request,
        )

    payload, errors = _validate_admin_store_payload(request, partial=False, instance=None)
    if errors:
        return error_response(
            message="بيانات المتجر غير صحيحة",
            errors=errors,
            status_code=status.HTTP_400_BAD_REQUEST,
            request=request,
        )

    shop = ShopOwner(
        owner_name=payload.get("owner_name") or payload["shop_name"],
        shop_name=payload["shop_name"],
        shop_number=_generate_admin_store_number(),
        phone_number=payload["phone_number"],
        password=payload["password"],
        shop_category=payload.get("shop_category"),
        description=payload.get("description"),
        admin_status=payload.get("admin_status", "active"),
        commission_rate=payload.get("commission_rate", Decimal("0")),
        admin_notes=payload.get("admin_notes"),
        is_active=payload.get("is_active", True),
    )
    if "profile_image" in payload:
        shop.profile_image = payload["profile_image"]
    shop.save()

    return success_response(
        data=_serialize_admin_store_detail(request, shop),
        message="تم إضافة المتجر بنجاح",
        status_code=status.HTTP_201_CREATED,
        request=request,
    )


@api_view(["GET", "PUT", "PATCH"])
@permission_classes([IsAuthenticated, IsAdminDesktopUser])
def admin_desktop_store_detail_view(request, shop_id):
    if not _has_admin_desktop_permission(request.user, "store_management"):
        return error_response(
            message="ليست لديك صلاحية لإدارة المتاجر",
            status_code=status.HTTP_403_FORBIDDEN,
            request=request,
        )

    try:
        shop = ShopOwner.objects.select_related("shop_category").get(id=shop_id)
    except ShopOwner.DoesNotExist:
        return error_response(
            message="المتجر غير موجود",
            status_code=status.HTTP_404_NOT_FOUND,
            request=request,
        )

    if request.method == "GET":
        return success_response(
            data=_serialize_admin_store_detail(request, shop),
            message="تم جلب تفاصيل المتجر بنجاح",
            request=request,
        )

    payload, errors = _validate_admin_store_payload(
        request,
        partial=request.method == "PATCH",
        instance=shop,
    )
    if errors:
        return error_response(
            message="بيانات المتجر غير صحيحة",
            errors=errors,
            status_code=status.HTTP_400_BAD_REQUEST,
            request=request,
        )

    update_fields = []
    for field in (
        "owner_name",
        "shop_name",
        "phone_number",
        "shop_category",
        "description",
        "commission_rate",
        "admin_notes",
        "profile_image",
    ):
        if field in payload:
            setattr(shop, field, payload[field])
            update_fields.append(field)

    if "password" in payload:
        shop.password = payload["password"]
        update_fields.append("password")

    if update_fields:
        shop.save(update_fields=update_fields)

    return success_response(
        data=_serialize_admin_store_detail(request, shop),
        message="تم تحديث بيانات المتجر بنجاح",
        request=request,
    )


@api_view(["POST"])
@permission_classes([IsAuthenticated, IsAdminDesktopUser])
def admin_desktop_store_suspend_view(request, shop_id):
    if not _has_admin_desktop_permission(request.user, "store_management"):
        return error_response(
            message="ليست لديك صلاحية لإدارة المتاجر",
            status_code=status.HTTP_403_FORBIDDEN,
            request=request,
        )

    try:
        shop = ShopOwner.objects.get(id=shop_id)
    except ShopOwner.DoesNotExist:
        return error_response(
            message="المتجر غير موجود",
            status_code=status.HTTP_404_NOT_FOUND,
            request=request,
        )

    reason = str(request.data.get("reason") or "").strip()
    duration_days = request.data.get("duration_days")
    notify_shop = _parse_bool(request.data.get("notify_shop"), default=True)
    admin_notes = str(request.data.get("admin_notes") or "").strip() or None

    if not reason:
        return error_response(
            message="سبب التعليق مطلوب",
            errors={"reason": ["سبب التعليق مطلوب"]},
            status_code=status.HTTP_400_BAD_REQUEST,
            request=request,
        )

    suspension_ends_at = None
    if duration_days not in (None, "", "null", "None"):
        try:
            duration_value = int(duration_days)
            if duration_value <= 0:
                raise ValueError
            suspension_ends_at = timezone.now() + timedelta(days=duration_value)
        except (TypeError, ValueError):
            return error_response(
                message="مدة التعليق غير صحيحة",
                errors={"duration_days": ["مدة التعليق يجب أن تكون رقمًا صحيحًا أكبر من صفر"]},
                status_code=status.HTTP_400_BAD_REQUEST,
                request=request,
            )

    shop.admin_status = "suspended"
    shop.is_active = False
    shop.suspension_reason = reason
    shop.suspension_started_at = timezone.now()
    shop.suspension_ends_at = suspension_ends_at
    update_fields = ["admin_status", "is_active", "suspension_reason", "suspension_started_at", "suspension_ends_at"]
    if admin_notes is not None:
        shop.admin_notes = admin_notes
        update_fields.append("admin_notes")
    shop.save(update_fields=update_fields)

    return success_response(
        data={
            "store": _serialize_admin_store_list_item(request, shop),
            "notification": {
                "notify_shop": bool(notify_shop),
            },
        },
        message="تم تعليق المتجر بنجاح",
        request=request,
    )


@api_view(["POST"])
@permission_classes([IsAuthenticated, IsAdminDesktopUser])
def admin_desktop_store_activate_view(request, shop_id):
    if not _has_admin_desktop_permission(request.user, "store_management"):
        return error_response(
            message="ليست لديك صلاحية لإدارة المتاجر",
            status_code=status.HTTP_403_FORBIDDEN,
            request=request,
        )

    try:
        shop = ShopOwner.objects.get(id=shop_id)
    except ShopOwner.DoesNotExist:
        return error_response(
            message="المتجر غير موجود",
            status_code=status.HTTP_404_NOT_FOUND,
            request=request,
        )

    admin_notes = request.data.get("admin_notes")
    shop.admin_status = "active"
    shop.is_active = True
    shop.suspension_reason = None
    shop.suspension_started_at = None
    shop.suspension_ends_at = None
    update_fields = ["admin_status", "is_active", "suspension_reason", "suspension_started_at", "suspension_ends_at"]
    if admin_notes is not None:
        shop.admin_notes = str(admin_notes).strip() or None
        update_fields.append("admin_notes")
    shop.save(update_fields=update_fields)

    return success_response(
        data={"store": _serialize_admin_store_list_item(request, shop)},
        message="تم تفعيل المتجر بنجاح",
        request=request,
    )


# ==================== Unified Auth APIs ====================

@api_view(['POST'])
@permission_classes([AllowAny])
def unified_login_view(request):
    """
    تسجيل دخول موحد لجميع المستخدمين
    POST /api/auth/login/
    Body: {
        "role": "shop_owner" | "customer" | "employee" | "driver",
        "phone_number": "رقم الهاتف",  // للعميل والموظف والسائق
        "shop_number": "رقم المحل",     // لصاحب المحل فقط
        "password": "كلمة المرور"
    }
    """
    role = request.data.get('role')
    phone_number = request.data.get('phone_number')
    shop_number = request.data.get('shop_number')
    password = request.data.get('password')
    
    if not role:
        return error_response(
            message=t(request, 'user_type_role_is_required'),
            status_code=status.HTTP_400_BAD_REQUEST
        )
    
    if not password:
        return error_response(
            message=t(request, 'password_is_required'),
            status_code=status.HTTP_400_BAD_REQUEST
        )
    
    # ===== Shop Owner Login =====
    if role == 'shop_owner':
        if not shop_number:
            return error_response(
                message=t(request, 'shop_number_is_required'),
                status_code=status.HTTP_400_BAD_REQUEST
            )
        
        try:
            shop_owner = ShopOwner.objects.get(shop_number=shop_number)
            if not shop_owner.check_password(password):
                return error_response(
                    message=t(request, 'shop_number_or_password_is_incorrect'),
                    status_code=status.HTTP_401_UNAUTHORIZED
                )
            if not shop_owner.is_active:
                return error_response(
                    message=t(request, 'account_is_inactive'),
                    status_code=status.HTTP_401_UNAUTHORIZED
                )
            
            # إنشاء التوكن
            refresh = RefreshToken.for_user(shop_owner)
            refresh['shop_owner_id'] = shop_owner.id
            refresh['shop_number'] = shop_owner.shop_number
            refresh['shop_category_id'] = shop_owner.shop_category_id
            refresh['shop_category_name'] = shop_owner.shop_category.name if shop_owner.shop_category else None
            refresh['user_type'] = 'shop_owner'
            
            return success_response(
                data={
                    'refresh': str(refresh),
                    'access': str(refresh.access_token),
                    'user': {
                        'id': shop_owner.id,
                        'shop_number': shop_owner.shop_number,
                        'shop_name': shop_owner.shop_name,
                        'owner_name': shop_owner.owner_name,
                        'shop_category_id': shop_owner.shop_category_id,
                        'shop_category_name': shop_owner.shop_category.name if shop_owner.shop_category else None,
                    },
                    'role': 'shop_owner'
                },
                message=t(request, 'login_successful')
            )
        except ShopOwner.DoesNotExist:
            return error_response(
                message=t(request, 'shop_number_or_password_is_incorrect'),
                status_code=status.HTTP_401_UNAUTHORIZED
            )
    
    # ===== Customer Login =====
    elif role == 'customer':
        if not phone_number:
            return error_response(
                message=t(request, 'phone_number_is_required'),
                status_code=status.HTTP_400_BAD_REQUEST
            )
        
        from shop.models import Customer
        try:
            customer = Customer.objects.get(phone_number=phone_number)
            if not customer.check_password(password):
                return error_response(
                    message=t(request, 'phone_number_or_password_is_incorrect'),
                    status_code=status.HTTP_401_UNAUTHORIZED
                )
            if not customer.is_verified:
                return error_response(
                    message=t(request, 'account_is_not_verified_complete_otp_verification'),
                    status_code=status.HTTP_401_UNAUTHORIZED
                )
             
            # إنشاء التوكن
            refresh = RefreshToken()
            refresh['customer_id'] = customer.id
            refresh['phone_number'] = customer.phone_number
            refresh['user_type'] = 'customer'
            
            return success_response(
                data={
                    'refresh': str(refresh),
                    'access': str(refresh.access_token),
                    'user': {
                        'id': customer.id,
                        'name': customer.name,
                        'phone_number': customer.phone_number,
                    
                        'is_verified': customer.is_verified,
                    },
                    'role': 'customer'
                },
                message=t(request, 'login_successful')
            )
        except Customer.DoesNotExist:
            return error_response(
                message=t(request, 'phone_number_or_password_is_incorrect'),
                status_code=status.HTTP_401_UNAUTHORIZED
            )
    
    # ===== Employee Login =====
    elif role == 'employee':
        if not phone_number:
            return error_response(
                message=t(request, 'phone_number_is_required'),
                status_code=status.HTTP_400_BAD_REQUEST
            )
        
        from shop.models import Employee
        try:
            employee = Employee.objects.get(phone_number=phone_number)
            if not employee.check_password(password):
                return error_response(
                    message=t(request, 'phone_number_or_password_is_incorrect'),
                    status_code=status.HTTP_401_UNAUTHORIZED
                )
            if not employee.is_active:
                return error_response(
                    message=t(request, 'employee_account_is_blocked'),
                    status_code=status.HTTP_403_FORBIDDEN
                )
            
            # إنشاء التوكن
            refresh = RefreshToken()
            refresh['employee_id'] = employee.id
            refresh['phone_number'] = employee.phone_number
            refresh['user_type'] = 'employee'
            refresh['shop_owner_id'] = employee.shop_owner_id
            refresh['role'] = employee.role
            
            return success_response(
                data={
                    'refresh': str(refresh),
                    'access': str(refresh.access_token),
                    'user': {
                        'id': employee.id,
                        'name': employee.name,
                        'phone_number': employee.phone_number,
                        'role': employee.role,
                        'shop_owner_id': employee.shop_owner_id,
                    },
                    'role': 'employee'
                },
                message=t(request, 'login_successful')
            )
        except Employee.DoesNotExist:
            return error_response(
                message=t(request, 'phone_number_or_password_is_incorrect'),
                status_code=status.HTTP_401_UNAUTHORIZED
            )
    
    # ===== Driver Login =====
    elif role == 'driver':
        if not phone_number:
            return error_response(
                message=t(request, 'phone_number_is_required'),
                status_code=status.HTTP_400_BAD_REQUEST
            )
        
        from shop.models import Driver
        queryset = Driver.objects.filter(phone_number__in=_phone_variants(phone_number)).order_by('-updated_at')
        driver = None
        for candidate in queryset:
            if candidate.password and candidate.check_password(password):
                driver = candidate
                break

        if not driver:
            return error_response(
                message=t(request, 'phone_number_or_password_is_incorrect'),
                status_code=status.HTTP_401_UNAUTHORIZED
            )

        if not driver.is_verified:
            return error_response(
                message=t(request, 'account_is_not_verified_complete_otp_verification'),
                status_code=status.HTTP_401_UNAUTHORIZED
            )

        # إنشاء التوكن
        refresh = RefreshToken()
        active_shop_ids = list(
            driver.shops.filter(shop_drivers__status='active').values_list('id', flat=True)
        )
        primary_shop_id = active_shop_ids[0] if active_shop_ids else None
        refresh['driver_id'] = driver.id
        refresh['phone_number'] = driver.phone_number
        refresh['user_type'] = 'driver'
        refresh['shop_owner_id'] = primary_shop_id
        
        return success_response(
            data={
                'refresh': str(refresh),
                'access': str(refresh.access_token),
                'user': {
                    'id': driver.id,
                    'name': driver.name,
                    'phone_number': driver.phone_number,
                    'status': driver.status,
                    'vehicle_type': driver.vehicle_type,
                    'is_verified': driver.is_verified,
                    'shop_owner_id': primary_shop_id,
                    'active_shop_ids': active_shop_ids,
                },
                'role': 'driver'
            },
            message=t(request, 'login_successful')
        )
    
    else:
        return error_response(
            message=t(request, 'invalid_user_type_available_values_shop_owner_customer_employee_driver'),
            status_code=status.HTTP_400_BAD_REQUEST
        )


def _find_customer_by_phone(phone_number):
    """البحث عن العميل برقم الهاتف (يدعم صيغ متعددة)"""
    from shop.models import Customer
    from django.db.models import Q
    normalized = normalize_phone(phone_number)
    alternate = normalized[3:] if normalized.startswith("+20") else "0" + normalized.lstrip("+")
    return Customer.objects.filter(
        Q(phone_number=normalized) | Q(phone_number=alternate)
    ).first()


def _phone_variants(phone_number):
    """إرجاع كل الصيغ المحتملة للرقم (للبحث في DB)"""
    if not phone_number:
        return []
    normalized = normalize_phone(phone_number)
    variants = [normalized, str(phone_number).strip()]
    if normalized.startswith("+20"):
        variants.extend([normalized[3:], "0" + normalized[3:]])  # 1027... و 01027...
    return list(set(v for v in variants if v))


def _phone_variants(phone_number):
    """إرجاع كل الصيغ المحتملة للرقم (للبحث في DB)"""
    if not phone_number:
        return []
    normalized = normalize_phone(phone_number)
    variants = [normalized, str(phone_number).strip()]
    if normalized.startswith("+20"):
        variants.extend([normalized[3:], "0" + normalized[3:]])  # 1027... و 01027...
    return list(set(v for v in variants if v))


def _find_user_for_reset(role, phone_number, shop_number=None):
    """
    البحث عن المستخدم لاستعادة كلمة المرور
    Returns: (user_object, error_message) - error_message is None if found
    """
    from shop.models import Customer, Employee, Driver
    from django.db.models import Q

    variants = _phone_variants(phone_number)

    def _phone_queryset(qs, field="phone_number"):
        q = Q()
        for v in variants:
            q |= Q(**{field: v})
        return qs.filter(q)

    def _phone_match(qs, field="phone_number"):
        return _phone_queryset(qs, field).first()

    if role == "customer":
        user = _phone_match(Customer.objects.all())
        return (user, None) if user else (None, "رقم الهاتف غير مسجل")
    if role == "shop_owner":
        q = Q()
        for v in variants:
            q |= Q(phone_number=v) | Q(shop_number=v)
        user = ShopOwner.objects.filter(q).first()
        if not user:
            return None, "رقم الهاتف غير مسجل أو صاحب المحل لم يضف رقم الهاتف بعد"
        return (user, None)
    if role == "employee":
        employee_qs = Employee.objects.all()
        if shop_number:
            try:
                shop = ShopOwner.objects.get(shop_number=shop_number)
                employee_qs = employee_qs.filter(shop_owner=shop)
            except ShopOwner.DoesNotExist:
                return None, "invalid_shop_number"

        matches = list(_phone_queryset(employee_qs).distinct()[:2])
        if not matches:
            return (
                None,
                "employee_phone_number_is_not_registered_in_this_shop"
                if shop_number else
                "employee_phone_number_is_not_registered"
            )
        if len(matches) > 1 and not shop_number:
            return None, "employee_phone_number_is_linked_to_multiple_shops_use_shop_number"
        return matches[0], None
    if role == "driver":
        if not shop_number:
            return None, "رقم المحل مطلوب للسائقين"
        try:
            shop = ShopOwner.objects.get(shop_number=shop_number)
            user = _phone_match(Driver.objects.filter(shops=shop).distinct())
            return (user, None) if user else (None, "رقم الهاتف غير مسجل في هذا المحل")
        except ShopOwner.DoesNotExist:
            return None, "رقم المحل غير صحيح"
    return None, "نوع المستخدم غير صحيح"


@api_view(['POST'])
@permission_classes([AllowAny])
def unified_register_view(request):
    """
    تسجيل مستخدم جديد (حالياً للعملاء فقط)
    POST /api/auth/register/
    Body (JSON أو form-data):
    - role: customer
    - name: الاسم
    - phone_number: رقم الهاتف
    - password: كلمة المرور
    - profile_image: ملف صورة (اختياري)
    
    الخطوات:
    1) إنشاء الحساب عبر هذا الـ endpoint
    2) إرسال OTP عبر /api/auth/otp/send/ مع purpose=register
    3) التحقق عبر /api/auth/otp/verify/ مع purpose=register لتفعيل الحساب
    """
    role = request.data.get('role')
    
    if not role:
        return error_response(
            message=t(request, 'user_type_role_is_required'),
            status_code=status.HTTP_400_BAD_REQUEST
        )
    
    # ===== Customer Registration =====
    if role == 'customer':
        name = request.data.get('name')
        phone_number = request.data.get('phone_number')
        password = request.data.get('password')
        profile_image = request.FILES.get('profile_image')
        
        # التحقق من البيانات المطلوبة
        if not name:
            return error_response(message=t(request, 'name_is_required'), status_code=status.HTTP_400_BAD_REQUEST)
        if not phone_number:
            return error_response(message=t(request, 'phone_number_is_required'), status_code=status.HTTP_400_BAD_REQUEST)
        if not password:
            return error_response(message=t(request, 'password_is_required'), status_code=status.HTTP_400_BAD_REQUEST)
        if len(password) < 6:
            return error_response(message=t(request, 'password_must_be_at_least_6_characters'), status_code=status.HTTP_400_BAD_REQUEST)

        # التحقق من حالة الرقم مسبقاً
        from shop.models import Customer
        existing_customer = _find_customer_by_phone(phone_number)
        if existing_customer and existing_customer.is_verified:
            return error_response(
                message=t(request, 'phone_number_is_already_registered_and_verified'),
                status_code=status.HTTP_400_BAD_REQUEST
            )
        if existing_customer and not existing_customer.is_verified:
            return error_response(
                message=t(request, 'account_already_exists_and_is_not_verified_send_otp_then_verify_via_api_auth_otp_verify'),
                status_code=status.HTTP_400_BAD_REQUEST
            )
        
        normalized = normalize_phone(phone_number)
        customer = Customer.objects.create(
            name=name,
            phone_number=normalized,
            profile_image=profile_image,
            is_verified=False
        )
        customer.set_password(password)
        customer.save()

        profile_image_url = None
        if customer.profile_image:
            profile_image_url = request.build_absolute_uri(customer.profile_image.url)

        return success_response(
            data={
                'user': {
                    'id': customer.id,
                    'name': customer.name,
                    'phone_number': customer.phone_number,
                    'profile_image': customer.profile_image.url if customer.profile_image else None,
                    'profile_image_url': profile_image_url,
                    'is_verified': customer.is_verified,
                },
                'role': 'customer'
            },
            message=t(request, 'account_created_successfully_complete_otp_verification'),
            status_code=status.HTTP_201_CREATED
        )
    
    # ===== Shop Owner Registration =====
    elif role == 'shop_owner':
        # يمكن إضافة تسجيل صاحب محل جديد هنا إذا مطلوب
        return error_response(
            message=t(request, 'new_shop_owner_registration_is_managed_by_admin'),
            status_code=status.HTTP_400_BAD_REQUEST
        )
    
    # ===== Employee/Driver Registration =====
    elif role in ['employee', 'driver']:
        return error_response(
            message=t(request, 'registration_for_role_is_done_by_shop_owner', role=role),
            status_code=status.HTTP_400_BAD_REQUEST
        )
    
    else:
        return error_response(
            message=t(request, 'invalid_user_type_available_values_customer'),
            status_code=status.HTTP_400_BAD_REQUEST
        )


# ==================== OTP APIs (UltraMsg WhatsApp) ====================

@api_view(['POST'])
@permission_classes([AllowAny])
def send_otp_view(request):
    """
    إرسال رمز OTP إلى رقم الهاتف عبر WhatsApp (UltraMsg)
    POST /api/auth/otp/send/
    Body: {
        "phone_number": "+201012345678",
        "purpose": "login" | "register" | "reset_password",
        "role": "customer" | "shop_owner" | "employee" | "driver",  // لـ reset_password
        "shop_number": "12345"  // اختياري للموظف عند reset_password ومطلوب للسائق
    }
    """
    phone_number = request.data.get('phone_number')
    purpose = request.data.get('purpose', 'login')
    role = request.data.get('role', 'customer')
    shop_number = request.data.get('shop_number')
    if not phone_number:
        return error_response(
            message=t(request, 'phone_number_is_required'),
            status_code=status.HTTP_400_BAD_REQUEST
        )

    if purpose == 'register':
        customer = _find_customer_by_phone(phone_number)
        if not customer:
            return error_response(
                message=t(request, 'you_must_create_the_account_first_via_api_auth_register'),
                status_code=status.HTTP_400_BAD_REQUEST
            )
        if customer.is_verified:
            return error_response(
                message=t(request, 'account_is_already_verified_use_login'),
                status_code=status.HTTP_400_BAD_REQUEST
            )
    elif purpose == 'reset_password':
        user, err = _find_user_for_reset(role, phone_number, shop_number)
        if err:
            return error_response(
                message=localize_message(request, err),
                status_code=status.HTTP_404_NOT_FOUND
            )

    success, msg = otp_send(phone_number)
    if success:
        return success_response(
            message=t(request, 'verification_code_sent_to_your_whatsapp')
        )
    return error_response(
        message=localize_message(request, msg),
        status_code=status.HTTP_400_BAD_REQUEST
    )


@api_view(['POST'])
@permission_classes([AllowAny])
def verify_otp_login_view(request):
    """
    التحقق من OTP لتسجيل الدخول أو التسجيل
    POST /api/auth/otp/verify/
    Body: {
        "phone_number": "+201012345678" أو "01012345678",
        "otp": "123456",
        "purpose": "login" | "register"  // افتراضي login
    }
    """

    phone_number = request.data.get('phone_number')
    otp_code = request.data.get('otp')
    purpose = request.data.get('purpose', 'login')

    if not phone_number:
        return error_response(
            message=t(request, 'phone_number_is_required'),
            status_code=status.HTTP_400_BAD_REQUEST
        )
    if not otp_code:
        return error_response(
            message=t(request, 'verification_code_is_required'),
            status_code=status.HTTP_400_BAD_REQUEST
        )
    if purpose not in ['login', 'register']:
        return error_response(
            message=t(request, 'invalid_purpose_available_values_login_register'),
            status_code=status.HTTP_400_BAD_REQUEST
        )
    
    customer = _find_customer_by_phone(phone_number)

    if purpose == 'register':
        if not customer:
            return error_response(
                message=t(request, 'you_must_create_the_account_first_via_api_auth_register'),
                status_code=status.HTTP_400_BAD_REQUEST
            )
        if customer.is_verified:
            return error_response(
                message=t(request, 'account_is_already_verified_use_login'),
                status_code=status.HTTP_400_BAD_REQUEST
            )
    else:
        if not customer:
            return error_response(
                message=t(request, 'phone_number_is_not_registered_please_register_first'),
                status_code=status.HTTP_404_NOT_FOUND
            )
        if not customer.is_verified:
            return error_response(
                message=t(request, 'account_is_not_verified_complete_otp_verification_for_registration'),
                status_code=status.HTTP_401_UNAUTHORIZED
            )

    if not otp_verify(phone_number, otp_code):
        return error_response(
            message=t(request, 'verification_code_is_invalid_or_expired'),
            status_code=status.HTTP_401_UNAUTHORIZED
        )

    if purpose == 'register':
        customer.is_verified = True
        customer.save(update_fields=['is_verified'])

    refresh = RefreshToken()
    refresh['customer_id'] = customer.id
    refresh['phone_number'] = customer.phone_number
    refresh['user_type'] = 'customer'

    success_message = t(request, 'verification_successful') if purpose == 'register' else t(request, 'login_successful')

    return success_response(
        data={
            'refresh': str(refresh),
            'access': str(refresh.access_token),
            'user': {
                'id': customer.id,
                'name': customer.name,
                'phone_number': customer.phone_number,
        
                'is_verified': customer.is_verified,
            },
            'role': 'customer'
        },
        message=success_message
    )

# ==================== Reset Password (OTP) ====================

@api_view(['POST'])
@permission_classes([AllowAny])
def reset_password_view(request):
    """
    استعادة كلمة المرور باستخدام OTP - لجميع أنواع المستخدمين
    الخطوة 1: إرسال OTP عبر POST /api/auth/otp/send/ مع purpose=reset_password و role
    الخطوة 2: استدعاء هذا الـ endpoint
    
    POST /api/auth/password-reset/
    Body: {
        "role": "customer" | "shop_owner" | "employee" | "driver",
        "phone_number": "+201012345678",
        "shop_number": "12345",  // اختياري للموظف ومطلوب للسائق
        "otp": "123456",
        "new_password": "كلمة المرور الجديدة"
    }
    """
    role = request.data.get('role', 'customer')
    phone_number = request.data.get('phone_number')
    shop_number = request.data.get('shop_number')
    otp_code = request.data.get('otp')
    new_password = request.data.get('new_password')

    if not phone_number:
        return error_response(
            message=t(request, 'phone_number_is_required'),
            status_code=status.HTTP_400_BAD_REQUEST
        )
    if not otp_code:
        return error_response(
            message=t(request, 'verification_code_is_required'),
            status_code=status.HTTP_400_BAD_REQUEST
        )
    if not new_password:
        return error_response(
            message=t(request, 'new_password_is_required'),
            status_code=status.HTTP_400_BAD_REQUEST
        )
    if len(new_password) < 6:
        return error_response(
            message=t(request, 'password_must_be_at_least_6_characters'),
            status_code=status.HTTP_400_BAD_REQUEST
        )

    if not otp_verify(phone_number, otp_code):
        return error_response(
            message=t(request, 'verification_code_is_invalid_or_expired'),
            status_code=status.HTTP_401_UNAUTHORIZED
        )

    user, err = _find_user_for_reset(role, phone_number, shop_number)
    if err:
        return error_response(
            message=localize_message(request, err),
            status_code=status.HTTP_404_NOT_FOUND
        )

    user.set_password(new_password)
    user.save()

    return success_response(
        message=t(request, 'password_changed_successfully')
    )


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def change_password_view(request):
    """
    Change password for the currently authenticated user.
    Works with shop owner, customer, employee, and driver tokens.

    POST /api/auth/password-change/
    Body: {
        "current_password": "current password",
        "new_password": "new password",
        "confirm_password": "confirm password"
    }
    """
    user = request.user

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

    if not current_password:
        return error_response(
            message='كلمة المرور الحالية مطلوبة',
            status_code=status.HTTP_400_BAD_REQUEST,
            request=request,
        )

    if not new_password:
        return error_response(
            message=t(request, 'new_password_is_required'),
            status_code=status.HTTP_400_BAD_REQUEST,
            request=request,
        )

    if not confirm_password:
        return error_response(
            message='تأكيد كلمة المرور الجديدة مطلوب',
            status_code=status.HTTP_400_BAD_REQUEST,
            request=request,
        )

    if new_password != confirm_password:
        return error_response(
            message='كلمة المرور الجديدة وتأكيدها غير متطابقين',
            status_code=status.HTTP_400_BAD_REQUEST,
            request=request,
        )

    if len(new_password) < 6:
        return error_response(
            message=t(request, 'password_must_be_at_least_6_characters'),
            status_code=status.HTTP_400_BAD_REQUEST,
            request=request,
        )

    if not hasattr(user, 'check_password') or not hasattr(user, 'set_password'):
        return error_response(
            message='هذا الحساب لا يدعم تغيير كلمة المرور',
            status_code=status.HTTP_400_BAD_REQUEST,
            request=request,
        )

    if not user.check_password(current_password):
        return error_response(
            message='كلمة المرور الحالية غير صحيحة',
            status_code=status.HTTP_400_BAD_REQUEST,
            request=request,
        )

    user.set_password(new_password)
    user.save()

    return success_response(
        message=t(request, 'password_changed_successfully'),
        request=request,
    )
