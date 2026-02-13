from django.conf import settings
from django.http import HttpResponse
from django.utils import translation
from django.utils.cache import patch_vary_headers

from .utils import DEFAULT_LANGUAGE, get_requested_language


class CorsMiddleware:
    """
    Minimal CORS middleware for API + local html testing.
    Handles preflight OPTIONS before auth/permission checks.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def _is_allowed_origin(self, origin: str) -> bool:
        if not origin:
            return False

        allow_all = getattr(settings, "CORS_ALLOW_ALL_ORIGINS", False)
        if allow_all:
            return True

        allowed_origins = set(getattr(settings, "CORS_ALLOWED_ORIGINS", []))
        if origin in allowed_origins:
            return True

        allow_null = getattr(settings, "CORS_ALLOW_NULL_ORIGIN", False)
        if allow_null and origin == "null":
            return True

        return False

    def _add_cors_headers(self, response, origin: str):
        allow_all = getattr(settings, "CORS_ALLOW_ALL_ORIGINS", False)
        allow_credentials = getattr(settings, "CORS_ALLOW_CREDENTIALS", False)

        if allow_all and not allow_credentials and origin != "null":
            response["Access-Control-Allow-Origin"] = "*"
        else:
            response["Access-Control-Allow-Origin"] = origin
            patch_vary_headers(response, ("Origin",))

        if allow_credentials:
            response["Access-Control-Allow-Credentials"] = "true"

        allow_methods = getattr(
            settings,
            "CORS_ALLOW_METHODS",
            ["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        )
        allow_headers = getattr(
            settings,
            "CORS_ALLOW_HEADERS",
            [
                "Authorization",
                "Content-Type",
                "Accept",
                "Origin",
                "X-Requested-With",
                "X-CSRFToken",
                "Accept-Language",
            ],
        )
        max_age = str(getattr(settings, "CORS_PREFLIGHT_MAX_AGE", 86400))

        response["Access-Control-Allow-Methods"] = ", ".join(allow_methods)
        response["Access-Control-Allow-Headers"] = ", ".join(allow_headers)
        response["Access-Control-Max-Age"] = max_age

    def __call__(self, request):
        origin = request.headers.get("Origin")
        is_preflight = (
            request.method == "OPTIONS"
            and bool(request.headers.get("Access-Control-Request-Method"))
        )
        origin_allowed = self._is_allowed_origin(origin)

        if is_preflight and origin_allowed:
            response = HttpResponse(status=204)
            self._add_cors_headers(response, origin)
            return response

        response = self.get_response(request)

        if origin and origin_allowed:
            self._add_cors_headers(response, origin)

        return response


class APILanguageMiddleware:
    """
    Select API language from query/header and activate it for current request.
    Supported: ar, en
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        lang = get_requested_language(request) or DEFAULT_LANGUAGE
        request.api_lang = lang
        request.LANGUAGE_CODE = lang
        translation.activate(lang)
        try:
            response = self.get_response(request)
        finally:
            translation.deactivate()
        if response is not None:
            response["Content-Language"] = lang
        return response
