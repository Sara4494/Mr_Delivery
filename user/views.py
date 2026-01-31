from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView
from rest_framework_simplejwt.tokens import RefreshToken
from .token_serializers import ShopOwnerTokenObtainPairSerializer
from .models import ShopOwner
from .utils import success_response, error_response
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
                message='فشل تسجيل الدخول',
                errors=errors,
                status_code=status.HTTP_400_BAD_REQUEST
            )
        
        return success_response(
            data=serializer.validated_data,
            message='تم تسجيل الدخول بنجاح',
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
                message='فشل تحديث Token',
                errors=errors,
                status_code=status.HTTP_400_BAD_REQUEST
            )
        
        return success_response(
            data=serializer.validated_data,
            message='تم تحديث Token بنجاح',
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
            message='يجب تحديد نوع المستخدم (role)',
            status_code=status.HTTP_400_BAD_REQUEST
        )
    
    if not password:
        return error_response(
            message='كلمة المرور مطلوبة',
            status_code=status.HTTP_400_BAD_REQUEST
        )
    
    # ===== Shop Owner Login =====
    if role == 'shop_owner':
        if not shop_number:
            return error_response(
                message='رقم المحل مطلوب',
                status_code=status.HTTP_400_BAD_REQUEST
            )
        
        try:
            shop_owner = ShopOwner.objects.get(shop_number=shop_number)
            if not shop_owner.check_password(password):
                return error_response(
                    message='رقم المحل أو كلمة المرور غير صحيحة',
                    status_code=status.HTTP_401_UNAUTHORIZED
                )
            if not shop_owner.is_active:
                return error_response(
                    message='الحساب غير نشط',
                    status_code=status.HTTP_401_UNAUTHORIZED
                )
            
            # إنشاء التوكن
            refresh = RefreshToken.for_user(shop_owner)
            refresh['shop_owner_id'] = shop_owner.id
            refresh['shop_number'] = shop_owner.shop_number
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
                    },
                    'role': 'shop_owner'
                },
                message='تم تسجيل الدخول بنجاح'
            )
        except ShopOwner.DoesNotExist:
            return error_response(
                message='رقم المحل أو كلمة المرور غير صحيحة',
                status_code=status.HTTP_401_UNAUTHORIZED
            )
    
    # ===== Customer Login =====
    elif role == 'customer':
        if not phone_number:
            return error_response(
                message='رقم الهاتف مطلوب',
                status_code=status.HTTP_400_BAD_REQUEST
            )
        
        from shop.models import Customer
        try:
            customer = Customer.objects.get(phone_number=phone_number)
            if not customer.check_password(password):
                return error_response(
                    message='رقم الهاتف أو كلمة المرور غير صحيحة',
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
                        'email': customer.email,
                        'is_verified': customer.is_verified,
                    },
                    'role': 'customer'
                },
                message='تم تسجيل الدخول بنجاح'
            )
        except Customer.DoesNotExist:
            return error_response(
                message='رقم الهاتف أو كلمة المرور غير صحيحة',
                status_code=status.HTTP_401_UNAUTHORIZED
            )
    
    # ===== Employee Login =====
    elif role == 'employee':
        if not phone_number:
            return error_response(
                message='رقم الهاتف مطلوب',
                status_code=status.HTTP_400_BAD_REQUEST
            )
        
        from shop.models import Employee
        try:
            employee = Employee.objects.get(phone_number=phone_number)
            if not employee.check_password(password):
                return error_response(
                    message='رقم الهاتف أو كلمة المرور غير صحيحة',
                    status_code=status.HTTP_401_UNAUTHORIZED
                )
            if not employee.is_active:
                return error_response(
                    message='الحساب غير نشط',
                    status_code=status.HTTP_401_UNAUTHORIZED
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
                message='تم تسجيل الدخول بنجاح'
            )
        except Employee.DoesNotExist:
            return error_response(
                message='رقم الهاتف أو كلمة المرور غير صحيحة',
                status_code=status.HTTP_401_UNAUTHORIZED
            )
    
    # ===== Driver Login =====
    elif role == 'driver':
        if not phone_number:
            return error_response(
                message='رقم الهاتف مطلوب',
                status_code=status.HTTP_400_BAD_REQUEST
            )
        
        from shop.models import Driver
        try:
            driver = Driver.objects.get(phone_number=phone_number)
            if not driver.check_password(password):
                return error_response(
                    message='رقم الهاتف أو كلمة المرور غير صحيحة',
                    status_code=status.HTTP_401_UNAUTHORIZED
                )
            
            # إنشاء التوكن
            refresh = RefreshToken()
            refresh['driver_id'] = driver.id
            refresh['phone_number'] = driver.phone_number
            refresh['user_type'] = 'driver'
            refresh['shop_owner_id'] = driver.shop_owner_id
            
            return success_response(
                data={
                    'refresh': str(refresh),
                    'access': str(refresh.access_token),
                    'user': {
                        'id': driver.id,
                        'name': driver.name,
                        'phone_number': driver.phone_number,
                        'status': driver.status,
                        'shop_owner_id': driver.shop_owner_id,
                    },
                    'role': 'driver'
                },
                message='تم تسجيل الدخول بنجاح'
            )
        except Driver.DoesNotExist:
            return error_response(
                message='رقم الهاتف أو كلمة المرور غير صحيحة',
                status_code=status.HTTP_401_UNAUTHORIZED
            )
    
    else:
        return error_response(
            message='نوع المستخدم غير صحيح. القيم المتاحة: shop_owner, customer, employee, driver',
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


def _find_user_for_reset(role, phone_number, shop_number=None):
    """
    البحث عن المستخدم لاستعادة كلمة المرور
    Returns: (user_object, error_message) - error_message is None if found
    """
    from shop.models import Customer, Employee, Driver
    normalized = normalize_phone(phone_number)
    alternate = normalized[3:] if normalized.startswith("+20") else "0" + normalized.lstrip("+")

    def _phone_match(qs, field="phone_number"):
        from django.db.models import Q
        return qs.filter(Q(**{field: normalized}) | Q(**{field: alternate})).first()

    if role == "customer":
        user = _phone_match(Customer.objects.all())
        return (user, None) if user else (None, "رقم الهاتف غير مسجل")
    if role == "shop_owner":
        from django.db.models import Q
        user = ShopOwner.objects.filter(
            Q(phone_number=normalized) | Q(phone_number=alternate)
        ).first()
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
            user = _phone_match(Driver.objects.filter(shop_owner=shop))
            return (user, None) if user else (None, "رقم الهاتف غير مسجل في هذا المحل")
        except ShopOwner.DoesNotExist:
            return None, "رقم المحل غير صحيح"
    return None, "نوع المستخدم غير صحيح"


@api_view(['POST'])
@permission_classes([AllowAny])
def unified_register_view(request):
    """
    تسجيل مستخدم جديد (حالياً للعملاء فقط) مع التحقق من OTP
    POST /api/auth/register/
    Body: {
        "role": "customer",
        "name": "الاسم",
        "phone_number": "رقم الهاتف",
        "otp": "رمز التحقق (مطلوب - يُرسل عبر واتساب)",
        "email": "البريد الإلكتروني (اختياري)",
        "password": "كلمة المرور"
    }
    
    الخطوات: 1) إرسال OTP عبر /api/auth/otp/send/  2) إكمال التسجيل هنا مع الرمز
    """
    role = request.data.get('role')
    
    if not role:
        return error_response(
            message='يجب تحديد نوع المستخدم (role)',
            status_code=status.HTTP_400_BAD_REQUEST
        )
    
    # ===== Customer Registration =====
    if role == 'customer':
        name = request.data.get('name')
        phone_number = request.data.get('phone_number')
        otp_code = request.data.get('otp')
        email = request.data.get('email', '')
        password = request.data.get('password')
        
        # التحقق من البيانات المطلوبة
        if not name:
            return error_response(message='الاسم مطلوب', status_code=status.HTTP_400_BAD_REQUEST)
        if not phone_number:
            return error_response(message='رقم الهاتف مطلوب', status_code=status.HTTP_400_BAD_REQUEST)
        if not otp_code:
            return error_response(
                message='رمز التحقق مطلوب. استخدم /api/auth/otp/send/ أولاً',
                status_code=status.HTTP_400_BAD_REQUEST
            )
        if not password:
            return error_response(message='كلمة المرور مطلوبة', status_code=status.HTTP_400_BAD_REQUEST)
        if len(password) < 6:
            return error_response(message='كلمة المرور يجب أن تكون 6 أحرف على الأقل', status_code=status.HTTP_400_BAD_REQUEST)
        
        # التحقق من OTP أولاً
        if not otp_verify(phone_number, otp_code):
            return error_response(
                message='رمز التحقق غير صحيح أو منتهي الصلاحية',
                status_code=status.HTTP_400_BAD_REQUEST
            )
        
        # التحقق من عدم وجود الرقم مسبقاً
        from shop.models import Customer
        customer = _find_customer_by_phone(phone_number)
        if customer:
            return error_response(
                message='رقم الهاتف مسجل مسبقاً',
                status_code=status.HTTP_400_BAD_REQUEST
            )
        
        normalized = normalize_phone(phone_number)
        customer = Customer.objects.create(
            name=name,
            phone_number=normalized,
            email=email,
            is_verified=True  # تم التحقق عبر OTP
        )
        customer.set_password(password)
        customer.save()
        
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
                    'email': customer.email,
                    'is_verified': customer.is_verified,
                },
                'role': 'customer'
            },
            message='تم إنشاء الحساب بنجاح',
            status_code=status.HTTP_201_CREATED
        )
    
    # ===== Shop Owner Registration =====
    elif role == 'shop_owner':
        # يمكن إضافة تسجيل صاحب محل جديد هنا إذا مطلوب
        return error_response(
            message='تسجيل صاحب محل جديد يتم من خلال الإدارة',
            status_code=status.HTTP_400_BAD_REQUEST
        )
    
    # ===== Employee/Driver Registration =====
    elif role in ['employee', 'driver']:
        return error_response(
            message=f'تسجيل {role} يتم بواسطة صاحب المحل',
            status_code=status.HTTP_400_BAD_REQUEST
        )
    
    else:
        return error_response(
            message='نوع المستخدم غير صحيح. القيم المتاحة: customer',
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
            message='رقم الهاتف مطلوب',
            status_code=status.HTTP_400_BAD_REQUEST
        )

    if purpose == 'register':
        if _find_customer_by_phone(phone_number):
            return error_response(
                message='رقم الهاتف مسجل مسبقاً. استخدم تسجيل الدخول',
                status_code=status.HTTP_400_BAD_REQUEST
            )
    elif purpose == 'reset_password':
        user, err = _find_user_for_reset(role, phone_number, shop_number)
        if err:
            return error_response(
                message=err,
                status_code=status.HTTP_404_NOT_FOUND
            )

    success, msg = otp_send(phone_number)
    if success:
        return success_response(
            message='تم إرسال رمز التحقق إلى واتساب الخاص بك'
        )
    return error_response(
        message=msg,
        status_code=status.HTTP_400_BAD_REQUEST
    )


@api_view(['POST'])
@permission_classes([AllowAny])
def verify_otp_login_view(request):
    """
    تسجيل دخول العملاء باستخدام OTP (بدون كلمة مرور)
    POST /api/auth/otp/verify/
    Body: {
        "phone_number": "+201012345678" أو "01012345678",
        "otp": "123456"
    }
    """
    phone_number = request.data.get('phone_number')
    otp_code = request.data.get('otp')

    if not phone_number:
        return error_response(
            message='رقم الهاتف مطلوب',
            status_code=status.HTTP_400_BAD_REQUEST
        )
    if not otp_code:
        return error_response(
            message='رمز التحقق مطلوب',
            status_code=status.HTTP_400_BAD_REQUEST
        )

    if not otp_verify(phone_number, otp_code):
        return error_response(
            message='رمز التحقق غير صحيح أو منتهي الصلاحية',
            status_code=status.HTTP_401_UNAUTHORIZED
        )

    customer = _find_customer_by_phone(phone_number)
    if not customer:
        return error_response(
            message='رقم الهاتف غير مسجل. يرجى التسجيل أولاً',
            status_code=status.HTTP_404_NOT_FOUND
        )

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
                'email': customer.email,
                'is_verified': customer.is_verified,
            },
            'role': 'customer'
        },
        message='تم تسجيل الدخول بنجاح'
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
            message='رقم الهاتف مطلوب',
            status_code=status.HTTP_400_BAD_REQUEST
        )
    if not otp_code:
        return error_response(
            message='رمز التحقق مطلوب',
            status_code=status.HTTP_400_BAD_REQUEST
        )
    if not new_password:
        return error_response(
            message='كلمة المرور الجديدة مطلوبة',
            status_code=status.HTTP_400_BAD_REQUEST
        )
    if len(new_password) < 6:
        return error_response(
            message='كلمة المرور يجب أن تكون 6 أحرف على الأقل',
            status_code=status.HTTP_400_BAD_REQUEST
        )

    if not otp_verify(phone_number, otp_code):
        return error_response(
            message='رمز التحقق غير صحيح أو منتهي الصلاحية',
            status_code=status.HTTP_401_UNAUTHORIZED
        )

    user, err = _find_user_for_reset(role, phone_number, shop_number)
    if err:
        return error_response(
            message=err,
            status_code=status.HTTP_404_NOT_FOUND
        )

    user.set_password(new_password)
    user.save()

    return success_response(
        message='تم تغيير كلمة المرور بنجاح'
    )
