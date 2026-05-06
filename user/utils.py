from django.utils.translation import get_language
from django.conf import settings
from rest_framework import status as http_status
from rest_framework.response import Response

from locales.ar import MESSAGES as AR_MESSAGES
from locales.en import MESSAGES as EN_MESSAGES


SUPPORTED_LANGUAGES = {"ar", "en"}
DEFAULT_LANGUAGE = "ar"

MESSAGES_BY_LANG = {
    "ar": AR_MESSAGES,
    "en": EN_MESSAGES,
}

ALL_MESSAGE_KEYS = set(AR_MESSAGES.keys()) | set(EN_MESSAGES.keys())
AR_TEXT_TO_KEY = {value: key for key, value in AR_MESSAGES.items()}
EN_TEXT_TO_KEY = {value: key for key, value in EN_MESSAGES.items()}


def _normalize_lang(raw_lang):
    if raw_lang is None:
        return None
    lang = str(raw_lang).strip().lower()
    if not lang:
        return None
    lang = lang.replace("_", "-")
    lang = lang.split(",")[0].split(";")[0].split("-")[0].strip()
    return lang if lang in SUPPORTED_LANGUAGES else None


def get_requested_language(request=None):
    """
    Resolve language from:
    1) Query param: ?lang=en|ar
    2) Headers: lang / X-Lang / X-Language / Accept-Language
    """
    if request is None:
        return None

    query_lang = None
    if hasattr(request, "query_params"):
        query_lang = request.query_params.get("lang")
    elif hasattr(request, "GET"):
        query_lang = request.GET.get("lang")

    normalized = _normalize_lang(query_lang)
    if normalized:
        return normalized

    headers = getattr(request, "headers", None)
    if headers:
        for key in ("lang", "x-lang", "x-language", "accept-language"):
            normalized = _normalize_lang(headers.get(key))
            if normalized:
                return normalized

    meta = getattr(request, "META", None) or {}
    for key in ("HTTP_LANG", "HTTP_X_LANG", "HTTP_X_LANGUAGE", "HTTP_ACCEPT_LANGUAGE"):
        normalized = _normalize_lang(meta.get(key))
        if normalized:
            return normalized

    return None


def resolve_language(request=None, lang=None):
    """
    Final language resolver. Falls back to active Django language then default.
    """
    normalized = _normalize_lang(lang)
    if normalized:
        return normalized

    request_lang = get_requested_language(request)
    if request_lang:
        return request_lang

    active_lang = _normalize_lang(get_language())
    if active_lang:
        return active_lang

    return DEFAULT_LANGUAGE


def _resolve_message_key(message):
    text = "" if message is None else str(message).strip()
    if not text:
        return None
    if text in ALL_MESSAGE_KEYS:
        return text
    if text in AR_TEXT_TO_KEY:
        return AR_TEXT_TO_KEY[text]
    if text in EN_TEXT_TO_KEY:
        return EN_TEXT_TO_KEY[text]
    return None


def t(request, key, lang=None, default=None, **kwargs):
    """
    Translate by message key.
    Example: t(request, "login_successful")
    """
    language = resolve_language(request=request, lang=lang)
    language_messages = MESSAGES_BY_LANG.get(language, AR_MESSAGES)

    if key in language_messages:
        template = language_messages[key]
    elif key in AR_MESSAGES:
        template = AR_MESSAGES[key]
    elif key in EN_MESSAGES:
        template = EN_MESSAGES[key]
    elif default is not None:
        template = str(default)
    else:
        template = str(key)

    if kwargs:
        try:
            return template.format(**kwargs)
        except Exception:
            return template
    return template


def localize_message(request, message, lang=None, **kwargs):
    """
    Accepts key or raw text and returns localized text.
    """
    key = _resolve_message_key(message)
    if key:
        return t(request, key, lang=lang, default=message, **kwargs)

    text = "" if message is None else str(message)
    if kwargs:
        try:
            return text.format(**kwargs)
        except Exception:
            return text
    return text


def build_message_fields(message, request=None, lang=None, **kwargs):
    """
    Backward-compatible helper used in pagination/WebSocket responses.
    """
    return {
        "message": localize_message(request, message, lang=lang, **kwargs),
    }


def _normalize_base_url(raw_base_url):
    value = str(raw_base_url or "").strip().rstrip("/")
    return value or None


def _scope_headers(scope=None):
    headers = {}
    for key, value in (scope or {}).get("headers", []) or []:
        try:
            headers[key.decode("latin1").lower()] = value.decode("latin1")
        except Exception:
            continue
    return headers


def resolve_base_url(request=None, scope=None, base_url=None):
    explicit_base_url = _normalize_base_url(base_url)
    if explicit_base_url:
        return explicit_base_url

    if request is not None:
        try:
            return request.build_absolute_uri("/").rstrip("/")
        except Exception:
            try:
                scheme = "https" if request.is_secure() else "http"
                return f"{scheme}://{request.get_host()}"
            except Exception:
                pass

    scope_headers = _scope_headers(scope)
    host = (scope_headers.get("x-forwarded-host") or scope_headers.get("host") or "").split(",")[0].strip()
    proto = (scope_headers.get("x-forwarded-proto") or "").split(",")[0].strip().lower()

    if not proto:
        scope_scheme = str((scope or {}).get("scheme") or "").strip().lower()
        if scope_scheme == "wss":
            proto = "https"
        elif scope_scheme == "ws":
            proto = "http"
        elif scope_scheme in {"http", "https"}:
            proto = scope_scheme

    if host:
        return f"{proto or 'http'}://{host}"

    return _normalize_base_url(getattr(settings, "PUBLIC_BASE_URL", ""))


def build_absolute_file_url(file_field_or_url, request=None, scope=None, base_url=None):
    """
    Resolve a file/url into an absolute URL.
    Falls back to the active request/scope host, and only then to
    settings.PUBLIC_BASE_URL when no request object exists,
    which is especially useful for WebSocket payloads.
    """
    if not file_field_or_url:
        return None

    try:
        file_url = file_field_or_url.url
    except Exception:
        file_url = str(file_field_or_url or "").strip()

    if not file_url:
        return None

    if file_url.startswith(("http://", "https://")):
        return file_url

    if request is not None:
        try:
            return request.build_absolute_uri(file_url)
        except Exception:
            pass

    resolved_base_url = resolve_base_url(request=request, scope=scope, base_url=base_url)
    if not resolved_base_url:
        return file_url

    normalized_path = file_url if str(file_url).startswith("/") else f"/{file_url}"
    return f"{resolved_base_url}{normalized_path}"


def resolve_customer_profile_image_url(customer, request=None, scope=None, base_url=None):
    if not customer:
        return None

    profile_image = getattr(customer, "profile_image", None)
    if profile_image:
        return build_absolute_file_url(
            profile_image,
            request=request,
            scope=scope,
            base_url=base_url,
        )

    google_image_url = str(getattr(customer, "google_profile_image_url", "") or "").strip()
    return google_image_url or None


def success_response(data=None, message="", status_code=http_status.HTTP_200_OK, request=None, lang=None):
    """
    إنشاء response ناجح
    """
    response_data = {
        "status": status_code,
        "message": localize_message(request, message, lang=lang),
        "data": data if data is not None else {},
    }
    return Response(response_data, status=status_code)


def error_response(message="", errors=None, status_code=http_status.HTTP_400_BAD_REQUEST, request=None, lang=None):
    """
    إنشاء response خطأ
    """
    response_data = {
        "status": status_code,
        "message": localize_message(request, message, lang=lang),
        "data": {},
    }
    if errors:
        response_data["errors"] = errors
    return Response(response_data, status=status_code)
