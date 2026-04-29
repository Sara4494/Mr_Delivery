"""
OTP delivery and verification helpers.

- Customer OTP can be delivered to email.
- Existing phone-based OTP delivery remains available for other roles.
"""
import random
import re

from django.conf import settings
from django.core.cache import cache
from django.core.mail import send_mail


OTP_EXPIRY_SECONDS = 300
OTP_RESEND_COOLDOWN = 60
OTP_LENGTH = 6


def normalize_phone(phone: str) -> str:
    if not phone:
        return ""
    phone = re.sub(r"\s+", "", str(phone))
    if phone.startswith("+"):
        return phone
    if phone.startswith("20") and len(phone) >= 12:
        return "+" + phone
    if phone.startswith("0") and len(phone) >= 10:
        return "+20" + phone[1:]
    if len(phone) >= 10:
        return "+20" + phone
    return phone


def normalize_email(email: str) -> str:
    return str(email or "").strip().lower()


def normalize_otp_target(target: str) -> str:
    value = str(target or "").strip()
    if "@" in value:
        return normalize_email(value)
    return normalize_phone(value)


def is_email_target(target: str) -> bool:
    return "@" in str(target or "").strip()


def generate_otp() -> str:
    return "".join(str(random.randint(0, 9)) for _ in range(OTP_LENGTH))


def send_otp_via_ultramsg(phone: str, otp: str) -> tuple[bool, str]:
    instance = getattr(settings, "ULTRAMSG_INSTANCE", None)
    token = getattr(settings, "ULTRAMSG_TOKEN", None)

    if not instance or not token:
        return False, "إعدادات UltraMsg غير مكتملة"

    url = f"https://api.ultramsg.com/{instance}/messages/chat"
    data = {
        "token": token,
        "to": phone,
        "body": f"رمز الدخول الخاص بك هو: {otp}\n\nصلاحية الرمز: 5 دقائق",
    }

    try:
        import requests

        response = requests.post(url, data=data, timeout=10)
        result = response.json()

        if response.status_code == 200:
            if isinstance(result, dict) and result.get("error"):
                return False, result.get("error", "فشل الإرسال")
            return True, "تم إرسال الرمز بنجاح"
        return False, str(result) if result else f"خطأ في الاتصال: {response.status_code}"
    except Exception as exc:
        return False, str(exc)


def send_otp_via_email(email: str, otp: str) -> tuple[bool, str]:
    if not settings.EMAIL_HOST_USER or not settings.EMAIL_HOST_PASSWORD:
        return False, "إعدادات البريد الإلكتروني غير مكتملة"

    try:
        send_mail(
            subject="Mr Delivery OTP Code",
            message=(
                f"Your verification code is: {otp}\n\n"
                "This code expires in 5 minutes."
            ),
            from_email=settings.DEFAULT_FROM_EMAIL or settings.EMAIL_HOST_USER,
            recipient_list=[email],
            fail_silently=False,
        )
        return True, "تم إرسال رمز التحقق إلى البريد الإلكتروني"
    except Exception as exc:
        return False, str(exc)


def get_otp_cache_key(target: str) -> str:
    return f"otp:{normalize_otp_target(target)}"


def get_otp_cooldown_key(target: str) -> str:
    return f"otp_cooldown:{normalize_otp_target(target)}"


def _get_fixed_otp_code():
    return (getattr(settings, "FIXED_OTP_CODE", None) or "").strip() or None


def send_otp(target: str, *, allow_fixed_code: bool = True) -> tuple[bool, str]:
    normalized = normalize_otp_target(target)
    if not normalized:
        return False, "بيانات الإرسال غير صالحة"

    if is_email_target(normalized):
        if "@" not in normalized:
            return False, "البريد الإلكتروني غير صالح"
    elif len(normalized) < 12:
        return False, "رقم الهاتف غير صالح"

    fixed = _get_fixed_otp_code() if allow_fixed_code else None
    if fixed:
        cache.set(get_otp_cache_key(normalized), fixed, OTP_EXPIRY_SECONDS)
        cache.set(get_otp_cooldown_key(normalized), True, OTP_RESEND_COOLDOWN)
        return True, "تم إرسال رمز التحقق بنجاح"

    if cache.get(get_otp_cooldown_key(normalized)):
        return False, "يرجى الانتظار دقيقة قبل إعادة إرسال الرمز"

    otp = generate_otp()
    if is_email_target(normalized):
        success, msg = send_otp_via_email(normalized, otp)
    else:
        success, msg = send_otp_via_ultramsg(normalized, otp)

    if success:
        cache.set(get_otp_cache_key(normalized), otp, OTP_EXPIRY_SECONDS)
        cache.set(get_otp_cooldown_key(normalized), True, OTP_RESEND_COOLDOWN)

    return success, msg


def verify_otp(target: str, otp: str, *, allow_fixed_code: bool = True) -> bool:
    normalized = normalize_otp_target(target)
    if not normalized or not otp:
        return False

    code = str(otp).strip()
    fixed = _get_fixed_otp_code() if allow_fixed_code else None
    if fixed and code == fixed:
        cache.delete(get_otp_cache_key(normalized))
        return True

    stored = cache.get(get_otp_cache_key(normalized))
    if not stored:
        return False

    if str(stored) != code:
        return False

    cache.delete(get_otp_cache_key(normalized))
    return True
