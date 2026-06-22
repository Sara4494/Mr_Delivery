from datetime import timedelta
import logging
import threading

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.db import connection, transaction
from django.db.migrations.recorder import MigrationRecorder
from django.db.utils import DatabaseError, OperationalError, ProgrammingError
from django.utils import timezone

from user.utils import build_absolute_file_url

from .fcm.service import send_push_to_user
from .models import ChatRing, Customer, Employee, Order


CHAT_RING_DURATION_SECONDS = 30
CHAT_RING_APNS_CATEGORY = 'CHAT_RING'
CHAT_RING_CHAT_TYPE = 'shop_customer'
CHAT_RING_TERMINAL_STATUSES = {'answered', 'dismissed', 'timeout', 'cancelled'}
_CHAT_RING_TIMEOUT_LOCK = threading.Lock()
_CHAT_RING_TIMEOUT_TIMERS = {}
_CHAT_RING_SCHEMA_LOCK = threading.Lock()
_CHAT_RING_SCHEMA_READY = False
logger = logging.getLogger(__name__)
CHAT_RING_STATUS_DISPLAY_MAP = {
    'ar': {
        'ringing': 'جارٍ الرن',
        'answered': 'تم الرد',
        'dismissed': 'تم الرفض',
        'timeout': 'انتهت المهلة',
        'cancelled': 'تم الإلغاء',
    },
    'en': {
        'ringing': 'Ringing',
        'answered': 'Answered',
        'dismissed': 'Dismissed',
        'timeout': 'Timed out',
        'cancelled': 'Cancelled',
    },
}


class ChatRingError(Exception):
    def __init__(self, message, *, status_code=400, errors=None):
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.errors = errors or {}


def _ensure_chat_ring_storage():
    global _CHAT_RING_SCHEMA_READY

    if _CHAT_RING_SCHEMA_READY:
        return

    table_name = ChatRing._meta.db_table
    migration_key = ('shop', '0064_chatring')
    recorder = MigrationRecorder(connection)

    with _CHAT_RING_SCHEMA_LOCK:
        if _CHAT_RING_SCHEMA_READY:
            return

        try:
            existing_tables = set(connection.introspection.table_names())
        except (DatabaseError, OperationalError, ProgrammingError) as exc:
            logger.exception('Unable to inspect ChatRing table state.')
            raise ChatRingError(
                'Chat ring storage is unavailable.',
                status_code=503,
                errors={'database': 'Unable to inspect chat ring storage.'},
            ) from exc

        migration_applied = migration_key in recorder.applied_migrations()

        if table_name in existing_tables:
            if not migration_applied:
                recorder.record_applied(*migration_key)
            _CHAT_RING_SCHEMA_READY = True
            return

        logger.warning('ChatRing table %s is missing. Creating it on demand.', table_name)
        try:
            with connection.schema_editor() as schema_editor:
                schema_editor.create_model(ChatRing)
            if not migration_applied:
                recorder.record_applied(*migration_key)
        except Exception as exc:
            logger.exception('Failed to create ChatRing table %s on demand.', table_name)
            raise ChatRingError(
                'Chat ring storage is not initialized. Please run database migrations.',
                status_code=503,
                errors={'database': f'Missing table: {table_name}.'},
            ) from exc

        _CHAT_RING_SCHEMA_READY = True


def _resolve_user_type(user):
    user_type = str(getattr(user, 'user_type', '') or '').strip()
    if user_type in {'customer', 'shop_owner', 'employee'}:
        return user_type
    return ''


def _user_avatar_url(user, user_type, *, request=None):
    if user_type == 'shop_owner':
        return build_absolute_file_url(getattr(user, 'profile_image', None), request=request)
    if user_type == 'employee':
        return build_absolute_file_url(getattr(user, 'profile_image', None), request=request)
    if user_type == 'customer':
        return (
            build_absolute_file_url(getattr(user, 'profile_image', None), request=request)
            or str(getattr(user, 'google_profile_image_url', '') or '').strip()
        )
    return ''


def _user_display_name(user, user_type):
    if user_type == 'shop_owner':
        return str(getattr(user, 'shop_name', '') or getattr(user, 'owner_name', '') or 'المحل').strip()
    return str(getattr(user, 'name', '') or 'مستخدم').strip()


def _can_access_shop_customer_chat(order, user, user_type):
    if user_type == 'customer':
        return order.customer_id == getattr(user, 'id', None)
    if user_type == 'shop_owner':
        return order.shop_owner_id == getattr(user, 'id', None)
    if user_type == 'employee':
        return order.shop_owner_id == getattr(user, 'shop_owner_id', None)
    return False


def _actor_matches_ring_side(ring, user, user_type, side):
    if side == 'sender':
        expected_type = ring.sender_type
        expected_id = ring.sender_id
    else:
        expected_type = ring.receiver_type
        expected_id = ring.receiver_id

    if user_type == 'employee' and expected_type in {'employee', 'shop_owner'}:
        return ring.order.shop_owner_id == getattr(user, 'shop_owner_id', None)
    if user_type == 'shop_owner' and expected_type in {'shop_owner', 'employee'}:
        return ring.order.shop_owner_id == getattr(user, 'id', None)
    return expected_type == user_type and expected_id == getattr(user, 'id', None)


def _resolve_receiver(order, sender_user_type, receiver_id):
    if sender_user_type in {'shop_owner', 'employee'}:
        if int(receiver_id) != int(order.customer_id):
            raise ChatRingError(
                'receiver_id must match the order customer for shop chat rings.',
                errors={'receiver_id': 'Must match order.customer_id.'},
            )
        return 'customer', int(order.customer_id)

    if sender_user_type == 'customer':
        normalized_receiver_id = int(receiver_id)
        if normalized_receiver_id == int(order.shop_owner_id):
            return 'shop_owner', normalized_receiver_id
        employee_exists = Employee.objects.filter(
            id=normalized_receiver_id,
            shop_owner_id=order.shop_owner_id,
            is_active=True,
        ).exists()
        if employee_exists:
            return 'employee', normalized_receiver_id
        raise ChatRingError(
            'receiver_id must match the shop owner or an active employee for this order.',
            errors={'receiver_id': 'Invalid shop receiver for this order.'},
        )

    raise ChatRingError('Only shop/customer chat participants can create chat rings.', status_code=403)


def _ring_payload(ring, *, event_type='chat_ring'):
    metadata = ring.metadata or {}
    payload = {
        'type': event_type,
        'ring_id': str(ring.public_id or ''),
        'chat_id': str(ring.chat_id or ''),
        'order_id': str(ring.order_id or ''),
        'sender_id': str(ring.sender_id or ''),
        'sender_name': str(metadata.get('sender_name') or ''),
        'sender_avatar': str(metadata.get('sender_avatar') or ''),
        'duration_seconds': str(CHAT_RING_DURATION_SECONDS),
        'action': 'open_chat' if event_type == 'chat_ring' else 'update_chat',
        'status': str(ring.status or ''),
        'status_display': _ring_status_display(ring.status, lang='ar'),
    }
    return payload


def _normalize_ring_lang(lang):
    normalized = str(lang or '').strip().lower()
    if not normalized:
        return 'ar'
    if normalized.startswith('en'):
        return 'en'
    return 'ar'


def _ring_status_display(status, *, lang=None):
    status_key = str(status or '').strip()
    normalized_lang = _normalize_ring_lang(lang)
    return CHAT_RING_STATUS_DISPLAY_MAP.get(normalized_lang, {}).get(status_key, status_key)


def _ring_socket_group_name(user_type, user_id, order):
    if user_type in {'shop_owner', 'employee'} and getattr(order, 'shop_owner_id', None):
        return f'shop_orders_{order.shop_owner_id}'
    if user_type == 'customer' and getattr(order, 'customer_id', None):
        return f'customer_orders_{order.customer_id}'
    if user_type == 'driver' and getattr(order, 'driver_id', None):
        return f'driver_{order.driver_id}'
    return ''


def _ring_socket_group_names(ring):
    order = ring.order
    groups = []
    for user_type, user_id in (
        (ring.sender_type, ring.sender_id),
        (ring.receiver_type, ring.receiver_id),
    ):
        group_name = _ring_socket_group_name(user_type, user_id, order)
        if group_name and group_name not in groups:
            groups.append(group_name)
    driver_group = getattr(order, 'driver_id', None)
    if driver_group:
        group_name = f'driver_{driver_group}'
        if group_name not in groups:
            groups.append(group_name)
    return groups


def _cancel_chat_ring_timeout_timer(ring_id):
    ring_key = str(ring_id or '').strip()
    if not ring_key:
        return
    with _CHAT_RING_TIMEOUT_LOCK:
        timer = _CHAT_RING_TIMEOUT_TIMERS.pop(ring_key, None)
    if timer is not None:
        timer.cancel()


def _schedule_chat_ring_timeout_timer(ring_id, expires_at):
    ring_key = str(ring_id or '').strip()
    if not ring_key or expires_at is None:
        return

    delay = max((expires_at - timezone.now()).total_seconds(), 0)

    def _timeout_ring():
        try:
            _ensure_chat_ring_storage()
            ring = (
                ChatRing.objects.select_related('order', 'order__shop_owner', 'order__customer', 'order__driver')
                .filter(public_id=ring_key)
                .first()
            )
            if not ring or ring.status != 'ringing':
                return
            if ring.expires_at and ring.expires_at > timezone.now():
                return
            try:
                update_chat_ring_status(ring, status_value='timeout', actor=None)
            except ChatRingError:
                return
        finally:
            _cancel_chat_ring_timeout_timer(ring_key)

    timer = threading.Timer(delay, _timeout_ring)
    timer.daemon = True

    with _CHAT_RING_TIMEOUT_LOCK:
        old_timer = _CHAT_RING_TIMEOUT_TIMERS.pop(ring_key, None)
        if old_timer is not None:
            old_timer.cancel()
        _CHAT_RING_TIMEOUT_TIMERS[ring_key] = timer

    timer.start()


def _broadcast_ring_status_update(ring):
    channel_layer = get_channel_layer()
    if channel_layer is None:
        return

    payload = _ring_payload(ring, event_type=f'chat_ring_{ring.status}')
    payload['status_display'] = _ring_status_display(ring.status, lang='ar')
    payload['updated_at'] = ring.updated_at.isoformat() if ring.updated_at else None
    if ring.answered_at is not None:
        payload['answered_at'] = ring.answered_at.isoformat()
    if ring.dismissed_at is not None:
        payload['dismissed_at'] = ring.dismissed_at.isoformat()
    if ring.timed_out_at is not None:
        payload['timed_out_at'] = ring.timed_out_at.isoformat()
    if ring.cancelled_at is not None:
        payload['cancelled_at'] = ring.cancelled_at.isoformat()

    for group_name in _ring_socket_group_names(ring):
        async_to_sync(channel_layer.group_send)(
            group_name,
            {
                'type': 'ring',
                'data': payload,
            },
        )


def _ring_push_profile():
    from django.conf import settings

    return {
        'channel_id': getattr(settings, 'FCM_SHOP_RING_CHANNEL_ID', 'chat_notifications'),
        'sound': getattr(settings, 'FCM_SHOP_RING_SOUND', 'chat_ring'),
        'ios_sound': 'chat_ring.caf',
        'high_priority': True,
        'ttl': f'{CHAT_RING_DURATION_SECONDS}s',
        'notification_priority': 'high',
    }


def _send_ring_event_to_user(user_type, user_id, payload, *, expires_at=None, with_sound=False):
    profile = _ring_push_profile()
    apns_expiration = None
    if expires_at is not None:
        apns_expiration = str(int(expires_at.timestamp()))

    return send_push_to_user(
        user_type=user_type,
        user_id=user_id,
        title='',
        body='',
        data=payload,
        channel_id=profile['channel_id'],
        sound=profile['sound'] if with_sound else 'default',
        ios_sound=profile['ios_sound'] if with_sound else None,
        high_priority=profile['high_priority'],
        ttl=profile['ttl'],
        notification_priority=profile['notification_priority'],
        tag=str(payload.get('ring_id') or ''),
        data_only=True,
        apns_category=CHAT_RING_APNS_CATEGORY if with_sound else None,
        apns_expiration=apns_expiration,
        apns_push_type='alert' if with_sound else 'background',
        allow_sound_with_data_only=with_sound,
    )


def serialize_chat_ring(ring):
    metadata = ring.metadata or {}
    return {
        'ring_id': ring.public_id,
        'chat_id': ring.chat_id,
        'chat_type': ring.chat_type,
        'order_id': str(ring.order_id),
        'sender_id': str(ring.sender_id),
        'sender_type': ring.sender_type,
        'receiver_id': str(ring.receiver_id),
        'receiver_type': ring.receiver_type,
        'status': ring.status,
        'duration_seconds': CHAT_RING_DURATION_SECONDS,
        'expires_at': ring.expires_at.isoformat() if ring.expires_at else None,
        'sender_name': metadata.get('sender_name') or '',
        'sender_avatar': metadata.get('sender_avatar') or '',
    }


def start_chat_ring(*, order_id, chat_id, sender_id, receiver_id, user, request=None):
    _ensure_chat_ring_storage()
    user_type = _resolve_user_type(user)
    if user_type not in {'customer', 'shop_owner', 'employee'}:
        raise ChatRingError('Authentication is required.', status_code=403)

    try:
        order = Order.objects.select_related('shop_owner', 'customer').get(id=order_id)
    except Order.DoesNotExist as exc:
        raise ChatRingError('Order not found.', status_code=404) from exc

    if not _can_access_shop_customer_chat(order, user, user_type):
        raise ChatRingError('You do not have access to this shop chat.', status_code=403)

    if str(chat_id or '').strip() == '':
        raise ChatRingError('chat_id is required.', errors={'chat_id': 'This field is required.'})

    if int(sender_id) != int(getattr(user, 'id', 0) or 0):
        raise ChatRingError(
            'sender_id must match the authenticated user.',
            status_code=403,
            errors={'sender_id': 'Authenticated user mismatch.'},
        )

    receiver_type, resolved_receiver_id = _resolve_receiver(order, user_type, receiver_id)
    now = timezone.now()
    expires_at = now + timedelta(seconds=CHAT_RING_DURATION_SECONDS)

    with transaction.atomic():
        existing_ring = (
            ChatRing.objects.select_for_update()
            .filter(
                chat_type=CHAT_RING_CHAT_TYPE,
                chat_id=str(chat_id).strip(),
                receiver_type=receiver_type,
                receiver_id=resolved_receiver_id,
                status='ringing',
                expires_at__gt=now,
            )
            .order_by('-created_at')
            .first()
        )
        if existing_ring is not None:
            raise ChatRingError(
                'An active ring already exists for this receiver in the same chat.',
                status_code=409,
                errors={'receiver_id': 'Duplicate active ring.'},
            )

        ring = ChatRing.objects.create(
            order=order,
            chat_type=CHAT_RING_CHAT_TYPE,
            chat_id=str(chat_id).strip(),
            sender_type=user_type,
            sender_id=int(sender_id),
            receiver_type=receiver_type,
            receiver_id=resolved_receiver_id,
            status='ringing',
            expires_at=expires_at,
            metadata={
                'sender_name': _user_display_name(user, user_type),
                'sender_avatar': _user_avatar_url(user, user_type, request=request),
            },
        )

    push_summary = _send_ring_event_to_user(
        receiver_type,
        resolved_receiver_id,
        _ring_payload(ring, event_type='chat_ring'),
        expires_at=expires_at,
        with_sound=True,
    )
    transaction.on_commit(lambda: _schedule_chat_ring_timeout_timer(ring.public_id, expires_at))
    response = serialize_chat_ring(ring)
    response['push'] = push_summary
    return ring, response


def get_chat_ring_for_user(ring_id, user):
    _ensure_chat_ring_storage()
    user_type = _resolve_user_type(user)
    ring = (
        ChatRing.objects.select_related('order', 'order__shop_owner', 'order__customer')
        .filter(public_id=ring_id)
        .first()
    )
    if ring is None:
        raise ChatRingError('Chat ring not found.', status_code=404)
    if not _can_access_shop_customer_chat(ring.order, user, user_type):
        raise ChatRingError('You do not have access to this chat ring.', status_code=403)
    return ring, user_type


def update_chat_ring_status(ring, *, status_value, actor=None):
    _ensure_chat_ring_storage()
    if status_value not in {'answered', 'dismissed', 'timeout', 'cancelled'}:
        raise ChatRingError('Unsupported chat ring status transition.')

    if ring.status == status_value:
        if ring.status in CHAT_RING_TERMINAL_STATUSES:
            _cancel_chat_ring_timeout_timer(ring.public_id)
        return ring, serialize_chat_ring(ring)
    if ring.status in CHAT_RING_TERMINAL_STATUSES:
        _cancel_chat_ring_timeout_timer(ring.public_id)
        return ring, serialize_chat_ring(ring)

    now = timezone.now()
    update_fields = ['status', 'updated_at']
    ring.status = status_value
    if status_value == 'answered':
        ring.answered_at = now
        update_fields.append('answered_at')
    elif status_value == 'dismissed':
        ring.dismissed_at = now
        update_fields.append('dismissed_at')
    elif status_value == 'timeout':
        ring.timed_out_at = now
        update_fields.append('timed_out_at')
    elif status_value == 'cancelled':
        ring.cancelled_at = now
        update_fields.append('cancelled_at')

    actor_type = _resolve_user_type(actor) if actor is not None else ''

    with transaction.atomic():
        ring.save(update_fields=update_fields)
        if status_value in CHAT_RING_TERMINAL_STATUSES:
            _cancel_chat_ring_timeout_timer(ring.public_id)

        def _dispatch_updates():
            _broadcast_ring_status_update(ring)
            payload = _ring_payload(ring, event_type=f'chat_ring_{status_value}')
            for user_type, user_id in {
                (ring.sender_type, ring.sender_id),
                (ring.receiver_type, ring.receiver_id),
            }:
                _send_ring_event_to_user(user_type, user_id, payload)

        transaction.on_commit(_dispatch_updates)

    response = serialize_chat_ring(ring)
    if actor_type:
        response['acted_by'] = actor_type
    return ring, response


def _chat_ring_actor_can_transition(ring, actor, status_value):
    if actor is None:
        return True
    user_type = _resolve_user_type(actor)
    if not user_type:
        return False
    if status_value in {'answered', 'dismissed'}:
        return _actor_matches_ring_side(ring, actor, user_type, 'receiver')
    if status_value == 'cancelled':
        return _actor_matches_ring_side(ring, actor, user_type, 'sender')
    return (
        _actor_matches_ring_side(ring, actor, user_type, 'sender')
        or _actor_matches_ring_side(ring, actor, user_type, 'receiver')
    )


def apply_chat_ring_status_update(*, ring_id, actor, status_value, lang=None):
    _ensure_chat_ring_storage()
    ring = (
        ChatRing.objects.select_related('order', 'order__shop_owner', 'order__customer', 'order__driver')
        .filter(public_id=str(ring_id or '').strip())
        .first()
    )
    if ring is None:
        raise ChatRingError('Chat ring not found.', status_code=404)

    now = timezone.now()
    if ring.status == 'ringing' and ring.expires_at and ring.expires_at <= now:
        ring, _ = update_chat_ring_status(ring, status_value='timeout', actor=None)

    if ring.status in CHAT_RING_TERMINAL_STATUSES:
        if ring.status == status_value:
            return ring, {
                'ack': {
                    'ring_id': ring.public_id,
                    'status': ring.status,
                    'status_display': _ring_status_display(ring.status, lang=lang),
                },
                'ring': {
                    **_ring_payload(ring, event_type='ring'),
                    'updated_at': ring.updated_at.isoformat() if ring.updated_at else None,
                },
                'status_changed': False,
            }
        if ring.status != status_value:
            return ring, {
                'ack': {
                    'ring_id': ring.public_id,
                    'status': ring.status,
                    'status_display': _ring_status_display(ring.status, lang=lang),
                },
                'ring': {
                    **_ring_payload(ring, event_type='ring'),
                    'updated_at': ring.updated_at.isoformat() if ring.updated_at else None,
                },
                'status_changed': False,
            }

    if not _chat_ring_actor_can_transition(ring, actor, status_value):
        raise ChatRingError('You do not have permission to update this ring.', status_code=403)

    ring, payload = update_chat_ring_status(ring, status_value=status_value, actor=actor)
    return ring, {
        'ack': {
            'ring_id': ring.public_id,
            'status': ring.status,
            'status_display': _ring_status_display(ring.status, lang=lang),
        },
        'ring': {
            **_ring_payload(ring, event_type='ring'),
            'updated_at': ring.updated_at.isoformat() if ring.updated_at else None,
        },
        'status_changed': True,
        'payload': payload,
    }
