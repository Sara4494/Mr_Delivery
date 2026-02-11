from django.utils import translation

from .utils import DEFAULT_LANGUAGE, get_requested_language


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
