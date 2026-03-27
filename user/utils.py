from django.utils.translation import get_language
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
        "message_ar": localize_message(request, message, lang='ar', **kwargs),
        "message_en": localize_message(request, message, lang='en', **kwargs),
    }


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
