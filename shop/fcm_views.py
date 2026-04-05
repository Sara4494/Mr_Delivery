from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.exceptions import AuthenticationFailed
from rest_framework.permissions import AllowAny
from rest_framework_simplejwt.exceptions import InvalidToken

from user.utils import error_response, success_response
from user.authentication import ShopOwnerJWTAuthentication

from .fcm_serializers import (
    FCMDeviceRefreshSerializer,
    FCMDeviceRegisterSerializer,
    FCMDeviceTokenSerializer,
    FCMDeviceUnregisterSerializer,
)
from .fcm_service import register_device_token, resolve_user_identity, unregister_device_token


def _authenticate_access_token(access_token):
    authenticator = ShopOwnerJWTAuthentication()
    validated_token = authenticator.get_validated_token(access_token)
    return authenticator.get_user(validated_token)


def _resolve_authenticated_user(request, *, access_token=''):
    header_user = getattr(request, 'user', None)
    if not getattr(header_user, 'is_authenticated', False):
        header_user = None

    body_user = None
    if access_token:
        try:
            body_user = _authenticate_access_token(access_token)
        except (InvalidToken, AuthenticationFailed) as exc:
            raise AuthenticationFailed('Invalid access_token in request body.') from exc

    if header_user and body_user:
        if resolve_user_identity(header_user) != resolve_user_identity(body_user):
            raise AuthenticationFailed('Authorization header does not match access_token in request body.')
        return header_user

    if header_user:
        return header_user

    if body_user:
        return body_user

    raise AuthenticationFailed('Provide Authorization header or access_token in request body.')


def _authentication_error_response(request, exc):
    detail = getattr(exc, 'detail', None)
    if isinstance(detail, dict):
        message = detail.get('detail') or detail.get('message') or 'Authentication failed.'
    else:
        message = str(detail or exc or 'Authentication failed.')
    return error_response(
        message=message,
        status_code=status.HTTP_401_UNAUTHORIZED,
        request=request,
    )


@api_view(['POST'])
@permission_classes([AllowAny])
def fcm_register_device_view(request):
    serializer = FCMDeviceRegisterSerializer(data=request.data)
    if not serializer.is_valid():
        return error_response(
            message='Invalid FCM registration payload.',
            errors=serializer.errors,
            status_code=status.HTTP_400_BAD_REQUEST,
            request=request,
        )

    validated_data = dict(serializer.validated_data)
    access_token = validated_data.pop('access_token', '')
    try:
        user = _resolve_authenticated_user(request, access_token=access_token)
    except AuthenticationFailed as exc:
        return _authentication_error_response(request, exc)

    token_record = register_device_token(
        user=user,
        action='register',
        **validated_data,
    )
    return success_response(
        data=FCMDeviceTokenSerializer(token_record).data,
        message='FCM device token registered successfully.',
        status_code=status.HTTP_200_OK,
        request=request,
    )


@api_view(['POST'])
@permission_classes([AllowAny])
def fcm_refresh_device_view(request):
    serializer = FCMDeviceRefreshSerializer(data=request.data)
    if not serializer.is_valid():
        return error_response(
            message='Invalid FCM refresh payload.',
            errors=serializer.errors,
            status_code=status.HTTP_400_BAD_REQUEST,
            request=request,
        )

    validated_data = dict(serializer.validated_data)
    access_token = validated_data.pop('access_token', '')
    try:
        user = _resolve_authenticated_user(request, access_token=access_token)
    except AuthenticationFailed as exc:
        return _authentication_error_response(request, exc)

    token_record = register_device_token(
        user=user,
        action='refresh',
        **validated_data,
    )
    return success_response(
        data=FCMDeviceTokenSerializer(token_record).data,
        message='FCM device token refreshed successfully.',
        status_code=status.HTTP_200_OK,
        request=request,
    )


@api_view(['DELETE'])
@permission_classes([AllowAny])
def fcm_unregister_device_view(request):
    serializer = FCMDeviceUnregisterSerializer(data=request.data)
    if not serializer.is_valid():
        return error_response(
            message='Invalid FCM unregister payload.',
            errors=serializer.errors,
            status_code=status.HTTP_400_BAD_REQUEST,
            request=request,
        )

    validated_data = dict(serializer.validated_data)
    access_token = validated_data.pop('access_token', '')
    try:
        user = _resolve_authenticated_user(request, access_token=access_token)
    except AuthenticationFailed as exc:
        return _authentication_error_response(request, exc)

    affected = unregister_device_token(
        user=user,
        **validated_data,
    )
    return success_response(
        data={'deactivated_tokens': affected},
        message='FCM device token unregistered successfully.',
        status_code=status.HTTP_200_OK,
        request=request,
    )
