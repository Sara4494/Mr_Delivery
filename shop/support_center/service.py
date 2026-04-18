from collections import Counter

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from user.models import ShopOwner

from ..models import ShopSupportTicket, ShopSupportTicketMessage
from ..realtime.presence import format_utc_iso8601
from ..serializers import ShopSupportTicketMessageSerializer, ShopSupportTicketSerializer

SHOP_SUPPORT_MESSAGE_PAGE_SIZE = 50


def support_center_shop_group(shop_owner_id):
    return f'support_center_shop_{shop_owner_id}'


def support_center_admin_group():
    return 'support_center_admins'


def support_center_ticket_group(ticket_id):
    return f'support_center_ticket_{ticket_id}'


def _serializer_context(*, request=None, scope=None, base_url=None, lang=None):
    context = {}
    if request is not None:
        context['request'] = request
    if scope is not None:
        context['scope'] = scope
    if base_url:
        context['base_url'] = base_url
    if lang:
        context['lang'] = lang
    return context


def _message_preview(message):
    if message.message_type == 'image':
        return 'صورة'
    if message.message_type == 'audio':
        return 'رسالة صوتية'
    if message.message_type == 'location':
        return 'موقع'
    text = str(message.content or '').strip()
    return text[:120] if text else 'رسالة جديدة'


def _update_ticket_counters(ticket):
    ticket.unread_for_admin_count = ticket.messages.filter(
        is_read=False,
        sender_type__in=['shop_owner', 'employee'],
    ).count()
    ticket.unread_for_shop_count = ticket.messages.filter(
        is_read=False,
        sender_type='admin_desktop',
    ).count()


def _serialize_ticket(ticket, *, request=None, scope=None, base_url=None, lang=None):
    return ShopSupportTicketSerializer(
        ticket,
        context=_serializer_context(request=request, scope=scope, base_url=base_url, lang=lang),
    ).data


def _serialize_message(message, *, request=None, scope=None, base_url=None, lang=None):
    return ShopSupportTicketMessageSerializer(
        message,
        context=_serializer_context(request=request, scope=scope, base_url=base_url, lang=lang),
    ).data


def _stats_from_queryset(queryset):
    today = timezone.localdate()
    tickets = list(queryset)
    counts = Counter(ticket.status for ticket in tickets)
    waiting_support = sum(
        1 for ticket in tickets
        if ticket.status not in {'resolved', 'closed'} and (ticket.unread_for_admin_count or 0) > 0
    )
    resolved_today = sum(
        1 for ticket in tickets
        if ticket.resolved_at and timezone.localtime(ticket.resolved_at).date() == today
    )
    return {
        'total': len(tickets),
        'open': counts.get('open', 0),
        'in_progress': counts.get('in_progress', 0),
        'waiting_shop': counts.get('waiting_shop', 0),
        'waiting_support': waiting_support if waiting_support else counts.get('waiting_support', 0),
        'resolved': counts.get('resolved', 0),
        'closed': counts.get('closed', 0),
        'resolved_today': resolved_today,
    }


def get_shop_support_snapshot(shop_owner_id, *, request=None, scope=None, base_url=None, lang=None):
    tickets = list(
        ShopSupportTicket.objects
        .filter(shop_owner_id=shop_owner_id)
        .select_related('shop_owner', 'created_by_employee', 'assigned_admin')
        .order_by('-updated_at', '-created_at')
    )
    return {
        'stats': _stats_from_queryset(tickets),
        'tickets': [
            _serialize_ticket(ticket, request=request, scope=scope, base_url=base_url, lang=lang)
            for ticket in tickets
        ],
    }


def get_admin_support_snapshot(*, request=None, scope=None, base_url=None, lang=None):
    tickets = list(
        ShopSupportTicket.objects
        .select_related('shop_owner', 'created_by_employee', 'assigned_admin')
        .order_by('-updated_at', '-created_at')
    )
    return {
        'stats': _stats_from_queryset(tickets),
        'tickets': [
            _serialize_ticket(ticket, request=request, scope=scope, base_url=base_url, lang=lang)
            for ticket in tickets
        ],
    }


def get_ticket_messages(ticket_id, *, request=None, scope=None, base_url=None, lang=None):
    messages = (
        ShopSupportTicketMessage.objects
        .filter(ticket__public_id=ticket_id)
        .select_related('ticket', 'sender_shop_owner', 'sender_employee', 'sender_admin')
        .order_by('created_at')[:SHOP_SUPPORT_MESSAGE_PAGE_SIZE]
    )
    return [
        _serialize_message(message, request=request, scope=scope, base_url=base_url, lang=lang)
        for message in messages
    ]


def get_ticket_by_public_id(ticket_id):
    raw_value = str(ticket_id or '').strip()
    if not raw_value:
        return None
    queryset = ShopSupportTicket.objects.select_related('shop_owner', 'created_by_employee', 'assigned_admin')
    if raw_value.isdigit():
        return queryset.filter(Q(pk=int(raw_value)) | Q(public_id=raw_value)).first()
    if '_' in raw_value:
        tail = raw_value.rsplit('_', 1)[-1]
        if tail.isdigit():
            return queryset.filter(Q(pk=int(tail)) | Q(public_id=raw_value)).first()
    return queryset.filter(public_id=raw_value).first()


def _resolve_ticket_sender(actor_type, actor):
    sender_kwargs = {'sender_type': actor_type}
    if actor_type == 'shop_owner':
        sender_kwargs['sender_shop_owner'] = actor
    elif actor_type == 'employee':
        sender_kwargs['sender_employee'] = actor
    elif actor_type == 'admin_desktop':
        sender_kwargs['sender_admin'] = actor
    else:
        return None
    return sender_kwargs


def _auto_status_for_new_message(ticket, actor_type):
    if actor_type == 'admin_desktop':
        if ticket.status in {'open', 'waiting_support'}:
            return 'in_progress'
        return ticket.status
    if actor_type in {'shop_owner', 'employee'}:
        if ticket.status in {'resolved', 'closed'}:
            return 'open'
        if ticket.status == 'waiting_shop':
            return 'in_progress'
        return 'waiting_support'
    return ticket.status


@transaction.atomic
def create_shop_support_ticket(
    *,
    shop_owner,
    subject,
    priority='medium',
    created_by_employee=None,
    initial_message=None,
    request=None,
    scope=None,
    base_url=None,
    lang=None,
):
    if not isinstance(shop_owner, ShopOwner):
        shop_owner = ShopOwner.objects.get(id=shop_owner)

    ticket = ShopSupportTicket.objects.create(
        shop_owner=shop_owner,
        created_by_employee=created_by_employee,
        subject=subject,
        priority=priority,
        status='open',
    )
    message = None
    if initial_message:
        message = ShopSupportTicketMessage.objects.create(
            ticket=ticket,
            sender_type='employee' if created_by_employee else 'shop_owner',
            sender_shop_owner=shop_owner if created_by_employee is None else None,
            sender_employee=created_by_employee,
            message_type='text',
            content=initial_message,
        )
        ticket.last_message_preview = initial_message
        ticket.last_message_at = message.created_at
        _update_ticket_counters(ticket)
        ticket.status = 'waiting_support'
        ticket.save(
            update_fields=[
                'last_message_preview',
                'last_message_at',
                'unread_for_shop_count',
                'unread_for_admin_count',
                'status',
                'updated_at',
            ]
        )
    return ticket, message


@transaction.atomic
def send_ticket_message(
    *,
    ticket,
    actor_type,
    actor,
    message_type='text',
    content=None,
    image_url=None,
    audio_url=None,
    latitude=None,
    longitude=None,
    metadata=None,
    request=None,
    scope=None,
    base_url=None,
    lang=None,
):
    sender_kwargs = _resolve_ticket_sender(actor_type, actor)
    if not sender_kwargs:
        raise ValueError('INVALID_SENDER')

    message = ShopSupportTicketMessage.objects.create(
        ticket=ticket,
        message_type=message_type,
        content=content,
        image_url=image_url,
        audio_url=audio_url,
        latitude=latitude,
        longitude=longitude,
        metadata=metadata or {},
        **sender_kwargs,
    )

    if actor_type == 'admin_desktop' and getattr(actor, 'id', None):
        ticket.assigned_admin = actor

    ticket.last_message_preview = _message_preview(message)
    ticket.last_message_at = message.created_at
    ticket.status = _auto_status_for_new_message(ticket, actor_type)
    if ticket.status == 'resolved':
        ticket.resolved_at = timezone.now()
    else:
        ticket.resolved_at = None
        if ticket.status != 'closed':
            ticket.closed_at = None
    _update_ticket_counters(ticket)
    update_fields = [
        'assigned_admin',
        'last_message_preview',
        'last_message_at',
        'status',
        'resolved_at',
        'closed_at',
        'unread_for_shop_count',
        'unread_for_admin_count',
        'updated_at',
    ]
    ticket.save(update_fields=update_fields)
    return message


@transaction.atomic
def mark_ticket_read(ticket, actor_type):
    if actor_type == 'admin_desktop':
        updated = ticket.messages.filter(
            is_read=False,
            sender_type__in=['shop_owner', 'employee'],
        ).update(is_read=True)
    else:
        updated = ticket.messages.filter(
            is_read=False,
            sender_type='admin_desktop',
        ).update(is_read=True)

    _update_ticket_counters(ticket)
    ticket.save(update_fields=['unread_for_shop_count', 'unread_for_admin_count', 'updated_at'])
    return updated


@transaction.atomic
def update_ticket_status(ticket, *, status_value, admin_user=None):
    if status_value not in dict(ShopSupportTicket.STATUS_CHOICES):
        raise ValueError('INVALID_STATUS')

    ticket.status = status_value
    now = timezone.now()
    if status_value == 'resolved':
        ticket.resolved_at = now
        ticket.closed_at = None
    elif status_value == 'closed':
        ticket.closed_at = now
        if not ticket.resolved_at:
            ticket.resolved_at = now
    else:
        ticket.resolved_at = None
        ticket.closed_at = None

    if admin_user is not None:
        ticket.assigned_admin = admin_user

    ticket.save(update_fields=['status', 'resolved_at', 'closed_at', 'assigned_admin', 'updated_at'])
    return ticket


@transaction.atomic
def assign_ticket_admin(ticket, admin_user):
    ticket.assigned_admin = admin_user
    ticket.save(update_fields=['assigned_admin', 'updated_at'])
    return ticket


def publish_support_event(group_name, payload):
    channel_layer = get_channel_layer()
    if not channel_layer:
        return
    async_to_sync(channel_layer.group_send)(
        group_name,
        {
            'type': 'support_center_event',
            'payload': payload,
        },
    )


def broadcast_ticket_created(ticket, *, request=None, scope=None, base_url=None, lang=None):
    payload = {
        'type': 'support.ticket.created',
        'data': {
            'ticket': _serialize_ticket(ticket, request=request, scope=scope, base_url=base_url, lang=lang),
        },
        'sent_at': format_utc_iso8601(timezone.now()),
    }
    publish_support_event(support_center_shop_group(ticket.shop_owner_id), payload)
    publish_support_event(support_center_admin_group(), payload)


def broadcast_ticket_updated(ticket, *, request=None, scope=None, base_url=None, lang=None):
    payload = {
        'type': 'support.ticket.updated',
        'data': {
            'ticket': _serialize_ticket(ticket, request=request, scope=scope, base_url=base_url, lang=lang),
        },
        'sent_at': format_utc_iso8601(timezone.now()),
    }
    publish_support_event(support_center_shop_group(ticket.shop_owner_id), payload)
    publish_support_event(support_center_admin_group(), payload)
    publish_support_event(support_center_ticket_group(ticket.public_id), payload)


def broadcast_ticket_message(message, *, request=None, scope=None, base_url=None, lang=None):
    ticket = message.ticket
    payload = {
        'type': 'support.ticket.message_created',
        'data': {
            'ticket_id': ticket.public_id,
            'message': _serialize_message(message, request=request, scope=scope, base_url=base_url, lang=lang),
        },
        'sent_at': format_utc_iso8601(timezone.now()),
    }
    publish_support_event(support_center_shop_group(ticket.shop_owner_id), payload)
    publish_support_event(support_center_admin_group(), payload)
    publish_support_event(support_center_ticket_group(ticket.public_id), payload)
    broadcast_ticket_updated(ticket, request=request, scope=scope, base_url=base_url, lang=lang)


def broadcast_ticket_typing(ticket, *, actor_type, actor_name, is_typing):
    payload = {
        'type': 'support.ticket.typing',
        'data': {
            'ticket_id': ticket.public_id,
            'actor_type': actor_type,
            'actor_name': actor_name,
            'is_typing': bool(is_typing),
        },
        'sent_at': format_utc_iso8601(timezone.now()),
    }
    publish_support_event(support_center_shop_group(ticket.shop_owner_id), payload)
    publish_support_event(support_center_admin_group(), payload)
    publish_support_event(support_center_ticket_group(ticket.public_id), payload)


def serialize_ticket_thread(ticket, *, request=None, scope=None, base_url=None, lang=None):
    return {
        'ticket': _serialize_ticket(ticket, request=request, scope=scope, base_url=base_url, lang=lang),
        'messages': get_ticket_messages(ticket.public_id, request=request, scope=scope, base_url=base_url, lang=lang),
    }
