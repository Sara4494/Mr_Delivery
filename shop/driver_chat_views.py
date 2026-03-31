import os
import uuid

from django.core.files.storage import default_storage
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes

from user.utils import error_response, success_response

from .driver_chat_service import (
    get_available_transfer_drivers,
    get_call_by_public_id,
    get_conversation_by_public_id,
    get_conversation_messages_page,
    get_resync_events,
    get_shop_snapshot,
    mark_conversation_read,
    serialize_driver_chat_driver,
    serialize_driver_chat_order,
)
from .permissions import IsShopOwnerOrEmployee
from .presence import format_utc_iso8601


def _resolve_shop_owner(user):
    user_type = getattr(user, 'user_type', None)
    if user_type == 'shop_owner':
        return user
    if user_type == 'employee':
        return getattr(user, 'shop_owner', None)
    return None


def _driver_chat_not_found(request):
    return error_response(
        message='محادثة السائق غير موجودة',
        status_code=status.HTTP_404_NOT_FOUND,
        request=request,
    )


@api_view(['GET'])
@permission_classes([IsShopOwnerOrEmployee])
def driver_chat_conversations_view(request):
    shop_owner = _resolve_shop_owner(request.user)
    if not shop_owner:
        return error_response(message='غير مصرح', status_code=status.HTTP_403_FORBIDDEN, request=request)

    snapshot = get_shop_snapshot(shop_owner, request=request)
    conversations = snapshot['conversations']
    query = str(request.query_params.get('q') or '').strip().lower()
    if query:
        filtered = []
        for conversation in conversations:
            haystacks = [
                str(conversation.get('driver', {}).get('name') or '').lower(),
                str(conversation.get('last_message_preview') or '').lower(),
            ]
            for order in conversation.get('orders', []):
                haystacks.extend([
                    str(order.get('order_number') or '').lower(),
                    str(order.get('delivery_address') or '').lower(),
                    str((order.get('customer') or {}).get('name') or '').lower(),
                ])
            if any(query in item for item in haystacks):
                filtered.append(conversation)
        conversations = filtered

    return success_response(
        data={
            'conversations': conversations,
            'count': len(conversations),
            'last_event_id': snapshot.get('last_event_id'),
        },
        message='تم استرجاع محادثات السائقين بنجاح',
        status_code=status.HTTP_200_OK,
        request=request,
    )


@api_view(['GET'])
@permission_classes([IsShopOwnerOrEmployee])
def driver_chat_messages_view(request, conversation_id):
    shop_owner = _resolve_shop_owner(request.user)
    if not shop_owner:
        return error_response(message='غير مصرح', status_code=status.HTTP_403_FORBIDDEN, request=request)

    conversation = get_conversation_by_public_id(conversation_id, shop_owner=shop_owner)
    if not conversation:
        return _driver_chat_not_found(request)

    page = get_conversation_messages_page(
        conversation,
        cursor=request.query_params.get('cursor'),
        request=request,
    )
    return success_response(
        data={
            'conversation_id': conversation.public_id,
            'messages': page['messages'],
            'next_cursor': page['next_cursor'],
        },
        message='تم استرجاع الرسائل بنجاح',
        status_code=status.HTTP_200_OK,
        request=request,
    )


@api_view(['GET'])
@permission_classes([IsShopOwnerOrEmployee])
def driver_chat_orders_view(request, conversation_id):
    shop_owner = _resolve_shop_owner(request.user)
    if not shop_owner:
        return error_response(message='غير مصرح', status_code=status.HTTP_403_FORBIDDEN, request=request)

    conversation = get_conversation_by_public_id(conversation_id, shop_owner=shop_owner)
    if not conversation:
        return _driver_chat_not_found(request)

    orders = [
        serialize_driver_chat_order(item)
        for item in conversation.orders.select_related('order', 'order__customer', 'order__driver', 'order__delivery_address').order_by('-updated_at')
    ]
    return success_response(
        data={
            'conversation_id': conversation.public_id,
            'orders': orders,
        },
        message='تم استرجاع الفواتير بنجاح',
        status_code=status.HTTP_200_OK,
        request=request,
    )


@api_view(['GET'])
@permission_classes([IsShopOwnerOrEmployee])
def driver_chat_available_transfer_drivers_view(request):
    shop_owner = _resolve_shop_owner(request.user)
    if not shop_owner:
        return error_response(message='غير مصرح', status_code=status.HTTP_403_FORBIDDEN, request=request)

    exclude_driver_id = request.query_params.get('exclude_driver_id')
    drivers = get_available_transfer_drivers(shop_owner, exclude_driver_id=exclude_driver_id)
    return success_response(
        data={
            'drivers': drivers,
            'count': len(drivers),
        },
        message='تم استرجاع السائقين المتاحين للتحويل',
        status_code=status.HTTP_200_OK,
        request=request,
    )


@api_view(['POST'])
@permission_classes([IsShopOwnerOrEmployee])
def driver_chat_voice_upload_url_view(request):
    upload_url = request.build_absolute_uri('/api/shop/driver-chats/voice/upload/')
    return success_response(
        data={
            'upload_url': upload_url,
            'method': 'POST',
            'field_name': 'file',
            'max_size_bytes': 10 * 1024 * 1024,
        },
        message='تم إنشاء رابط رفع الصوت',
        status_code=status.HTTP_200_OK,
        request=request,
    )


@api_view(['POST'])
@permission_classes([IsShopOwnerOrEmployee])
def driver_chat_voice_upload_view(request):
    uploaded_file = request.FILES.get('file')
    if not uploaded_file:
        return error_response(
            message='ملف الصوت مطلوب',
            status_code=status.HTTP_400_BAD_REQUEST,
            request=request,
        )

    extension = os.path.splitext(uploaded_file.name or '')[-1] or '.webm'
    storage_path = f"driver_chats/voice/{uuid.uuid4().hex}{extension}"
    saved_path = default_storage.save(storage_path, uploaded_file)
    audio_url = request.build_absolute_uri(default_storage.url(saved_path))
    return success_response(
        data={
            'audio_url': audio_url,
            'path': saved_path,
        },
        message='تم رفع الملف الصوتي بنجاح',
        status_code=status.HTTP_201_CREATED,
        request=request,
    )


@api_view(['POST'])
@permission_classes([IsShopOwnerOrEmployee])
def driver_chat_mark_read_view(request):
    shop_owner = _resolve_shop_owner(request.user)
    if not shop_owner:
        return error_response(message='غير مصرح', status_code=status.HTTP_403_FORBIDDEN, request=request)

    conversation = get_conversation_by_public_id(request.data.get('conversation_id'), shop_owner=shop_owner)
    if not conversation:
        return _driver_chat_not_found(request)

    mark_conversation_read(conversation, 'store')
    return success_response(
        data={
            'conversation_id': conversation.public_id,
            'unread_count': 0,
        },
        message='تم تصفير عداد الرسائل غير المقروءة',
        status_code=status.HTTP_200_OK,
        request=request,
    )


@api_view(['GET'])
@permission_classes([IsShopOwnerOrEmployee])
def driver_chat_resync_view(request):
    shop_owner = _resolve_shop_owner(request.user)
    if not shop_owner:
        return error_response(message='غير مصرح', status_code=status.HTTP_403_FORBIDDEN, request=request)

    last_event_id = request.query_params.get('last_event_id')
    events = get_resync_events(shop_owner, last_event_id)
    if events is None:
        return success_response(
            data={
                'requires_snapshot': True,
                'snapshot': get_shop_snapshot(shop_owner, request=request),
            },
            message='آخر حدث غير موجود، تم إرجاع snapshot جديد',
            status_code=status.HTTP_200_OK,
            request=request,
        )

    return success_response(
        data={
            'events': events,
            'count': len(events),
        },
        message='تمت المزامنة بنجاح',
        status_code=status.HTTP_200_OK,
        request=request,
    )


@api_view(['GET'])
@permission_classes([IsShopOwnerOrEmployee])
def driver_chat_call_detail_view(request, call_id):
    shop_owner = _resolve_shop_owner(request.user)
    if not shop_owner:
        return error_response(message='غير مصرح', status_code=status.HTTP_403_FORBIDDEN, request=request)

    call = get_call_by_public_id(call_id)
    if not call or call.conversation.shop_owner_id != shop_owner.id:
        return error_response(
            message='المكالمة غير موجودة',
            status_code=status.HTTP_404_NOT_FOUND,
            request=request,
        )

    return success_response(
        data={
            'call': {
                'call_id': call.public_id,
                'conversation_id': call.conversation.public_id,
                'driver': serialize_driver_chat_driver(call.conversation.driver, request=request),
                'status': call.status,
                'initiated_by': call.initiated_by,
                'reason': call.reason,
                'created_at': format_utc_iso8601(call.created_at),
                'answered_at': format_utc_iso8601(call.answered_at),
                'ended_at': format_utc_iso8601(call.ended_at),
                'duration_seconds': call.duration_seconds,
                'channel_name': call.channel_name,
            }
        },
        message='تم استرجاع تفاصيل المكالمة',
        status_code=status.HTTP_200_OK,
        request=request,
    )
