from rest_framework.exceptions import AuthenticationFailed, NotAuthenticated
from rest_framework.views import exception_handler as drf_exception_handler
from rest_framework_simplejwt.exceptions import InvalidToken

from .utils import t


def _looks_like_token_error(exc, response):
    if isinstance(exc, InvalidToken):
        return True

    response_data = response.data if isinstance(response.data, dict) else {}
    if response_data.get('code') == 'token_not_valid':
        return True

    detail = str(response_data.get('detail', '')).lower()
    exc_detail = str(getattr(exc, 'detail', '')).lower()
    text = f'{detail} {exc_detail}'
    token_markers = [
        'token',
        'expired',
        'not valid',
        'authentication credentials were not provided',
        'invalid credentials',
    ]
    return any(marker in text for marker in token_markers)


def custom_exception_handler(exc, context):
    response = drf_exception_handler(exc, context)
    if response is None:
        return None

    request = context.get('request')
    is_auth_error = isinstance(exc, (InvalidToken, AuthenticationFailed, NotAuthenticated))

    if is_auth_error and _looks_like_token_error(exc, response):
        response.data = {
            'status': response.status_code,
            'message': t(request, 'session_expired_login_again'),
            'data': {},
        }
        return response

    return response
