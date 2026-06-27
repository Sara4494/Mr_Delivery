from datetime import timedelta
from datetime import timezone as dt_timezone
import json
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
from .models import ChatRing, Customer, CustomerPresenceConnection, DriverPresenceConnection, Employee, Order


CHAT_RING_DURATION_SECONDS = 30
CHAT_RING_APNS_CATEGORY = 'CHAT_RING'
CHAT_RING_TERMINAL_STATUSES = {'answered', 'dismissed', 'timeout', 'cancelled'}
CHAT_RING_CHAT_TYPE_CHOICES = {
    'shop_customer',
    'customer_shop',
    'driver_customer',
    'customer_driver',
    'shop_driver',
    'driver_shop',
}
_CHAT_RING_TIMEOUT_LOCK = threading.Lock()
_CHAT_RING_TIMEOUT_TIMERS = {}
_CHAT_RING_SCHEMA_LOCK = threading.Lock()
_CHAT_RING_SCHEMA_READY = False
logger = logging.getLogger(__name__)


def _format_local_iso8601(value):
    if not value:
        return None
    if timezone.is_naive(value):
        value = timezone.make_aware(value, dt_timezone.utc)
    return timezone.localtime(value).replace(microsecond=0).isoformat()


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


CHAT_RING_PUBLIC_STATUS_ALIASES = {
    'accepted': 'accepted',
    'answered': 'accepted',
    'rejected': 'rejected',
    'dismissed': 'rejected',
    'timeout': 'timeout',
    'missed': 'missed',
    'cancelled': 'cancelled',
    'ended': 'ended',
}

CHAT_RING_INTERNAL_STATUS_ALIASES = {
    'accepted': 'answered',
    'answered': 'answered',
    'rejected': 'dismissed',
    'dismissed': 'dismissed',
    'timeout': 'timeout',
    'missed': 'timeout',
    'cancelled': 'cancelled',
    'ended': 'cancelled',
}

CHAT_RING_PUBLIC_STATUS_DISPLAY_MAP = {
    'ar': {
        'accepted': 'تم القبول',
        'rejected': 'تم الرفض',
        'missed': 'فاتت المكالمة',
        'ended': 'تم الإنهاء',
    },
    'en': {
        'accepted': 'Accepted',
        'rejected': 'Rejected',
        'missed': 'Missed',
        'ended': 'Ended',
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
    if user_type in {'customer', 'shop_owner', 'employee', 'driver'}:
        return user_type
    return ''


def _normalize_chat_type(chat_type):
    chat_type = str(chat_type or '').strip()
    return {
        'customer_shop': 'shop_customer',
        'customer_driver': 'driver_customer',
        'driver_shop': 'shop_driver',
    }.get(chat_type, chat_type)


def _user_avatar_url(user, user_type, *, request=None):
    if user_type == 'shop_owner':
        return build_absolute_file_url(getattr(user, 'profile_image', None), request=request)
    if user_type == 'employee':
        return build_absolute_file_url(getattr(user, 'profile_image', None), request=request)
    if user_type == 'driver':
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


def _can_access_shop_customer_chat(order, user, user_type, chat_type='shop_customer'):
    chat_type = _normalize_chat_type(chat_type)
    if chat_type == 'driver_customer':
        if user_type == 'customer':
            return order.customer_id == getattr(user, 'id', None)
        if user_type == 'driver':
            return order.driver_id == getattr(user, 'id', None)
        return False
    if chat_type == 'shop_driver':
        if user_type == 'shop_owner':
            return order.shop_owner_id == getattr(user, 'id', None)
        if user_type == 'employee':
            return order.shop_owner_id == getattr(user, 'shop_owner_id', None)
        if user_type == 'driver':
            return order.driver_id == getattr(user, 'id', None)
        return False
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


def _resolve_receiver(order, sender_user_type, receiver_id, *, chat_type='shop_customer'):
    chat_type = _normalize_chat_type(chat_type)
    if chat_type == 'driver_customer':
        normalized_receiver_id = int(receiver_id)
        if sender_user_type == 'customer' and normalized_receiver_id == int(order.driver_id or 0):
            return 'driver', normalized_receiver_id
        if sender_user_type == 'driver' and normalized_receiver_id == int(order.customer_id or 0):
            return 'customer', normalized_receiver_id
        raise ChatRingError(
            'receiver_id must match the order driver or customer for driver chat rings.',
            errors={'receiver_id': 'Invalid driver/customer receiver for this order.'},
        )

    if chat_type == 'shop_driver':
        normalized_receiver_id = int(receiver_id)
        if sender_user_type in {'shop_owner', 'employee'} and normalized_receiver_id == int(order.driver_id or 0):
            return 'driver', normalized_receiver_id
        if sender_user_type == 'driver' and normalized_receiver_id == int(order.shop_owner_id or 0):
            return 'shop_owner', normalized_receiver_id
        raise ChatRingError(
            'receiver_id must match the order driver or shop owner for shop/driver chat rings.',
            errors={'receiver_id': 'Invalid shop/driver receiver for this order.'},
        )

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


def _participant_has_active_socket(user_type, user_id):
    if not user_id:
        return False
    if user_type == 'customer':
        return CustomerPresenceConnection.objects.filter(customer_id=user_id).exists()
    if user_type == 'driver':
        return DriverPresenceConnection.objects.filter(driver_id=user_id).exists()
    return False


def _ring_state_payload(ring):
    closed_at = None
    if ring.status == 'answered':
        closed_at = ring.answered_at
    elif ring.status == 'dismissed':
        closed_at = ring.dismissed_at
    elif ring.status == 'timeout':
        closed_at = ring.timed_out_at
    elif ring.status == 'cancelled':
        closed_at = ring.cancelled_at

    is_terminal = ring.status in CHAT_RING_TERMINAL_STATUSES
    payload = {
        'is_terminal': is_terminal,
        'is_active': not is_terminal,
        'should_close': is_terminal,
        'closed_at': _format_local_iso8601(closed_at),
        'closed_reason': ring.status if is_terminal else '',
    }
    if is_terminal:
        payload['ui_action'] = 'close_chat'
    return payload


def _normalize_chat_ring_status(status_value):
    status_key = str(status_value or '').strip().lower()
    if not status_key:
        return '', ''
    return (
        CHAT_RING_INTERNAL_STATUS_ALIASES.get(status_key, status_key),
        CHAT_RING_PUBLIC_STATUS_ALIASES.get(status_key, status_key),
    )


def _public_chat_ring_status(status_value):
    _, public_status = _normalize_chat_ring_status(status_value)
    return public_status


def _ring_payload_for_log(ring, payload):
    return {
        'ring_id': str(getattr(ring, 'public_id', '') or ''),
        'chat_id': str(getattr(ring, 'chat_id', '') or ''),
        'order_id': str(getattr(ring, 'order_id', '') or ''),
        'chat_type': str(getattr(ring, 'chat_type', '') or ''),
        'status': str((payload or {}).get('status') or ''),
        'type': str((payload or {}).get('type') or ''),
        'should_close': bool((payload or {}).get('should_close')),
        'is_terminal': bool((payload or {}).get('is_terminal')),
        'is_active': bool((payload or {}).get('is_active')),
        'ui_action': str((payload or {}).get('ui_action') or ''),
        'closed_reason': str((payload or {}).get('closed_reason') or ''),
        'sender_id': str((payload or {}).get('sender_id') or ''),
        'sender_type': str(getattr(ring, 'sender_type', '') or ''),
        'receiver_id': str(getattr(ring, 'receiver_id', '') or ''),
        'receiver_type': str(getattr(ring, 'receiver_type', '') or ''),
    }


def _ring_payload(ring, *, event_type='chat_ring', public_status=None):
    metadata = ring.metadata or {}
    normalized_public_status = _public_chat_ring_status(public_status or ring.status)
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
        'status': normalized_public_status,
        'status_display': _ring_status_display(normalized_public_status, lang='ar'),
        **_ring_state_payload(ring),
    }
    if normalized_public_status and payload.get('is_terminal'):
        payload['closed_reason'] = normalized_public_status
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
    public_display = CHAT_RING_PUBLIC_STATUS_DISPLAY_MAP.get(normalized_lang, {}).get(status_key)
    if public_display:
        return public_display
    return CHAT_RING_STATUS_DISPLAY_MAP.get(normalized_lang, {}).get(status_key, status_key)


def _ring_payload_for_status(ring, status_value, *, lang='ar'):
    _, public_status = _normalize_chat_ring_status(status_value)
    public_status = public_status or _public_chat_ring_status(ring.status)
    payload = _ring_payload(ring, event_type=f'chat_ring_{public_status}', public_status=public_status)
    payload['status_display'] = _ring_status_display(public_status, lang=lang)
    payload['updated_at'] = _format_local_iso8601(ring.updated_at)
    if ring.answered_at is not None:
        payload['answered_at'] = _format_local_iso8601(ring.answered_at)
    if ring.dismissed_at is not None:
        payload['dismissed_at'] = _format_local_iso8601(ring.dismissed_at)
    if ring.timed_out_at is not None:
        payload['timed_out_at'] = _format_local_iso8601(ring.timed_out_at)
    if ring.cancelled_at is not None:
        payload['cancelled_at'] = _format_local_iso8601(ring.cancelled_at)
    return payload


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
    chat_group_name = f'chat_order_{order.id}_{ring.chat_type}'
    if chat_group_name not in groups:
        groups.append(chat_group_name)
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


def _log_ring_delivery(stage, ring, payload, *, groups=None, user_type=None, user_id=None):
    try:
        logger.info(
            'ring.%s payload=%s user_type=%s user_id=%s groups=%s',
            stage,
            json.dumps(_ring_payload_for_log(ring, payload), ensure_ascii=False, default=str),
            user_type or '',
            user_id or '',
            groups or [],
        )
    except Exception:
        logger.exception('Failed to log ring delivery stage=%s ring_id=%s', stage, getattr(ring, 'public_id', None))


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


def _broadcast_ring_status_update(ring, *, public_status=None):
    channel_layer = get_channel_layer()
    if channel_layer is None:
        return

    normalized_public_status = _public_chat_ring_status(public_status or ring.status)
    payload = _ring_payload_for_status(ring, normalized_public_status, lang='ar')
    groups = _ring_socket_group_names(ring)

    logger.info(
        'ring.status.broadcast ring_id=%s order_id=%s chat_type=%s internal_status=%s public_status=%s groups=%s payload=%s',
        ring.public_id,
        ring.order_id,
        ring.chat_type,
        ring.status,
        normalized_public_status,
        groups,
        json.dumps(_ring_payload_for_log(ring, payload), ensure_ascii=False, default=str),
    )

    for group_name in groups:
        async_to_sync(channel_layer.group_send)(
            group_name,
            {
                'type': 'ring',
                'data': payload,
            },
        )
        async_to_sync(channel_layer.group_send)(
            group_name,
            {
                'type': 'ring_status',
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


def _send_ring_status_push_updates(ring, *, public_status=None):
    """
    Send a silent ring status update to both participants.

    The websocket broadcast is the primary path, but this extra data-only
    push helps keep the UI in sync when one side is idle, backgrounded, or
    connected through a less reliable socket session.
    """
    normalized_public_status = _public_chat_ring_status(public_status or ring.status)
    payload = _ring_payload_for_status(ring, normalized_public_status, lang='ar')
    recipients = [
        (ring.sender_type, ring.sender_id),
        (ring.receiver_type, ring.receiver_id),
    ]
    for user_type, user_id in recipients:
        if not user_id:
            continue
        try:
            logger.info(
                'ring.status.push ring_id=%s user_type=%s user_id=%s status=%s payload=%s',
                ring.public_id,
                user_type,
                user_id,
                normalized_public_status,
                json.dumps(_ring_payload_for_log(ring, payload), ensure_ascii=False, default=str),
            )
            _send_ring_event_to_user(user_type, user_id, payload, expires_at=ring.expires_at, with_sound=False)
        except Exception:
            logger.exception(
                'Failed to send silent ring status update ring_id=%s user_type=%s user_id=%s',
                ring.public_id,
                user_type,
                user_id,
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
        'expires_at': _format_local_iso8601(ring.expires_at),
        'sender_name': metadata.get('sender_name') or '',
        'sender_avatar': metadata.get('sender_avatar') or '',
        **_ring_state_payload(ring),
    }


def start_chat_ring(*, order_id, chat_id, sender_id, receiver_id, user, request=None, chat_type='shop_customer'):
    _ensure_chat_ring_storage()
    user_type = _resolve_user_type(user)
    chat_type = _normalize_chat_type(chat_type)
    if chat_type not in CHAT_RING_CHAT_TYPE_CHOICES:
        raise ChatRingError('Unsupported chat type.', status_code=400)

    if user_type not in {'customer', 'shop_owner', 'employee', 'driver'}:
        raise ChatRingError('Authentication is required.', status_code=403)

    try:
        order = Order.objects.select_related('shop_owner', 'customer').get(id=order_id)
    except Order.DoesNotExist as exc:
        raise ChatRingError('Order not found.', status_code=404) from exc

    if not _can_access_shop_customer_chat(order, user, user_type, chat_type=chat_type):
        raise ChatRingError('You do not have access to this shop chat.', status_code=403)

    if str(chat_id or '').strip() == '':
        raise ChatRingError('chat_id is required.', errors={'chat_id': 'This field is required.'})

    if int(sender_id) != int(getattr(user, 'id', 0) or 0):
        raise ChatRingError(
            'sender_id must match the authenticated user.',
            status_code=403,
            errors={'sender_id': 'Authenticated user mismatch.'},
        )

    receiver_type, resolved_receiver_id = _resolve_receiver(order, user_type, receiver_id, chat_type=chat_type)
    now = timezone.now()
    expires_at = now + timedelta(seconds=CHAT_RING_DURATION_SECONDS)

    with transaction.atomic():
        existing_ring = (
            ChatRing.objects.select_for_update()
            .filter(
                chat_type=chat_type,
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
            chat_type=chat_type,
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

    if _participant_has_active_socket(receiver_type, resolved_receiver_id):
        push_summary = {
            'users_targeted': 0,
            'tokens_total': 0,
            'tokens_sent': 0,
            'tokens_failed': 0,
            'tokens_invalidated': 0,
            'skipped_due_to_active_socket': True,
        }
    else:
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
        ChatRing.objects.select_related('order', 'order__shop_owner', 'order__customer', 'order__driver')
        .filter(public_id=ring_id)
        .first()
    )
    if ring is None:
        raise ChatRingError('Chat ring not found.', status_code=404)
    if not _can_access_shop_customer_chat(ring.order, user, user_type, chat_type=ring.chat_type):
        raise ChatRingError('You do not have access to this chat ring.', status_code=403)
    return ring, user_type


def update_chat_ring_status(ring, *, status_value, actor=None):
    _ensure_chat_ring_storage()
    internal_status, public_status = _normalize_chat_ring_status(status_value)
    if internal_status not in {'answered', 'dismissed', 'timeout', 'cancelled'}:
        raise ChatRingError('Unsupported chat ring status transition.')

    original_status = ring.status
    if ring.status == internal_status:
        if ring.status in CHAT_RING_TERMINAL_STATUSES:
            _cancel_chat_ring_timeout_timer(ring.public_id)
        return ring, serialize_chat_ring(ring)
    if ring.status in CHAT_RING_TERMINAL_STATUSES:
        _cancel_chat_ring_timeout_timer(ring.public_id)
        return ring, serialize_chat_ring(ring)

    now = timezone.now()
    update_fields = ['status', 'updated_at']
    ring.status = internal_status
    if internal_status == 'answered':
        ring.answered_at = now
        update_fields.append('answered_at')
    elif internal_status == 'dismissed':
        ring.dismissed_at = now
        update_fields.append('dismissed_at')
    elif internal_status == 'timeout':
        ring.timed_out_at = now
        update_fields.append('timed_out_at')
    elif internal_status == 'cancelled':
        ring.cancelled_at = now
        update_fields.append('cancelled_at')

    actor_type = _resolve_user_type(actor) if actor is not None else ''

    with transaction.atomic():
        ring.save(update_fields=update_fields)
        if internal_status in CHAT_RING_TERMINAL_STATUSES:
            _cancel_chat_ring_timeout_timer(ring.public_id)

        def _dispatch_updates():
            _broadcast_ring_status_update(ring, public_status=public_status)
            _send_ring_status_push_updates(ring, public_status=public_status)
            payload = _ring_payload_for_status(ring, public_status, lang='ar')
            for user_type, user_id in {
                (ring.sender_type, ring.sender_id),
                (ring.receiver_type, ring.receiver_id),
            }:
                _send_ring_event_to_user(user_type, user_id, payload)
            logger.info(
                'ring.status.changed ring_id=%s order_id=%s chat_type=%s from=%s to=%s public_status=%s actor_type=%s actor_id=%s',
                ring.public_id,
                ring.order_id,
                ring.chat_type,
                original_status,
                ring.status,
                public_status,
                actor_type or '',
                getattr(actor, 'id', None) if actor is not None else None,
            )

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
    ring_chat_type = _normalize_chat_type(ring.chat_type)
    if ring_chat_type == 'shop_driver':
        if status_value in {'answered', 'dismissed'}:
            return _actor_matches_ring_side(ring, actor, user_type, 'receiver')
        if status_value == 'cancelled':
            return _actor_matches_ring_side(ring, actor, user_type, 'sender')
        return (
            _actor_matches_ring_side(ring, actor, user_type, 'sender')
            or _actor_matches_ring_side(ring, actor, user_type, 'receiver')
        )
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
    internal_status, public_status = _normalize_chat_ring_status(status_value)
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
        ring_public_status = _public_chat_ring_status(ring.status)
        if ring.status == internal_status or ring_public_status == public_status:
            return ring, {
                'ack': {
                    'ring_id': ring.public_id,
                    'status': ring_public_status,
                    'status_display': _ring_status_display(ring_public_status, lang=lang),
                },
                'ring': {
                    **_ring_payload(ring, event_type='ring', public_status=ring_public_status),
                    'updated_at': _format_local_iso8601(ring.updated_at),
                },
                'status_changed': False,
            }
        if ring.status != internal_status:
            return ring, {
                'ack': {
                    'ring_id': ring.public_id,
                    'status': ring_public_status,
                    'status_display': _ring_status_display(ring_public_status, lang=lang),
                },
                'ring': {
                    **_ring_payload(ring, event_type='ring', public_status=ring_public_status),
                    'updated_at': _format_local_iso8601(ring.updated_at),
                },
                'status_changed': False,
            }

    if not _chat_ring_actor_can_transition(ring, actor, internal_status):
        raise ChatRingError('You do not have permission to update this ring.', status_code=403)

    ring, payload = update_chat_ring_status(ring, status_value=internal_status, actor=actor)
    ring_public_status = public_status or _public_chat_ring_status(ring.status)
    return ring, {
        'ack': {
            'ring_id': ring.public_id,
            'status': ring_public_status,
            'status_display': _ring_status_display(ring_public_status, lang=lang),
        },
        'ring': {
            **_ring_payload(ring, event_type='ring', public_status=ring_public_status),
            'updated_at': _format_local_iso8601(ring.updated_at),
        },
        'status_changed': True,
        'payload': payload,
    }
