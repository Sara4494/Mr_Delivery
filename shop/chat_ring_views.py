from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated

from user.utils import error_response, success_response

from .chat_ring_service import (
    ChatRingError,
    get_chat_ring_for_user,
    start_chat_ring,
    update_chat_ring_status,
)


def _chat_ring_error_response(exc):
    return error_response(
        message=exc.message,
        errors=exc.errors or None,
        status_code=exc.status_code,
    )


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def chat_ring_start_view(request):
    try:
        _, payload = start_chat_ring(
            order_id=request.data.get('order_id'),
            chat_id=request.data.get('chat_id'),
            sender_id=request.data.get('sender_id'),
            receiver_id=request.data.get('receiver_id'),
            user=request.user,
            request=request,
        )
    except (TypeError, ValueError):
        return error_response(
            message='Invalid chat ring payload.',
            errors={'request': 'order_id, sender_id, and receiver_id must be valid integers.'},
            status_code=400,
        )
    except ChatRingError as exc:
        return _chat_ring_error_response(exc)

    return success_response(
        data=payload,
        message='Chat ring started successfully.',
        status_code=201,
    )


def _chat_ring_transition_view(request, ring_id, status_value, success_message):
    try:
        ring, _ = get_chat_ring_for_user(ring_id, request.user)
        _, payload = update_chat_ring_status(ring, status_value=status_value, actor=request.user)
    except ChatRingError as exc:
        return _chat_ring_error_response(exc)

    return success_response(
        data=payload,
        message=success_message,
        status_code=200,
    )


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def chat_ring_answered_view(request, ring_id):
    return _chat_ring_transition_view(request, ring_id, 'answered', 'Chat ring answered successfully.')


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def chat_ring_dismissed_view(request, ring_id):
    return _chat_ring_transition_view(request, ring_id, 'dismissed', 'Chat ring dismissed successfully.')


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def chat_ring_timeout_view(request, ring_id):
    return _chat_ring_transition_view(request, ring_id, 'timeout', 'Chat ring timed out successfully.')


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def chat_ring_cancel_view(request, ring_id):
    return _chat_ring_transition_view(request, ring_id, 'cancelled', 'Chat ring cancelled successfully.')
