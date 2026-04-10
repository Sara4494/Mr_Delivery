import json
import logging
import threading
from pathlib import Path

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from user.models import ShopOwner
from user.utils import build_absolute_file_url

from .models import Customer, Driver, Employee, FCMDeviceToken, Order


logger = logging.getLogger(__name__)

_FIREBASE_APP = None
_FIREBASE_LOCK = threading.Lock()
_UNSET = object()


class FCMConfigurationError(RuntimeError):
    pass


def resolve_user_identity(user):
    user_type = getattr(user, 'user_type', None)
    user_id = getattr(user, 'id', None)

    if user_type in {'customer', 'shop_owner', 'employee', 'driver'} and user_id:
        return user_type, int(user_id)

    if isinstance(user, Customer):
        return 'customer', int(user.id)
    if isinstance(user, ShopOwner):
        return 'shop_owner', int(user.id)
    if isinstance(user, Employee):
        return 'employee', int(user.id)
    if isinstance(user, Driver):
        return 'driver', int(user.id)

    raise ValueError('Unsupported authenticated user for FCM token registration.')


def _mask_token(token):
    token = str(token or '').strip()
    if len(token) <= 12:
        return token or 'empty'
    return f"{token[:6]}...{token[-6:]}"


def _trim_text(value, *, default='', max_length=180):
    text = str(value or '').strip()
    if not text:
        text = default
    return text[:max_length]


def _stringify_payload(data):
    payload = {}
    for key, value in (data or {}).items():
        if value is None:
            continue
        if isinstance(value, bool):
            payload[str(key)] = 'true' if value else 'false'
        else:
            payload[str(key)] = str(value)
    return payload


def _message_preview(message_payload):
    message_type = str((message_payload or {}).get('message_type') or 'text').strip().lower()
    content = _trim_text((message_payload or {}).get('content'), max_length=120)

    if message_type == 'text':
        return content or 'رسالة جديدة'
    if message_type in {'audio', 'voice'}:
        return 'رسالة صوتية'
    if message_type == 'image':
        return 'صورة'
    if message_type == 'location':
        return 'موقع'
    return 'رسالة جديدة'


def _get_shop_identities(shop_owner_id):
    identities = []
    if shop_owner_id:
        identities.append(('shop_owner', int(shop_owner_id)))
        employee_ids = (
            Employee.objects
            .filter(shop_owner_id=shop_owner_id, is_active=True)
            .values_list('id', flat=True)
        )
        identities.extend(('employee', int(employee_id)) for employee_id in employee_ids)
    return identities


def _deduplicate_identities(identities):
    seen = set()
    normalized = []
    for user_type, user_id in identities or []:
        if not user_type or not user_id:
            continue
        key = (str(user_type), int(user_id))
        if key in seen:
            continue
        seen.add(key)
        normalized.append(key)
    return normalized


def _chat_recipient_identities(order, chat_type, sender_type):
    if chat_type == 'shop_customer':
        if sender_type == 'customer':
            return _get_shop_identities(order.shop_owner_id)
        if order.customer_id:
            return [('customer', int(order.customer_id))]
        return []

    if chat_type == 'driver_customer':
        if sender_type == 'customer':
            return [('driver', int(order.driver_id))] if order.driver_id else []
        if order.customer_id:
            return [('customer', int(order.customer_id))]
        return []

    return []


def _ring_target_identities(order, target):
    target = str(target or '').strip().lower()
    if target == 'customer' and order.customer_id:
        return [('customer', int(order.customer_id))]
    if target == 'driver' and order.driver_id:
        return [('driver', int(order.driver_id))]
    if target == 'shop':
        return _get_shop_identities(order.shop_owner_id)
    return []


def _firebase_modules():
    try:
        import firebase_admin
        from firebase_admin import credentials, messaging
    except ImportError as exc:
        raise FCMConfigurationError(
            'firebase_admin is not installed. Add firebase-admin to requirements.'
        ) from exc
    return firebase_admin, credentials, messaging


def _firebase_app():
    global _FIREBASE_APP

    if not getattr(settings, 'FCM_ENABLED', False):
        raise FCMConfigurationError('FCM is disabled.')

    if _FIREBASE_APP is not None:
        return _FIREBASE_APP

    firebase_admin, credentials, _ = _firebase_modules()

    with _FIREBASE_LOCK:
        if _FIREBASE_APP is not None:
            return _FIREBASE_APP

        service_account_json = str(getattr(settings, 'FCM_SERVICE_ACCOUNT_JSON', '') or '').strip()
        service_account_file = str(getattr(settings, 'FCM_SERVICE_ACCOUNT_FILE', '') or '').strip()
        project_id = str(getattr(settings, 'FCM_PROJECT_ID', '') or '').strip()

        if service_account_json:
            try:
                cert_value = json.loads(service_account_json)
            except json.JSONDecodeError as exc:
                raise FCMConfigurationError('FCM_SERVICE_ACCOUNT_JSON is not valid JSON.') from exc
            credential = credentials.Certificate(cert_value)
        elif service_account_file:
            path = Path(service_account_file)
            if not path.exists():
                raise FCMConfigurationError(f'FCM service account file not found: {service_account_file}')
            credential = credentials.Certificate(str(path))
        else:
            raise FCMConfigurationError(
                'FCM is enabled but neither FCM_SERVICE_ACCOUNT_FILE nor FCM_SERVICE_ACCOUNT_JSON is configured.'
            )

        options = {}
        if project_id:
            options['projectId'] = project_id

        _FIREBASE_APP = firebase_admin.initialize_app(credential, options or None, name='mr_delivery_fcm')
        return _FIREBASE_APP


def register_device_token(*, user, device_id, platform, fcm_token, app_version=_UNSET, action='register'):
    user_type, user_id = resolve_user_identity(user)
    now = timezone.now()

    with transaction.atomic():
        FCMDeviceToken.objects.filter(
            user_type=user_type,
            user_id=user_id,
        ).exclude(
            device_id=device_id,
        ).update(is_active=False, updated_at=now)

        FCMDeviceToken.objects.filter(fcm_token=fcm_token).exclude(
            user_type=user_type,
            user_id=user_id,
            device_id=device_id,
        ).update(is_active=False, updated_at=now)

        token_record = (
            FCMDeviceToken.objects.select_for_update()
            .filter(user_type=user_type, user_id=user_id)
            .order_by('-updated_at', '-created_at')
            .first()
        )
        created = token_record is None

        if created:
            token_record = FCMDeviceToken.objects.create(
                user_type=user_type,
                user_id=user_id,
                device_id=device_id,
                platform=platform,
                fcm_token=fcm_token,
                app_version=None if app_version is _UNSET else app_version,
                is_active=True,
                last_used_at=now,
            )

        field_updates = [
            ('device_id', device_id),
            ('platform', platform),
            ('fcm_token', fcm_token),
            ('is_active', True),
            ('last_used_at', now),
        ]
        if app_version is not _UNSET:
            field_updates.append(('app_version', app_version))

        changed_fields = []
        for field, value in field_updates:
            if getattr(token_record, field) != value:
                setattr(token_record, field, value)
                changed_fields.append(field)

        if created:
            changed_fields = []
        elif changed_fields:
            changed_fields.append('updated_at')
            token_record.save(update_fields=changed_fields)

        FCMDeviceToken.objects.filter(
            user_type=user_type,
            user_id=user_id,
        ).exclude(pk=token_record.pk).delete()

    logger.info(
        'fcm.token.%s user_type=%s user_id=%s device_id=%s platform=%s token=%s created=%s',
        action,
        user_type,
        user_id,
        device_id,
        platform,
        _mask_token(fcm_token),
        created,
    )
    return token_record


def unregister_device_token(*, user, device_id=None, fcm_token=None):
    user_type, user_id = resolve_user_identity(user)
    now = timezone.now()

    queryset = FCMDeviceToken.objects.filter(
        user_type=user_type,
        user_id=user_id,
        is_active=True,
    )
    if device_id:
        queryset = queryset.filter(device_id=device_id)
    if fcm_token:
        queryset = queryset.filter(fcm_token=fcm_token)

    affected = queryset.count()
    if affected:
        queryset.update(is_active=False, updated_at=now)

    logger.info(
        'fcm.token.unregister user_type=%s user_id=%s device_id=%s token=%s affected=%s',
        user_type,
        user_id,
        device_id or '',
        _mask_token(fcm_token),
        affected,
    )
    return affected


def _send_push_to_fcm_token(
    *,
    token,
    title,
    body,
    data,
    channel_id,
    sound,
    ios_sound=None,
):
    _, _, messaging = _firebase_modules()
    app = _firebase_app()

    android_notification = messaging.AndroidNotification(
        channel_id=channel_id,
        sound=sound,
    )
    android_config = messaging.AndroidConfig(
        priority='high',
        notification=android_notification,
    )
    apns_config = messaging.APNSConfig(
        headers={
            'apns-priority': '10',
            'apns-push-type': 'alert',
        },
        payload=messaging.APNSPayload(
            aps=messaging.Aps(
                sound=ios_sound or sound or 'default',
                content_available=True,
            )
        ),
    )
    message = messaging.Message(
        token=token,
        notification=messaging.Notification(title=title, body=body),
        data=_stringify_payload(data),
        android=android_config,
        apns=apns_config,
    )
    return messaging.send(message, app=app)


def _is_invalid_token_error(exc):
    class_name = exc.__class__.__name__
    text = str(exc).lower()
    if class_name in {'UnregisteredError', 'SenderIdMismatchError'}:
        return True
    markers = (
        'registration token is not a valid',
        'requested entity was not found',
        'registration-token-not-registered',
        'unregistered',
        'not a valid fcm registration token',
    )
    return any(marker in text for marker in markers)


def _deactivate_token_record(token_record):
    FCMDeviceToken.objects.filter(pk=token_record.pk).update(
        is_active=False,
        updated_at=timezone.now(),
    )


def send_push_to_token_record(
    token_record,
    *,
    title,
    body,
    data,
    channel_id,
    sound,
    ios_sound=None,
):
    logger.info(
        'fcm.send.attempt token_id=%s user_type=%s user_id=%s platform=%s token=%s',
        token_record.id,
        token_record.user_type,
        token_record.user_id,
        token_record.platform,
        _mask_token(token_record.fcm_token),
    )

    try:
        response_id = _send_push_to_fcm_token(
            token=token_record.fcm_token,
            title=title,
            body=body,
            data=data,
            channel_id=channel_id,
            sound=sound,
            ios_sound=ios_sound,
        )
    except FCMConfigurationError as exc:
        logger.warning('fcm.send.skipped reason=%s', exc)
        return {
            'success': False,
            'error': str(exc),
            'invalid_token': False,
        }
    except Exception as exc:
        invalid_token = _is_invalid_token_error(exc)
        if invalid_token:
            _deactivate_token_record(token_record)
            logger.warning(
                'fcm.token.invalid_cleanup token_id=%s user_type=%s user_id=%s error=%s',
                token_record.id,
                token_record.user_type,
                token_record.user_id,
                exc,
            )
        else:
            logger.exception(
                'fcm.send.failed token_id=%s user_type=%s user_id=%s',
                token_record.id,
                token_record.user_type,
                token_record.user_id,
            )
        return {
            'success': False,
            'error': str(exc),
            'invalid_token': invalid_token,
        }

    FCMDeviceToken.objects.filter(pk=token_record.pk).update(
        last_used_at=timezone.now(),
        updated_at=timezone.now(),
    )
    logger.info(
        'fcm.send.success token_id=%s user_type=%s user_id=%s response_id=%s',
        token_record.id,
        token_record.user_type,
        token_record.user_id,
        response_id,
    )
    return {
        'success': True,
        'response_id': response_id,
        'invalid_token': False,
    }


def send_push_to_token(
    fcm_token,
    *,
    title,
    body,
    data,
    channel_id,
    sound,
    ios_sound=None,
):
    token_record = FCMDeviceToken.objects.filter(fcm_token=fcm_token).order_by('-updated_at').first()
    if token_record:
        return send_push_to_token_record(
            token_record,
            title=title,
            body=body,
            data=data,
            channel_id=channel_id,
            sound=sound,
            ios_sound=ios_sound,
        )

    try:
        response_id = _send_push_to_fcm_token(
            token=fcm_token,
            title=title,
            body=body,
            data=data,
            channel_id=channel_id,
            sound=sound,
            ios_sound=ios_sound,
        )
    except Exception as exc:
        logger.exception('fcm.send.failed_raw token=%s', _mask_token(fcm_token))
        return {
            'success': False,
            'error': str(exc),
            'invalid_token': _is_invalid_token_error(exc),
        }

    logger.info('fcm.send.success_raw token=%s response_id=%s', _mask_token(fcm_token), response_id)
    return {
        'success': True,
        'response_id': response_id,
        'invalid_token': False,
    }


def send_push_to_user(
    *,
    user_type,
    user_id,
    title,
    body,
    data,
    channel_id,
    sound,
    ios_sound=None,
):
    token_records = list(
        FCMDeviceToken.objects.filter(
            user_type=user_type,
            user_id=user_id,
            is_active=True,
        ).order_by('-updated_at')
    )
    return _send_push_to_token_records(
        token_records,
        title=title,
        body=body,
        data=data,
        channel_id=channel_id,
        sound=sound,
        ios_sound=ios_sound,
    )


def _send_push_to_token_records(
    token_records,
    *,
    title,
    body,
    data,
    channel_id,
    sound,
    ios_sound=None,
):
    summary = {
        'tokens_total': len(token_records),
        'tokens_sent': 0,
        'tokens_failed': 0,
        'tokens_invalidated': 0,
    }

    for token_record in token_records:
        result = send_push_to_token_record(
            token_record,
            title=title,
            body=body,
            data=data,
            channel_id=channel_id,
            sound=sound,
            ios_sound=ios_sound,
        )
        if result.get('success'):
            summary['tokens_sent'] += 1
        else:
            summary['tokens_failed'] += 1
            if result.get('invalid_token'):
                summary['tokens_invalidated'] += 1

    return summary


def send_push_to_identities(
    identities,
    *,
    title,
    body,
    data,
    channel_id,
    sound,
    ios_sound=None,
):
    summary = {
        'users_targeted': 0,
        'tokens_total': 0,
        'tokens_sent': 0,
        'tokens_failed': 0,
        'tokens_invalidated': 0,
    }

    for user_type, user_id in _deduplicate_identities(identities):
        summary['users_targeted'] += 1
        user_summary = send_push_to_user(
            user_type=user_type,
            user_id=user_id,
            title=title,
            body=body,
            data=data,
            channel_id=channel_id,
            sound=sound,
            ios_sound=ios_sound,
        )
        summary['tokens_total'] += user_summary['tokens_total']
        summary['tokens_sent'] += user_summary['tokens_sent']
        summary['tokens_failed'] += user_summary['tokens_failed']
        summary['tokens_invalidated'] += user_summary['tokens_invalidated']

    return summary


def send_order_chat_push_fallback(order_id, chat_type, message_payload, *, request=None, scope=None, base_url=None):
    try:
        order = Order.objects.select_related('shop_owner', 'customer', 'driver').get(id=order_id)
    except Order.DoesNotExist:
        logger.warning('fcm.chat.order_not_found order_id=%s', order_id)
        return {'users_targeted': 0, 'tokens_total': 0, 'tokens_sent': 0, 'tokens_failed': 0, 'tokens_invalidated': 0}

    sender_type = str((message_payload or {}).get('sender_type') or '').strip()
    recipient_identities = _chat_recipient_identities(order, chat_type, sender_type)
    message_preview = _message_preview(message_payload)
    shop_name = getattr(order.shop_owner, 'shop_name', '') or 'Mr Delivery'
    shop_profile_image_url = build_absolute_file_url(
        getattr(order.shop_owner, 'profile_image', None),
        request=request,
        scope=scope,
        base_url=base_url,
    )
    payload = {
        'type': 'chat_message',
        'order_id': order.id,
        'order_number': order.order_number,
        'shop_id': order.shop_owner_id,
        'shop_name': shop_name,
        'shop_profile_image_url': shop_profile_image_url or '',
        'chat_type': chat_type,
        'message_type': (message_payload or {}).get('message_type') or 'text',
        'message_preview': message_preview,
        'click_action': 'OPEN_CHAT',
    }
    logger.info(
        'fcm.chat.dispatch order_id=%s chat_type=%s sender_type=%s recipients=%s',
        order.id,
        chat_type,
        sender_type,
        recipient_identities,
    )
    return send_push_to_identities(
        recipient_identities,
        title=_trim_text(shop_name, default='Mr Delivery', max_length=120),
        body=_trim_text(message_preview, default='رسالة جديدة', max_length=180),
        data=payload,
        channel_id=getattr(settings, 'FCM_CHAT_CHANNEL_ID', 'chat_channel'),
        sound=getattr(settings, 'FCM_CHAT_SOUND', 'default'),
        ios_sound=getattr(settings, 'FCM_CHAT_IOS_SOUND', 'default'),
    )


def _ring_notification_body(order, ring_payload, target):
    sender_name = _trim_text((ring_payload or {}).get('sender_name'), default='طرف آخر', max_length=80)
    shop_name = _trim_text((ring_payload or {}).get('shop_name') or getattr(order.shop_owner, 'shop_name', ''), max_length=80)
    order_number = _trim_text(order.order_number, max_length=80)

    if target == 'customer' and shop_name:
        return f'{shop_name} يرن عليك بخصوص الطلب {order_number}'
    return f'{sender_name} يرن عليك بخصوص الطلب {order_number}'


def send_ring_push_fallback(order_id, ring_payload, *, request=None, scope=None, base_url=None):
    try:
        order = Order.objects.select_related('shop_owner', 'customer', 'driver').get(id=order_id)
    except Order.DoesNotExist:
        logger.warning('fcm.ring.order_not_found order_id=%s', order_id)
        return {'users_targeted': 0, 'tokens_total': 0, 'tokens_sent': 0, 'tokens_failed': 0, 'tokens_invalidated': 0}

    raw_targets = (ring_payload or {}).get('targets') or [ring_payload.get('target')]
    targets = [str(item).strip().lower() for item in raw_targets if str(item or '').strip()]
    shop_name = _trim_text((ring_payload or {}).get('shop_name') or getattr(order.shop_owner, 'shop_name', ''), default='Mr Delivery', max_length=120)
    shop_profile_image_url = build_absolute_file_url(
        getattr(order.shop_owner, 'profile_image', None),
        request=request,
        scope=scope,
        base_url=base_url,
    )

    summary = {
        'users_targeted': 0,
        'tokens_total': 0,
        'tokens_sent': 0,
        'tokens_failed': 0,
        'tokens_invalidated': 0,
    }

    for target in targets:
        recipient_identities = _ring_target_identities(order, target)
        payload = {
            'type': 'ring',
            'order_id': order.id,
            'order_number': order.order_number,
            'shop_id': order.shop_owner_id,
            'shop_name': shop_name,
            'shop_profile_image_url': shop_profile_image_url or '',
            'chat_type': (ring_payload or {}).get('chat_type') or '',
            'target': target,
            'click_action': 'OPEN_CHAT',
        }
        if ring_payload:
            for field in ('ring_id', 'sender_type', 'sender_name', 'sender_id'):
                if ring_payload.get(field) is not None:
                    payload[field] = ring_payload.get(field)

        logger.info(
            'fcm.ring.dispatch order_id=%s target=%s sender_type=%s recipients=%s',
            order.id,
            target,
            (ring_payload or {}).get('sender_type'),
            recipient_identities,
        )
        target_summary = send_push_to_identities(
            recipient_identities,
            title=shop_name,
            body=_trim_text(_ring_notification_body(order, ring_payload, target), max_length=180),
            data=payload,
            channel_id=getattr(settings, 'FCM_RING_CHANNEL_ID', 'ring_channel'),
            sound=getattr(settings, 'FCM_RING_SOUND', 'incoming_call'),
            ios_sound=getattr(settings, 'FCM_RING_IOS_SOUND', 'incoming_call.mp3'),
        )
        summary['users_targeted'] += target_summary['users_targeted']
        summary['tokens_total'] += target_summary['tokens_total']
        summary['tokens_sent'] += target_summary['tokens_sent']
        summary['tokens_failed'] += target_summary['tokens_failed']
        summary['tokens_invalidated'] += target_summary['tokens_invalidated']

    return summary
