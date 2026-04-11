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
        FCMDeviceToken.objects.select_for_update().filter(
            fcm_token=fcm_token,
        ).exclude(
            user_type=user_type,
            user_id=user_id,
            device_id=device_id,
        ).update(
            is_active=False,
            updated_at=now,
        )

        token_record, created = FCMDeviceToken.objects.select_for_update().get_or_create(
            user_type=user_type,
            user_id=user_id,
            device_id=device_id,
            defaults={
                'platform': platform,
                'fcm_token': fcm_token,
                'app_version': None if app_version is _UNSET else app_version,
                'is_active': True,
                'last_seen_at': now,
                'last_used_at': now,
            },
        )

        if not created:
            field_updates = [
                ('platform', platform),
                ('fcm_token', fcm_token),
                ('is_active', True),
                ('last_seen_at', now),
                ('last_used_at', now),
            ]
            if app_version is not _UNSET:
                field_updates.append(('app_version', app_version))

            changed_fields = []
            for field, value in field_updates:
                if getattr(token_record, field) != value:
                    setattr(token_record, field, value)
                    changed_fields.append(field)

            if changed_fields:
                changed_fields.append('updated_at')
                token_record.save(update_fields=changed_fields)

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
        queryset.update(
            is_active=False,
            updated_at=now,
        )

    logger.info(
        'fcm.token.unregister user_type=%s user_id=%s device_id=%s token=%s affected=%s',
        user_type,
        user_id,
        device_id or '',
        _mask_token(fcm_token),
        affected,
    )
    return affected


def _android_priority(high_priority):
    return 'high' if high_priority else 'normal'


def _apns_priority(high_priority):
    return '10' if high_priority else '5'


def _build_android_config(messaging, *, channel_id, sound, high_priority):
    return messaging.AndroidConfig(
        priority=_android_priority(high_priority),
        notification=messaging.AndroidNotification(
            channel_id=channel_id,
            sound=sound,
        ),
    )


def _build_apns_config(messaging, *, sound, ios_sound, high_priority):
    return messaging.APNSConfig(
        headers={
            'apns-priority': _apns_priority(high_priority),
            'apns-push-type': 'alert',
        },
        payload=messaging.APNSPayload(
            aps=messaging.Aps(
                sound=ios_sound or sound or 'default',
                content_available=True,
            )
        ),
    )


def _build_message_kwargs(
    messaging,
    *,
    title,
    body,
    data,
    channel_id,
    sound,
    ios_sound=None,
    high_priority=False,
):
    return {
        'notification': messaging.Notification(
            title=_trim_text(title, max_length=120),
            body=_trim_text(body, max_length=180),
        ),
        'data': _stringify_payload(data),
        'android': _build_android_config(
            messaging,
            channel_id=channel_id,
            sound=sound,
            high_priority=high_priority,
        ),
        'apns': _build_apns_config(
            messaging,
            sound=sound,
            ios_sound=ios_sound,
            high_priority=high_priority,
        ),
    }


def _send_push_to_fcm_token(
    *,
    token,
    title,
    body,
    data,
    channel_id,
    sound,
    ios_sound=None,
    high_priority=False,
):
    _, _, messaging = _firebase_modules()
    app = _firebase_app()
    message = messaging.Message(
        token=token,
        **_build_message_kwargs(
            messaging,
            title=title,
            body=body,
            data=data,
            channel_id=channel_id,
            sound=sound,
            ios_sound=ios_sound,
            high_priority=high_priority,
        ),
    )
    return messaging.send(message, app=app)


def _chunked(items, size):
    for start in range(0, len(items), size):
        yield items[start:start + size]


def _is_invalid_token_error(exc):
    class_name = exc.__class__.__name__
    text = str(exc).lower()
    if class_name in {
        'UnregisteredError',
        'SenderIdMismatchError',
        'InvalidArgumentError',
        'InvalidArgument',
    }:
        return True
    markers = (
        'registration token is not a valid',
        'requested entity was not found',
        'registration-token-not-registered',
        'not a valid fcm registration token',
        'invalid registration token',
        'invalid argument',
        'unregistered',
        'senderid mismatch',
    )
    return any(marker in text for marker in markers)


def _deactivate_token_record(token_record):
    FCMDeviceToken.objects.filter(pk=token_record.pk).update(
        is_active=False,
        updated_at=timezone.now(),
    )


def _normalize_excluded(values):
    return {str(value).strip() for value in (values or []) if str(value or '').strip()}


def _filter_token_records(token_records, *, exclude_tokens=None, exclude_device_ids=None):
    exclude_tokens = _normalize_excluded(exclude_tokens)
    exclude_device_ids = _normalize_excluded(exclude_device_ids)
    filtered_records = []
    for token_record in token_records:
        if token_record.fcm_token in exclude_tokens:
            continue
        if token_record.device_id in exclude_device_ids:
            continue
        filtered_records.append(token_record)
    return filtered_records


def send_push_to_token_record(
    token_record,
    *,
    title,
    body,
    data,
    channel_id,
    sound,
    ios_sound=None,
    high_priority=False,
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
            high_priority=high_priority,
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

    now = timezone.now()
    FCMDeviceToken.objects.filter(pk=token_record.pk).update(
        last_seen_at=now,
        last_used_at=now,
        updated_at=now,
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


def _send_push_to_token_records(
    token_records,
    *,
    title,
    body,
    data,
    channel_id,
    sound,
    ios_sound=None,
    high_priority=False,
):
    token_records = list(token_records)
    summary = {
        'tokens_total': len(token_records),
        'tokens_sent': 0,
        'tokens_failed': 0,
        'tokens_invalidated': 0,
    }
    if not token_records:
        return summary

    try:
        firebase_admin, _, messaging = _firebase_modules()
        app = _firebase_app()
    except FCMConfigurationError as exc:
        logger.warning('fcm.send.skipped reason=%s', exc)
        summary['tokens_failed'] = summary['tokens_total']
        return summary
    except Exception:
        firebase_admin = None
        messaging = None
        app = None

    if messaging is not None and hasattr(messaging, 'send_each_for_multicast'):
        for chunk in _chunked(token_records, 500):
            message = messaging.MulticastMessage(
                tokens=[token_record.fcm_token for token_record in chunk],
                **_build_message_kwargs(
                    messaging,
                    title=title,
                    body=body,
                    data=data,
                    channel_id=channel_id,
                    sound=sound,
                    ios_sound=ios_sound,
                    high_priority=high_priority,
                ),
            )
            try:
                batch_response = messaging.send_each_for_multicast(message, app=app)
            except Exception:
                for token_record in chunk:
                    result = send_push_to_token_record(
                        token_record,
                        title=title,
                        body=body,
                        data=data,
                        channel_id=channel_id,
                        sound=sound,
                        ios_sound=ios_sound,
                        high_priority=high_priority,
                    )
                    if result.get('success'):
                        summary['tokens_sent'] += 1
                    else:
                        summary['tokens_failed'] += 1
                        if result.get('invalid_token'):
                            summary['tokens_invalidated'] += 1
                continue

            now = timezone.now()
            success_ids = []
            for token_record, send_response in zip(chunk, batch_response.responses):
                if send_response.success:
                    success_ids.append(token_record.pk)
                    summary['tokens_sent'] += 1
                    continue

                summary['tokens_failed'] += 1
                exc = getattr(send_response, 'exception', None)
                if exc and _is_invalid_token_error(exc):
                    summary['tokens_invalidated'] += 1
                    _deactivate_token_record(token_record)
                    logger.warning(
                        'fcm.token.invalid_cleanup token_id=%s user_type=%s user_id=%s error=%s',
                        token_record.id,
                        token_record.user_type,
                        token_record.user_id,
                        exc,
                    )
                elif exc:
                    logger.warning(
                        'fcm.send.failed token_id=%s user_type=%s user_id=%s error=%s',
                        token_record.id,
                        token_record.user_type,
                        token_record.user_id,
                        exc,
                    )

            if success_ids:
                FCMDeviceToken.objects.filter(pk__in=success_ids).update(
                    last_seen_at=now,
                    last_used_at=now,
                    updated_at=now,
                )

        return summary

    for token_record in token_records:
        result = send_push_to_token_record(
            token_record,
            title=title,
            body=body,
            data=data,
            channel_id=channel_id,
            sound=sound,
            ios_sound=ios_sound,
            high_priority=high_priority,
        )
        if result.get('success'):
            summary['tokens_sent'] += 1
        else:
            summary['tokens_failed'] += 1
            if result.get('invalid_token'):
                summary['tokens_invalidated'] += 1

    return summary


def send_to_token(
    token,
    title,
    body,
    data=None,
    *,
    high_priority=False,
    channel_id=None,
    sound='default',
    ios_sound=None,
):
    return send_push_to_token(
        token,
        title=title,
        body=body,
        data=data or {},
        channel_id=channel_id or getattr(settings, 'FCM_CHAT_CHANNEL_ID', 'chat_channel'),
        sound=sound,
        ios_sound=ios_sound,
        high_priority=high_priority,
    )


def send_push_to_token(
    fcm_token,
    *,
    title,
    body,
    data,
    channel_id,
    sound,
    ios_sound=None,
    high_priority=False,
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
            high_priority=high_priority,
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
            high_priority=high_priority,
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


def send_to_user(
    user,
    title,
    body,
    data=None,
    *,
    high_priority=False,
    channel_id=None,
    sound='default',
    ios_sound=None,
    exclude_tokens=None,
    exclude_device_ids=None,
):
    user_type, user_id = resolve_user_identity(user)
    return send_push_to_user(
        user_type=user_type,
        user_id=user_id,
        title=title,
        body=body,
        data=data or {},
        channel_id=channel_id or getattr(settings, 'FCM_CHAT_CHANNEL_ID', 'chat_channel'),
        sound=sound,
        ios_sound=ios_sound,
        high_priority=high_priority,
        exclude_tokens=exclude_tokens,
        exclude_device_ids=exclude_device_ids,
    )


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
    high_priority=False,
    exclude_tokens=None,
    exclude_device_ids=None,
):
    token_records = list(
        FCMDeviceToken.objects.filter(
            user_type=user_type,
            user_id=user_id,
            is_active=True,
        ).order_by('-updated_at')
    )
    token_records = _filter_token_records(
        token_records,
        exclude_tokens=exclude_tokens,
        exclude_device_ids=exclude_device_ids,
    )
    return _send_push_to_token_records(
        token_records,
        title=title,
        body=body,
        data=data,
        channel_id=channel_id,
        sound=sound,
        ios_sound=ios_sound,
        high_priority=high_priority,
    )


def send_to_users(
    users,
    title,
    body,
    data=None,
    *,
    high_priority=False,
    channel_id=None,
    sound='default',
    ios_sound=None,
    exclude_tokens=None,
    exclude_device_ids=None,
):
    identities = [resolve_user_identity(user) for user in users]
    return send_push_to_identities(
        identities,
        title=title,
        body=body,
        data=data or {},
        channel_id=channel_id or getattr(settings, 'FCM_CHAT_CHANNEL_ID', 'chat_channel'),
        sound=sound,
        ios_sound=ios_sound,
        high_priority=high_priority,
        exclude_tokens=exclude_tokens,
        exclude_device_ids=exclude_device_ids,
    )


def send_push_to_identities(
    identities,
    *,
    title,
    body,
    data,
    channel_id,
    sound,
    ios_sound=None,
    high_priority=False,
    exclude_tokens=None,
    exclude_device_ids=None,
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
            high_priority=high_priority,
            exclude_tokens=exclude_tokens,
            exclude_device_ids=exclude_device_ids,
        )
        summary['tokens_total'] += user_summary['tokens_total']
        summary['tokens_sent'] += user_summary['tokens_sent']
        summary['tokens_failed'] += user_summary['tokens_failed']
        summary['tokens_invalidated'] += user_summary['tokens_invalidated']

    return summary


def send_to_topic(
    topic,
    title,
    body,
    data=None,
    *,
    high_priority=False,
    channel_id=None,
    sound='default',
    ios_sound=None,
):
    _, _, messaging = _firebase_modules()
    app = _firebase_app()
    message = messaging.Message(
        topic=str(topic).strip(),
        **_build_message_kwargs(
            messaging,
            title=title,
            body=body,
            data=data or {},
            channel_id=channel_id or getattr(settings, 'FCM_CHAT_CHANNEL_ID', 'chat_channel'),
            sound=sound,
            ios_sound=ios_sound,
            high_priority=high_priority,
        ),
    )
    response_id = messaging.send(message, app=app)
    logger.info('fcm.topic.send.success topic=%s response_id=%s', topic, response_id)
    return {
        'success': True,
        'response_id': response_id,
        'topic': topic,
    }


def broadcast_to_all(
    title,
    body,
    data=None,
    *,
    high_priority=False,
    channel_id=None,
    sound='default',
    ios_sound=None,
    topic=None,
    user_types=None,
):
    if topic:
        topic_result = send_to_topic(
            topic,
            title,
            body,
            data=data or {},
            high_priority=high_priority,
            channel_id=channel_id,
            sound=sound,
            ios_sound=ios_sound,
        )
        return {
            'users_targeted': None,
            'tokens_total': None,
            'tokens_sent': 1 if topic_result.get('success') else 0,
            'tokens_failed': 0 if topic_result.get('success') else 1,
            'tokens_invalidated': 0,
            'topic': topic,
        }

    queryset = FCMDeviceToken.objects.filter(is_active=True)
    if user_types:
        queryset = queryset.filter(user_type__in=list(user_types))

    summary = _send_push_to_token_records(
        list(queryset.order_by('-updated_at')),
        title=title,
        body=body,
        data=data or {},
        channel_id=channel_id or getattr(settings, 'FCM_CHAT_CHANNEL_ID', 'chat_channel'),
        sound=sound,
        ios_sound=ios_sound,
        high_priority=high_priority,
    )
    summary['users_targeted'] = queryset.values('user_type', 'user_id').distinct().count()
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
    payload = build_chat_message_payload(
        order=order,
        chat_type=chat_type,
        message_payload=message_payload,
        shop_name=shop_name,
        shop_profile_image_url=shop_profile_image_url,
    )
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
        high_priority=False,
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
        payload = build_incoming_ring_payload(
            order=order,
            ring_payload=ring_payload,
            target=target,
            shop_name=shop_name,
            shop_profile_image_url=shop_profile_image_url,
        )

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
            high_priority=True,
        )
        summary['users_targeted'] += target_summary['users_targeted']
        summary['tokens_total'] += target_summary['tokens_total']
        summary['tokens_sent'] += target_summary['tokens_sent']
        summary['tokens_failed'] += target_summary['tokens_failed']
        summary['tokens_invalidated'] += target_summary['tokens_invalidated']

    return summary


def build_chat_message_payload(*, order, chat_type, message_payload, shop_name=None, shop_profile_image_url=None):
    message_payload = message_payload or {}
    return {
        'type': 'chat_message',
        'chat_id': order.id,
        'chat_type': chat_type,
        'order_id': order.id,
        'order_number': order.order_number,
        'shop_id': order.shop_owner_id,
        'shop_name': shop_name or getattr(order.shop_owner, 'shop_name', '') or 'Mr Delivery',
        'shop_profile_image_url': shop_profile_image_url or '',
        'sender_id': message_payload.get('sender_id') or '',
        'sender_type': message_payload.get('sender_type') or '',
        'sender_name': message_payload.get('sender_name') or '',
        'message_type': message_payload.get('message_type') or 'text',
        'message_preview': _message_preview(message_payload),
        'route': '/chat',
        'click_action': 'OPEN_CHAT',
    }


def build_incoming_ring_payload(*, order, ring_payload, target, shop_name=None, shop_profile_image_url=None):
    ring_payload = ring_payload or {}
    return {
        'type': 'incoming_ring',
        'ring_id': ring_payload.get('ring_id') or '',
        'call_id': ring_payload.get('call_id') or ring_payload.get('ring_id') or '',
        'order_id': order.id,
        'order_number': order.order_number,
        'shop_id': order.shop_owner_id,
        'shop_name': shop_name or getattr(order.shop_owner, 'shop_name', '') or 'Mr Delivery',
        'shop_profile_image_url': shop_profile_image_url or '',
        'target': target,
        'chat_type': ring_payload.get('chat_type') or '',
        'sender_id': ring_payload.get('sender_id') or '',
        'sender_type': ring_payload.get('sender_type') or '',
        'sender_name': ring_payload.get('sender_name') or '',
        'caller_name': ring_payload.get('caller_name') or ring_payload.get('sender_name') or '',
        'route': '/incoming-ring',
        'click_action': 'OPEN_CHAT',
    }


def build_broadcast_payload(*, notification_type='broadcast', route='/notifications', extra_data=None):
    payload = {
        'type': notification_type,
        'route': route,
        'click_action': 'OPEN_NOTIFICATIONS',
    }
    payload.update(_stringify_payload(extra_data or {}))
    return payload
