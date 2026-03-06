from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView
from rest_framework_simplejwt.tokens import RefreshToken
from .token_serializers import ShopOwnerTokenObtainPairSerializer
from .models import ShopOwner
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
        try:
            driver = Driver.objects.get(phone_number=phone_number)
            if not driver.check_password(password):
                return error_response(
                    message=t(request, 'phone_number_or_password_is_incorrect'),
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
                        'shop_owner_id': primary_shop_id,
                        'active_shop_ids': active_shop_ids,
                    },
                    'role': 'driver'
                },
                message=t(request, 'login_successful')
            )
        except Driver.DoesNotExist:
            return error_response(
                message=t(request, 'phone_number_or_password_is_incorrect'),
                status_code=status.HTTP_401_UNAUTHORIZED
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

    def _phone_match(qs, field="phone_number"):
        q = Q()
        for v in variants:
            q |= Q(**{field: v})
        return qs.filter(q).first()

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
        if not shop_number:
            return None, "رقم المحل مطلوب للموظفين"
        try:
            shop = ShopOwner.objects.get(shop_number=shop_number)
            user = _phone_match(Employee.objects.filter(shop_owner=shop))
            return (user, None) if user else (None, "رقم الهاتف غير مسجل في هذا المحل")
        except ShopOwner.DoesNotExist:
            return None, "رقم المحل غير صحيح"
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
        "shop_number": "12345"  // مطلوب لـ employee و driver عند reset_password
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
        "shop_number": "12345",  // مطلوب لـ employee و driver
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
