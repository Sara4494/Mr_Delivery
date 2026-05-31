"""
OTP delivery and verification helpers.

- Customer OTP can be delivered to email.
- Existing phone-based OTP delivery remains available for other roles via Twilio WhatsApp.
"""
import json
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


def _twilio_whatsapp_address(value: str) -> str:
    value = str(value or "").strip()
    if value.startswith("whatsapp:"):
        return value
    return f"whatsapp:{normalize_phone(value)}"


def _get_twilio_client():
    account_sid = getattr(settings, "TWILIO_ACCOUNT_SID", "").strip()
    auth_token = getattr(settings, "TWILIO_AUTH_TOKEN", "").strip()
    if not account_sid or not auth_token:
        return None, "Twilio WhatsApp settings are incomplete"

    try:
        from twilio.rest import Client
    except ImportError:
        return None, "Twilio SDK is not installed"

    return Client(account_sid, auth_token), ""


def _get_twilio_verify_service_sid() -> str:
    return getattr(settings, "TWILIO_VERIFY_SERVICE_SID", "").strip()


def send_otp_via_twilio_whatsapp(phone: str, otp: str | None = None) -> tuple[bool, str]:
    client, error_message = _get_twilio_client()
    if not client:
        return False, error_message

    verify_service_sid = _get_twilio_verify_service_sid()
    from_number = getattr(settings, "TWILIO_WHATSAPP_FROM", "").strip()
    content_sid = getattr(settings, "TWILIO_WHATSAPP_OTP_CONTENT_SID", "").strip()
    if not verify_service_sid and not from_number:
        return False, "Twilio WhatsApp sender is not configured"

    try:
        if verify_service_sid:
            client.verify.v2.services(verify_service_sid).verifications.create(
                to=_twilio_whatsapp_address(phone),
                channel="whatsapp",
            )
            return True, "تم إرسال رمز التحقق بنجاح"

        message_kwargs = {
            "from_": _twilio_whatsapp_address(from_number),
            "to": _twilio_whatsapp_address(phone),
        }
        if content_sid:
            message_kwargs["content_sid"] = content_sid
            message_kwargs["content_variables"] = json.dumps({"1": otp or ""})
        else:
            message_kwargs["body"] = (
                f"رمز التحقق الخاص بك هو: {otp or ''}\n\n"
                "صلاحية الرمز: 5 دقائق"
            )

        client.messages.create(**message_kwargs)
        return True, "تم إرسال رمز التحقق بنجاح"
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

    if is_email_target(normalized):
        otp = generate_otp()
        success, msg = send_otp_via_email(normalized, otp)
        if success:
            cache.set(get_otp_cache_key(normalized), otp, OTP_EXPIRY_SECONDS)
    else:
        verify_service_sid = _get_twilio_verify_service_sid()
        otp = None if verify_service_sid else generate_otp()
        success, msg = send_otp_via_twilio_whatsapp(normalized, otp)
        if success and otp:
            cache.set(get_otp_cache_key(normalized), otp, OTP_EXPIRY_SECONDS)

    if success:
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

    if not is_email_target(normalized):
        verify_service_sid = _get_twilio_verify_service_sid()
        if verify_service_sid:
            client, error_message = _get_twilio_client()
            if not client:
                return False
            try:
                result = client.verify.v2.services(verify_service_sid).verification_checks.create(
                    to=_twilio_whatsapp_address(normalized),
                    code=code,
                )
            except Exception:
                return False
            return getattr(result, "status", "") == "approved"

    stored = cache.get(get_otp_cache_key(normalized))
    if not stored:
        return False

    if str(stored) != code:
        return False

    cache.delete(get_otp_cache_key(normalized))
    return True
