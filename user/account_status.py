from rest_framework import status
from rest_framework.exceptions import PermissionDenied

from .utils import resolve_language, t


ACCOUNT_SUSPENDED_CODE = "account_suspended"


class SuspendedAccountError(PermissionDenied):
    status_code = status.HTTP_403_FORBIDDEN
    default_code = ACCOUNT_SUSPENDED_CODE

    def __init__(self, detail, *, reason=None):
        super().__init__(detail=detail, code=ACCOUNT_SUSPENDED_CODE)
        self.reason = reason


def _normalized_reason(reason):
    value = str(reason or "").strip()
    return value or None


def get_account_suspension_context(user, request=None, lang=None):
    if not user:
        return None

    user_type = getattr(user, "user_type", None)
    reason = None

    if user_type == "customer" or user.__class__.__name__ == "Customer":
        moderation = getattr(user, "moderation_status", None)
        if moderation and moderation.is_suspended:
            reason = _normalized_reason(getattr(moderation, "suspension_reason", None))
    elif user_type == "driver" or user.__class__.__name__ == "Driver":
        moderation = getattr(user, "moderation_status", None)
        if moderation and moderation.is_suspended:
            reason = _normalized_reason(getattr(moderation, "suspension_reason", None))
    elif user_type == "shop_owner" or user.__class__.__name__ == "ShopOwner":
        moderation = getattr(user, "moderation_status", None)
        if getattr(user, "admin_status", None) == "suspended" or (moderation and moderation.is_suspended):
            reason = _normalized_reason(
                getattr(user, "suspension_reason", None) or getattr(moderation, "suspension_reason", None)
            )
        elif hasattr(user, "is_active") and not getattr(user, "is_active", True):
            reason = _normalized_reason(getattr(user, "suspension_reason", None))
    elif user_type == "employee" or user.__class__.__name__ == "Employee":
        if hasattr(user, "is_active") and not getattr(user, "is_active", True):
            reason = None
    elif user_type == "admin_desktop" or user.__class__.__name__ == "AdminDesktopUser":
        if hasattr(user, "is_active") and not getattr(user, "is_active", True):
            reason = None

    if reason is None:
        is_suspended = False
        if user_type in {"employee", "admin_desktop"}:
            is_suspended = hasattr(user, "is_active") and not getattr(user, "is_active", True)
        elif user_type == "shop_owner" or user.__class__.__name__ == "ShopOwner":
            moderation = getattr(user, "moderation_status", None)
            is_suspended = (
                getattr(user, "admin_status", None) == "suspended"
                or not getattr(user, "is_active", True)
                or bool(moderation and moderation.is_suspended)
            )
        else:
            moderation = getattr(user, "moderation_status", None)
            is_suspended = bool(moderation and moderation.is_suspended)
        if not is_suspended:
            return None

    language = resolve_language(request=request, lang=lang)
    detail_default = (
        "تم تعطيل حسابك مؤقتًا. يرجى التواصل مع الدعم."
        if language == "ar"
        else "Your account has been suspended. Please contact support."
    )

    return {
        "code": ACCOUNT_SUSPENDED_CODE,
        "detail": t(request, "account_suspended_detail", lang=lang, default=detail_default),
        "reason": reason,
    }


def ensure_account_is_active(user, request=None, lang=None):
    suspension = get_account_suspension_context(user, request=request, lang=lang)
    if suspension:
        raise SuspendedAccountError(
            suspension["detail"],
            reason=suspension.get("reason"),
        )
    return user
