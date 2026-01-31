"""
خدمة إرسال وتخزين رموز OTP عبر UltraMsg (WhatsApp)
"""
import random
import re
from django.conf import settings
from django.core.cache import cache


# مدة صلاحية OTP بالثواني (5 دقائق)
OTP_EXPIRY_SECONDS = 300
# الحد الأدنى لإعادة الإرسال بالثواني (60 ثانية)
OTP_RESEND_COOLDOWN = 60
# طول الرمز
OTP_LENGTH = 6


def normalize_phone(phone: str) -> str:
    """
    تحويل رقم الهاتف إلى الصيغة الدولية (مثال: +201012345678)
    يدعم: 01012345678, 201012345678, +201012345678
    """
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


def generate_otp() -> str:
    """إنشاء رمز OTP عشوائي"""
    return "".join(str(random.randint(0, 9)) for _ in range(OTP_LENGTH))


def send_otp_via_ultramsg(phone: str, otp: str) -> tuple[bool, str]:
    """
    إرسال OTP عبر UltraMsg WhatsApp API
    Returns: (success: bool, message: str)
    """
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
    except Exception as e:
        return False, str(e)


def get_otp_cache_key(phone: str) -> str:
    return f"otp:{normalize_phone(phone)}"


def get_otp_cooldown_key(phone: str) -> str:
    return f"otp_cooldown:{normalize_phone(phone)}"


def send_otp(phone: str) -> tuple[bool, str]:
    """
    إنشاء رمز OTP، تخزينه، وإرساله عبر WhatsApp
    Returns: (success: bool, message: str)
    """
    normalized = normalize_phone(phone)
    if not normalized or len(normalized) < 12:
        return False, "رقم الهاتف غير صالح"

    if cache.get(get_otp_cooldown_key(normalized)):
        return False, "يرجى الانتظار دقيقة قبل إعادة إرسال الرمز"

    otp = generate_otp()
    success, msg = send_otp_via_ultramsg(normalized, otp)

    if success:
        cache.set(get_otp_cache_key(normalized), otp, OTP_EXPIRY_SECONDS)
        cache.set(get_otp_cooldown_key(normalized), True, OTP_RESEND_COOLDOWN)

    return success, msg


def verify_otp(phone: str, otp: str) -> bool:
    """
    التحقق من صحة رمز OTP للرقم المعطى
    """
    normalized = normalize_phone(phone)
    if not normalized or not otp:
        return False

    stored = cache.get(get_otp_cache_key(normalized))
    if not stored:
        return False

    if str(stored) != str(otp).strip():
        return False

    cache.delete(get_otp_cache_key(normalized))
    return True
