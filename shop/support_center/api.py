import os
import uuid

from django.core.files.storage import default_storage
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated

from user.utils import error_response, success_response, t

from ..core.identity import resolve_customer_user, resolve_shop_owner_or_employee_owner, resolve_user_type
from ..core.permissions import IsCustomer, IsShopOwnerOrEmployee
from ..models import CustomerSupportConversation, CustomerSupportMessage, ShopSupportTicket
from ..websocket_utils import broadcast_support_chat_message, notify_support_conversation_update, notify_support_message
from .serializers import (
    CustomerSupportConversationCreateSerializer,
    CustomerSupportConversationSerializer,
    CustomerSupportMessageSerializer,
    ShopSupportTicketMessageSerializer,
)
from .service import broadcast_ticket_message, get_ticket_by_public_id, send_ticket_message


def build_support_message_payload(message, request=None, base_url=None):
    context = {'request': request, 'base_url': base_url} if request is not None or base_url else {}
    serialized = CustomerSupportMessageSerializer(message, context=context).data
    return {
        'id': serialized.get('id'),
        'thread_id': serialized.get('thread_id'),
        'support_conversation_id': serialized.get('support_conversation_id'),
        'chat_type': serialized.get('chat_type'),
        'conversation_type': serialized.get('conversation_type'),
        'conversation_type_display': serialized.get('conversation_type_display'),
        'sender_type': serialized.get('sender_type'),
        'sender_name': serialized.get('sender_name'),
        'sender_id': serialized.get('sender_id'),
        'customer_profile_image_url': serialized.get('customer_profile_image_url'),
        'message_type': serialized.get('message_type'),
        'content': serialized.get('content'),
        'is_read': serialized.get('is_read'),
        'created_at': serialized.get('created_at'),
        'audio_file_url': serialized.get('audio_file_url'),
        'image_file_url': serialized.get('image_file_url'),
        'latitude': serialized.get('latitude'),
        'longitude': serialized.get('longitude'),
    }


def build_customer_support_shop_conversation_item(conversation, request, base_url=None):
    context = {'request': request, 'base_url': base_url} if request is not None or base_url else {}
    payload = CustomerSupportConversationSerializer(conversation, context=context).data
    return {
        'shop_id': payload.get('shop_id'),
        'shop_name': payload.get('shop_name'),
        'shop_logo_url': payload.get('shop_logo_url'),
        'subtitle': payload.get('subtitle'),
        'chat': payload.get('chat'),
        'support_conversation': payload,
    }


def build_support_message_notification_payload(conversation, message, request=None, base_url=None):
    context = {'request': request, 'base_url': base_url} if request is not None or base_url else {}
    conversation_payload = CustomerSupportConversationSerializer(conversation, context=context).data
    return {
        'support_conversation_id': conversation.public_id,
        'thread_id': conversation.public_id,
        'chat_type': 'support_customer',
        'conversation_type': conversation.conversation_type,
        'message': build_support_message_payload(message, request=request, base_url=base_url),
        'conversation': conversation_payload,
        'shop_id': conversation.shop_owner_id,
        'shop_name': conversation.shop_owner.shop_name,
        'customer_id': conversation.customer_id,
        'customer_name': conversation.customer.name,
        'customer_profile_image_url': conversation_payload.get('customer_profile_image_url'),
        'customer': conversation_payload.get('customer'),
    }


def _support_sender_kwargs_for_user(user, user_type):
    sender_kwargs = {'sender_type': user_type}
    if user_type == 'customer':
        sender_kwargs['sender_customer'] = user
    elif user_type == 'shop_owner':
        sender_kwargs['sender_shop_owner'] = user
    elif user_type == 'employee':
        sender_kwargs['sender_employee'] = user
    else:
        return None
    return sender_kwargs


def _extract_media_upload_payload(request):
    image_file = request.FILES.get('image_file')
    audio_file = request.FILES.get('audio_file')
    generic_file = request.FILES.get('file')
    requested_type = str(
        request.data.get('message_type')
        or request.data.get('media_type')
        or ''
    ).strip().lower()

    if generic_file is not None:
        if image_file is not None or audio_file is not None:
            return {
                'error': error_response(
                    message=t(request, 'invalid_data'),
                    errors={'file': 'Send one file field only: file, image_file, or audio_file.'},
                    status_code=status.HTTP_400_BAD_REQUEST,
                )
            }

        inferred_type = requested_type
        if not inferred_type:
            content_type = str(getattr(generic_file, 'content_type', '') or '').lower()
            inferred_type = 'audio' if content_type.startswith('audio/') else 'image'

        if inferred_type == 'audio':
            audio_file = generic_file
        elif inferred_type == 'image':
            image_file = generic_file
        else:
            return {
                'error': error_response(
                    message=t(request, 'invalid_data'),
                    errors={'media_type': 'media_type must be image or audio when file is provided.'},
                    status_code=status.HTTP_400_BAD_REQUEST,
                )
            }

    if bool(image_file) == bool(audio_file):
        return {
            'error': error_response(
                message=t(request, 'invalid_data'),
                errors={'file': 'Send exactly one file: image_file, audio_file, or file.'},
                status_code=status.HTTP_400_BAD_REQUEST,
            )
        }

    if image_file:
        if requested_type and requested_type != 'image':
            return {
                'error': error_response(
                    message=t(request, 'invalid_data'),
                    errors={'message_type': 'message_type/media_type must be image when an image file is provided.'},
                    status_code=status.HTTP_400_BAD_REQUEST,
                )
            }
        return {'message_type': 'image', 'image_file': image_file, 'audio_file': None}

    if requested_type and requested_type != 'audio':
        return {
            'error': error_response(
                message=t(request, 'invalid_data'),
                errors={'message_type': 'message_type/media_type must be audio when an audio file is provided.'},
                status_code=status.HTTP_400_BAD_REQUEST,
            )
        }
    return {'message_type': 'audio', 'image_file': None, 'audio_file': audio_file}


def _resolve_support_center_actor_type(user):
    user_type = getattr(user, 'user_type', None)
    if user_type in {'shop_owner', 'employee', 'admin_desktop'}:
        return user_type
    return None


def _can_user_access_support_ticket(ticket, user, actor_type):
    if actor_type == 'shop_owner':
        return ticket.shop_owner_id == getattr(user, 'id', None)
    if actor_type == 'employee':
        return ticket.shop_owner_id == getattr(user, 'shop_owner_id', None)
    if actor_type == 'admin_desktop':
        has_permission = getattr(user, 'has_permission', None)
        return bool(callable(has_permission) and has_permission('support_center'))
    return False


def _store_support_ticket_media_file(request, uploaded_file, message_type):
    extension = os.path.splitext(uploaded_file.name or '')[-1] or ('.jpg' if message_type == 'image' else '.webm')
    folder = 'support_center/images' if message_type == 'image' else 'support_center/audio'
    storage_path = f'{folder}/{uuid.uuid4().hex}{extension}'
    saved_path = default_storage.save(storage_path, uploaded_file)
    return request.build_absolute_uri(default_storage.url(saved_path))


def _can_user_access_support_conversation(conversation, user, user_type):
    if user_type == 'shop_owner':
        return conversation.shop_owner_id == getattr(user, 'id', None)
    if user_type == 'employee':
        return conversation.shop_owner_id == getattr(user, 'shop_owner_id', None)
    if user_type == 'customer':
        return conversation.customer_id == getattr(user, 'id', None)
    return False


def _update_conversation_counters(conversation, message, *, preview_text):
    conversation.last_message_preview = preview_text
    conversation.last_message_at = message.created_at
    conversation.unread_for_shop_count = conversation.messages.filter(
        is_read=False,
        sender_type='customer',
    ).count()
    conversation.unread_for_customer_count = conversation.messages.filter(
        is_read=False,
    ).exclude(sender_type='customer').count()
    conversation.save(update_fields=[
        'last_message_preview',
        'last_message_at',
        'unread_for_shop_count',
        'unread_for_customer_count',
        'updated_at',
    ])


@api_view(['GET', 'POST'])
@permission_classes([IsCustomer])
def customer_support_conversations_view(request):
    customer = resolve_customer_user(request.user)
    if not customer:
        return error_response(message=t(request, 'customer_not_found'), status_code=status.HTTP_404_NOT_FOUND)

    if request.method == 'GET':
        conversations = (
            CustomerSupportConversation.objects
            .filter(customer=customer)
            .select_related('shop_owner', 'customer')
            .order_by('-updated_at', '-created_at')
        )
        serializer = CustomerSupportConversationSerializer(conversations, many=True, context={'request': request})
        return success_response(
            data={'count': len(serializer.data), 'results': serializer.data},
            message='support_conversations_retrieved_successfully',
            status_code=status.HTTP_200_OK,
            request=request,
        )

    serializer = CustomerSupportConversationCreateSerializer(
        data=request.data,
        context={'customer': customer, 'request': request},
    )
    if not serializer.is_valid():
        return error_response(
            message=t(request, 'invalid_data'),
            errors=serializer.errors,
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    conversation = serializer.save()
    initial_message = str(serializer.validated_data.get('initial_message') or '').strip()
    if initial_message:
        message = CustomerSupportMessage.objects.create(
            conversation=conversation,
            sender_type='customer',
            sender_customer=customer,
            message_type='text',
            content=initial_message,
        )
        _update_conversation_counters(conversation, message, preview_text=initial_message)
        support_payload = build_support_message_notification_payload(conversation, message, request=request)
        notify_support_message(conversation.shop_owner_id, conversation.customer_id, support_payload)

    response_serializer = CustomerSupportConversationSerializer(conversation, context={'request': request})
    notify_support_conversation_update(
        conversation.shop_owner_id,
        conversation.customer_id,
        response_serializer.data,
    )
    return success_response(
        data=response_serializer.data,
        message='تم فتح المحادثة بنجاح',
        status_code=status.HTTP_201_CREATED,
        request=request,
    )


@api_view(['GET'])
@permission_classes([IsShopOwnerOrEmployee])
def shop_support_conversations_view(request):
    shop_owner = resolve_shop_owner_or_employee_owner(request.user)
    if not shop_owner:
        return error_response(message=t(request, 'shop_not_found'), status_code=status.HTTP_404_NOT_FOUND)

    conversations = (
        CustomerSupportConversation.objects
        .filter(shop_owner=shop_owner)
        .select_related('shop_owner', 'customer')
        .order_by('-updated_at', '-created_at')
    )
    serializer = CustomerSupportConversationSerializer(conversations, many=True, context={'request': request})
    return success_response(
        data={'count': len(serializer.data), 'results': serializer.data},
        message='support_conversations_retrieved_successfully',
        status_code=status.HTTP_200_OK,
        request=request,
    )


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def support_ticket_media_upload_view(request, ticket_id):
    return _perform_support_ticket_media_upload(request, ticket_id)


def _perform_support_ticket_media_upload(request, ticket_id):
    ticket = get_ticket_by_public_id(ticket_id)
    if not isinstance(ticket, ShopSupportTicket):
        return error_response(
            message='تذكرة الدعم غير موجودة.',
            status_code=status.HTTP_404_NOT_FOUND,
        )

    user = request.user
    actor_type = _resolve_support_center_actor_type(user)
    if not actor_type or not _can_user_access_support_ticket(ticket, user, actor_type):
        return error_response(
            message='ليس لديك صلاحية للوصول إلى هذه التذكرة.',
            status_code=status.HTTP_403_FORBIDDEN,
        )

    upload_payload = _extract_media_upload_payload(request)
    if upload_payload.get('error') is not None:
        return upload_payload['error']

    message_type = upload_payload['message_type']
    media_url = _store_support_ticket_media_file(
        request,
        upload_payload['image_file'] or upload_payload['audio_file'],
        message_type,
    )
    content = str(request.data.get('content') or '').strip() or None
    metadata = request.data.get('metadata')
    if not isinstance(metadata, dict):
        metadata = {}

    message = send_ticket_message(
        ticket=ticket,
        actor_type=actor_type,
        actor=user,
        message_type=message_type,
        content=content,
        image_url=media_url if message_type == 'image' else None,
        audio_url=media_url if message_type == 'audio' else None,
        metadata=metadata,
        request=request,
    )
    broadcast_ticket_message(message, request=request)

    serialized = ShopSupportTicketMessageSerializer(message, context={'request': request}).data
    return success_response(
        data=serialized,
        message='تم إرسال الوسائط بنجاح',
        status_code=status.HTTP_201_CREATED,
    )


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def support_chat_media_upload_view(request, conversation_id):
    ticket_hint = str(request.data.get('ticket_id') or request.data.get('conversation_id') or '').strip()
    if ticket_hint.startswith('ticket_') or str(conversation_id).strip().startswith('ticket_'):
        return _perform_support_ticket_media_upload(request, ticket_hint or conversation_id)

    try:
        conversation = (
            CustomerSupportConversation.objects
            .select_related('shop_owner', 'customer')
            .get(public_id=conversation_id)
        )
    except CustomerSupportConversation.DoesNotExist:
        return error_response(
            message='محادثة الدعم غير موجودة.',
            status_code=status.HTTP_404_NOT_FOUND,
        )

    user = request.user
    user_type = resolve_user_type(user)
    if not user_type or not _can_user_access_support_conversation(conversation, user, user_type):
        return error_response(
            message='ليس لديك صلاحية للوصول إلى هذه المحادثة.',
            status_code=status.HTTP_403_FORBIDDEN,
        )

    upload_payload = _extract_media_upload_payload(request)
    if upload_payload.get('error') is not None:
        return upload_payload['error']

    image_file = upload_payload['image_file']
    audio_file = upload_payload['audio_file']
    message_type = upload_payload['message_type']
    default_preview = 'صورة' if message_type == 'image' else 'رسالة صوتية'

    sender_kwargs = _support_sender_kwargs_for_user(user, user_type)
    if not sender_kwargs:
        return error_response(
            message='ليس لديك صلاحية للإرسال في هذه المحادثة.',
            status_code=status.HTTP_403_FORBIDDEN,
        )

    content = str(request.data.get('content') or '').strip() or None
    message = CustomerSupportMessage.objects.create(
        conversation=conversation,
        message_type=message_type,
        content=content,
        audio_file=audio_file,
        image_file=image_file,
        **sender_kwargs,
    )
    _update_conversation_counters(conversation, message, preview_text=content or default_preview)

    payload = build_support_message_payload(message, request=request)
    broadcast_support_chat_message(conversation.public_id, payload)
    notify_support_message(
        conversation.shop_owner_id,
        conversation.customer_id,
        build_support_message_notification_payload(conversation, message, request=request),
    )

    serialized = CustomerSupportMessageSerializer(message, context={'request': request}).data
    return success_response(
        data=serialized,
        message='تم إرسال الوسائط بنجاح',
        status_code=status.HTTP_201_CREATED,
    )
