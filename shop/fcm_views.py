from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated

from user.utils import error_response, success_response

from .fcm_serializers import (
    FCMDeviceRefreshSerializer,
    FCMDeviceRegisterSerializer,
    FCMDeviceTokenSerializer,
    FCMDeviceUnregisterSerializer,
)
from .fcm_service import register_device_token, unregister_device_token


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def fcm_register_device_view(request):
    serializer = FCMDeviceRegisterSerializer(data=request.data)
    if not serializer.is_valid():
        return error_response(
            message='Invalid FCM registration payload.',
            errors=serializer.errors,
            status_code=status.HTTP_400_BAD_REQUEST,
            request=request,
        )

    token_record = register_device_token(
        user=request.user,
        action='register',
        **serializer.validated_data,
    )
    return success_response(
        data=FCMDeviceTokenSerializer(token_record).data,
        message='FCM device token registered successfully.',
        status_code=status.HTTP_200_OK,
        request=request,
    )


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def fcm_refresh_device_view(request):
    serializer = FCMDeviceRefreshSerializer(data=request.data)
    if not serializer.is_valid():
        return error_response(
            message='Invalid FCM refresh payload.',
            errors=serializer.errors,
            status_code=status.HTTP_400_BAD_REQUEST,
            request=request,
        )

    token_record = register_device_token(
        user=request.user,
        action='refresh',
        **serializer.validated_data,
    )
    return success_response(
        data=FCMDeviceTokenSerializer(token_record).data,
        message='FCM device token refreshed successfully.',
        status_code=status.HTTP_200_OK,
        request=request,
    )


@api_view(['DELETE'])
@permission_classes([IsAuthenticated])
def fcm_unregister_device_view(request):
    serializer = FCMDeviceUnregisterSerializer(data=request.data)
    if not serializer.is_valid():
        return error_response(
            message='Invalid FCM unregister payload.',
            errors=serializer.errors,
            status_code=status.HTTP_400_BAD_REQUEST,
            request=request,
        )

    affected = unregister_device_token(
        user=request.user,
        **serializer.validated_data,
    )
    return success_response(
        data={'deactivated_tokens': affected},
        message='FCM device token unregistered successfully.',
        status_code=status.HTTP_200_OK,
        request=request,
    )
