import json
import json
import logging
import threading
from datetime import timedelta
from pathlib import Path

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from user.models import ShopOwner
from user.utils import build_absolute_file_url

from ..models import Customer, Driver, DriverPresenceConnection, Employee, FCMDeviceToken, Notification, Order


logger = logging.getLogger(__name__)

_FIREBASE_APPS = {}
_FIREBASE_LOCK = threading.Lock()
_UNSET = object()
_FCM_RESERVED_DATA_KEYS = {
    'from',
    'message_type',
}
_FCM_RESERVED_KEY_RENAMES = {
    'message_type': 'content_type',
}


class FCMConfigurationError(RuntimeError):
    pass


_DRIVER_ORDER_NOTIFICATION_TYPES = {
    'order',
    'order_status',
    'order_assigned',
    'order_cancelled',
    'order_update',
    'new_delivery_order',
}
_DRIVER_CHAT_NOTIFICATION_TYPES = {
    'chat',
    'chat_message',
}
_FCM_USER_TYPE_APP_PROFILE = {
    'driver': 'driver',
    'customer': 'customer',
    'shop_owner': 'customer',
    'employee': 'customer',
}


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
        normalized_key = str(key).strip()
        if not normalized_key:
            continue
        normalized_key = _FCM_RESERVED_KEY_RENAMES.get(normalized_key, normalized_key)
        if normalized_key in _FCM_RESERVED_DATA_KEYS:
            normalized_key = f'app_{normalized_key}'
        if isinstance(value, bool):
            payload[normalized_key] = 'true' if value else 'false'
        else:
            payload[normalized_key] = str(value)
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


def _driver_has_active_socket(driver_id):
    if not driver_id:
        return False
    return DriverPresenceConnection.objects.filter(driver_id=driver_id).exists()


def _driver_urgent_ring_profile():
    return {
        'channel_id': getattr(settings, 'FCM_DRIVER_INCOMING_CALLS_CHANNEL_ID', 'delivery_incoming_calls_v3'),
        'sound': getattr(settings, 'FCM_DRIVER_INCOMING_CALL_SOUND', 'incoming_call'),
        'ios_sound': getattr(settings, 'FCM_DRIVER_INCOMING_CALL_IOS_SOUND', 'incoming_call.mp3'),
        'high_priority': True,
        'ttl': '60s',
        'notification_priority': 'max',
    }


def _customer_driver_chat_ring_profile():
    return {
        'channel_id': getattr(settings, 'FCM_DRIVER_INCOMING_CALLS_CHANNEL_ID', 'delivery_incoming_calls_v3'),
        'sound': getattr(settings, 'FCM_DRIVER_INCOMING_CALL_SOUND', 'incoming_call'),
        'ios_sound': getattr(settings, 'FCM_DRIVER_INCOMING_CALL_IOS_SOUND', 'incoming_call.mp3'),
        'high_priority': True,
        'ttl': '60s',
        'notification_priority': 'max',
    }


def _infer_customer_provider(customer):
    if not customer:
        return 'unknown'
    if str(getattr(customer, 'google_profile_image_url', '') or '').strip():
        return 'google'
    if str(getattr(customer, 'password', '') or '').strip():
        return 'email_password'
    return 'unknown'


def _firebase_modules():
    try:
        import firebase_admin
        from firebase_admin import credentials, messaging
    except ImportError as exc:
        raise FCMConfigurationError(
            'firebase_admin is not installed. Add firebase-admin to requirements.'
        ) from exc
    return firebase_admin, credentials, messaging


def _firebase_app_profile(user_type=None):
    normalized_user_type = str(user_type or '').strip().lower()
    return _FCM_USER_TYPE_APP_PROFILE.get(normalized_user_type, 'default')


def _firebase_app_settings(profile):
    normalized_profile = str(profile or 'default').strip().lower() or 'default'
    if normalized_profile == 'driver':
        return {
            'service_account_json': str(getattr(settings, 'FCM_DRIVER_SERVICE_ACCOUNT_JSON', '') or '').strip(),
            'service_account_file': str(getattr(settings, 'FCM_DRIVER_SERVICE_ACCOUNT_FILE', '') or '').strip(),
            'project_id': str(getattr(settings, 'FCM_DRIVER_PROJECT_ID', '') or '').strip(),
        }
    if normalized_profile == 'customer':
        return {
            'service_account_json': str(getattr(settings, 'FCM_CUSTOMER_SERVICE_ACCOUNT_JSON', '') or '').strip(),
            'service_account_file': str(getattr(settings, 'FCM_CUSTOMER_SERVICE_ACCOUNT_FILE', '') or '').strip(),
            'project_id': str(getattr(settings, 'FCM_CUSTOMER_PROJECT_ID', '') or '').strip(),
        }
    return {
        'service_account_json': str(getattr(settings, 'FCM_SERVICE_ACCOUNT_JSON', '') or '').strip(),
        'service_account_file': str(getattr(settings, 'FCM_SERVICE_ACCOUNT_FILE', '') or '').strip(),
        'project_id': str(getattr(settings, 'FCM_PROJECT_ID', '') or '').strip(),
    }


def _firebase_app(user_type=None):
    if not getattr(settings, 'FCM_ENABLED', False):
        raise FCMConfigurationError('FCM is disabled.')

    profile = _firebase_app_profile(user_type)
    existing_app = _FIREBASE_APPS.get(profile)
    if existing_app is not None:
        return existing_app

    firebase_admin, credentials, _ = _firebase_modules()

    with _FIREBASE_LOCK:
        existing_app = _FIREBASE_APPS.get(profile)
        if existing_app is not None:
            return existing_app

        app_settings = _firebase_app_settings(profile)
        service_account_json = app_settings['service_account_json']
        service_account_file = app_settings['service_account_file']
        project_id = app_settings['project_id']

        if service_account_json:
            try:
                cert_value = json.loads(service_account_json)
            except json.JSONDecodeError as exc:
                raise FCMConfigurationError('FCM_SERVICE_ACCOUNT_JSON is not valid JSON.') from exc
            credential = credentials.Certificate(cert_value)
        elif service_account_file:
            path = Path(service_account_file)
            if not path.exists():
                raise FCMConfigurationError(
                    f'FCM service account file not found for profile "{profile}": {service_account_file}'
                )
            credential = credentials.Certificate(str(path))
        else:
            raise FCMConfigurationError(
                f'FCM is enabled but no service account is configured for profile "{profile}".'
            )

        options = {}
        if project_id:
            options['projectId'] = project_id

        app_name = f'mr_delivery_fcm_{profile}'
        _FIREBASE_APPS[profile] = firebase_admin.initialize_app(credential, options or None, name=app_name)
        return _FIREBASE_APPS[profile]


def register_device_token(*, user, device_id, platform, fcm_token, app_version=_UNSET, action='register'):
    user_type, user_id = resolve_user_identity(user)
    customer_provider = _infer_customer_provider(user) if user_type == 'customer' else None
    now = timezone.now()

    with transaction.atomic():
        FCMDeviceToken.objects.select_for_update().filter(
            fcm_token=fcm_token,
        ).exclude(
            user_type=user_type,
            user_id=user_id,
            device_id=device_id,
        ).delete()

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
        'fcm.token.%s user_type=%s user_id=%s device_id=%s platform=%s token=%s created=%s customer_provider=%s',
        action,
        user_type,
        user_id,
        device_id,
        platform,
        _mask_token(fcm_token),
        created,
        customer_provider,
    )
    return token_record


def unregister_device_token(*, user, device_id=None, fcm_token=None):
    user_type, user_id = resolve_user_identity(user)

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
        queryset.delete()

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


def _coerce_ttl(ttl):
    if ttl in (None, ''):
        return None
    if isinstance(ttl, timedelta):
        return ttl
    ttl_text = str(ttl).strip().lower()
    if ttl_text.endswith('s'):
        return timedelta(seconds=int(ttl_text[:-1] or 0))
    if ttl_text.endswith('h'):
        return timedelta(hours=int(ttl_text[:-1] or 0))
    if ttl_text.endswith('m'):
        return timedelta(minutes=int(ttl_text[:-1] or 0))
    return None


def _driver_notification_profile(notification_type):
    normalized = str(notification_type or '').strip() or 'general_notification'
    urgent_channel = getattr(settings, 'FCM_DRIVER_URGENT_CHANNEL_ID', 'delivery_orders_urgent')
    general_channel = getattr(settings, 'FCM_DRIVER_GENERAL_CHANNEL_ID', 'delivery_general')
    order_sound = getattr(settings, 'FCM_DRIVER_ORDER_SOUND', 'order_ring')
    order_ios_sound = getattr(settings, 'FCM_DRIVER_ORDER_IOS_SOUND', 'order_ring.mp3')
    default_sound = getattr(settings, 'FCM_DRIVER_DEFAULT_SOUND', 'default')

    profiles = {
        'new_delivery_order': {
            'channel_id': urgent_channel,
            'sound': order_sound,
            'ios_sound': order_ios_sound,
            'high_priority': True,
            'ttl': '60s',
            'notification_priority': 'max',
        },
        'store_invite': {
            'channel_id': general_channel,
            'sound': default_sound,
            'ios_sound': default_sound,
            'high_priority': True,
            'ttl': '3600s',
            'notification_priority': 'high',
        },
        'general_notification': {
            'channel_id': general_channel,
            'sound': default_sound,
            'ios_sound': default_sound,
            'high_priority': False,
            'ttl': '86400s',
            'notification_priority': 'default',
        },
        'order_update': {
            'channel_id': general_channel,
            'sound': default_sound,
            'ios_sound': default_sound,
            'high_priority': True,
            'ttl': '3600s',
            'notification_priority': 'high',
        },
    }
    return profiles.get(normalized, profiles['general_notification'])


def build_driver_inbox_notification_payload(
    *,
    notification_type,
    notification_id,
    data=None,
    order_id=None,
):
    payload = dict(data or {})
    normalized_type = str(notification_type or '').strip() or 'general_notification'
    notification_id_value = str(notification_id)
    order_id_value = (
        payload.get('order_id')
        if payload.get('order_id') not in (None, '')
        else order_id
    )
    order_id_value = str(order_id_value) if order_id_value not in (None, '') else None
    conversation_id = payload.get('conversation_id') or payload.get('support_conversation_id')

    payload['notification_id'] = notification_id_value

    if normalized_type in _DRIVER_CHAT_NOTIFICATION_TYPES or conversation_id:
        payload['type'] = 'chat_message'
        payload['screen'] = 'chat'
        payload['click_action'] = 'OPEN_CHAT'
        if conversation_id not in (None, ''):
            payload['conversation_id'] = str(conversation_id)
        if order_id_value is not None:
            payload['order_id'] = order_id_value
        return payload

    if normalized_type in _DRIVER_ORDER_NOTIFICATION_TYPES or (
        order_id_value is not None and str(payload.get('screen') or '').strip() == 'order_details'
    ):
        payload['type'] = 'order'
        payload['screen'] = 'order_details'
        payload['click_action'] = 'OPEN_ORDER'
        if order_id_value is not None:
            payload['order_id'] = order_id_value
        payload.pop('route', None)
        return payload

    payload['type'] = payload.get('type') or normalized_type
    payload['screen'] = 'notifications'
    payload['route'] = '/notifications'
    payload['click_action'] = 'OPEN_NOTIFICATIONS'
    return payload


def send_driver_notification_from_record(driver, notification):
    if not driver or not notification:
        return {
            'notification': notification,
            'push': {
                'tokens_total': 0,
                'tokens_sent': 0,
                'tokens_failed': 0,
                'tokens_invalidated': 0,
            },
        }

    payload = build_driver_inbox_notification_payload(
        notification_type=notification.notification_type,
        notification_id=notification.id,
        data=notification.data or {},
        order_id=notification.order_id,
    )
    profile = _driver_notification_profile(notification.notification_type)
    tag = (
        str(payload.get('tag')).strip()
        if str(payload.get('tag') or '').strip()
        else f"{notification.notification_type}_{notification.id}"
    )

    return {
        'notification': notification,
        'push': send_to_user(
            driver,
            title=notification.title,
            body=notification.message,
            data=payload,
            high_priority=profile['high_priority'],
            channel_id=profile['channel_id'],
            sound=profile['sound'],
            ios_sound=profile['ios_sound'],
            ttl=profile['ttl'],
            click_action=payload['click_action'],
            notification_priority=profile['notification_priority'],
            tag=tag,
        ),
    }


def _build_android_config(
    messaging,
    *,
    channel_id,
    sound,
    high_priority,
    ttl=None,
    click_action=None,
    notification_priority=None,
    tag=None,
):
    return messaging.AndroidConfig(
        priority=_android_priority(high_priority),
        ttl=_coerce_ttl(ttl),
        notification=messaging.AndroidNotification(
            channel_id=channel_id,
            sound=sound,
            click_action=click_action,
            priority=notification_priority,
            tag=tag,
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
    ttl=None,
    click_action=None,
    notification_priority=None,
    tag=None,
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
            ttl=ttl,
            click_action=click_action,
            notification_priority=notification_priority,
            tag=tag,
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
    user_type=None,
    title,
    body,
    data,
    channel_id,
    sound,
    ios_sound=None,
    high_priority=False,
    ttl=None,
    click_action=None,
    notification_priority=None,
    tag=None,
):
    _, _, messaging = _firebase_modules()
    app = _firebase_app(user_type=user_type)
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
            ttl=ttl,
            click_action=click_action,
            notification_priority=notification_priority,
            tag=tag,
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
    FCMDeviceToken.objects.filter(pk=token_record.pk).delete()


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
    ttl=None,
    click_action=None,
    notification_priority=None,
    tag=None,
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
            user_type=token_record.user_type,
            title=title,
            body=body,
            data=data,
            channel_id=channel_id,
            sound=sound,
            ios_sound=ios_sound,
            high_priority=high_priority,
            ttl=ttl,
            click_action=click_action,
            notification_priority=notification_priority,
            tag=tag,
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
    ttl=None,
    click_action=None,
    notification_priority=None,
    tag=None,
):
    token_records = list(token_records)
    summary = {
        'tokens_total': len(token_records),
        'tokens_sent': 0,
        'tokens_failed': 0,
        'tokens_invalidated': 0,
    }
    if not token_records:
        logger.info('fcm.send.batch.skip reason=no_active_tokens')
        return summary

    try:
        firebase_admin, _, messaging = _firebase_modules()
        primary_user_type = token_records[0].user_type if token_records else None
        app = _firebase_app(user_type=primary_user_type)
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
                    ttl=ttl,
                    click_action=click_action,
                    notification_priority=notification_priority,
                    tag=tag,
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
                    ttl=ttl,
                    click_action=click_action,
                    notification_priority=notification_priority,
                    tag=tag,
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
            logger.info(
                'fcm.send.batch.chunk tokens=%s success=%s failure=%s',
                len(chunk),
                sum(1 for response in batch_response.responses if response.success),
                sum(1 for response in batch_response.responses if not response.success),
            )

        logger.info(
            'fcm.send.batch.complete tokens_total=%s tokens_sent=%s tokens_failed=%s tokens_invalidated=%s',
            summary['tokens_total'],
            summary['tokens_sent'],
            summary['tokens_failed'],
            summary['tokens_invalidated'],
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
            ttl=ttl,
            click_action=click_action,
            notification_priority=notification_priority,
            tag=tag,
        )
        if result.get('success'):
            summary['tokens_sent'] += 1
        else:
            summary['tokens_failed'] += 1
            if result.get('invalid_token'):
                summary['tokens_invalidated'] += 1

    logger.info(
        'fcm.send.batch.complete tokens_total=%s tokens_sent=%s tokens_failed=%s tokens_invalidated=%s',
        summary['tokens_total'],
        summary['tokens_sent'],
        summary['tokens_failed'],
        summary['tokens_invalidated'],
    )
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
    ttl=None,
    click_action=None,
    notification_priority=None,
    tag=None,
):
    return send_push_to_token(
        token,
        title=title,
        body=body,
        data=data or {},
        channel_id=channel_id or getattr(settings, 'FCM_CHAT_CHANNEL_ID', 'delivery_general'),
        sound=sound,
        ios_sound=ios_sound,
        high_priority=high_priority,
        ttl=ttl,
        click_action=click_action,
        notification_priority=notification_priority,
        tag=tag,
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
    ttl=None,
    click_action=None,
    notification_priority=None,
    tag=None,
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
            ttl=ttl,
            click_action=click_action,
            notification_priority=notification_priority,
            tag=tag,
        )

    try:
        response_id = _send_push_to_fcm_token(
            token=fcm_token,
            user_type=token_record.user_type if token_record else None,
            title=title,
            body=body,
            data=data,
            channel_id=channel_id,
            sound=sound,
            ios_sound=ios_sound,
            high_priority=high_priority,
            ttl=ttl,
            click_action=click_action,
            notification_priority=notification_priority,
            tag=tag,
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
    ttl=None,
    click_action=None,
    notification_priority=None,
    tag=None,
):
    user_type, user_id = resolve_user_identity(user)
    return send_push_to_user(
        user_type=user_type,
        user_id=user_id,
        title=title,
        body=body,
        data=data or {},
        channel_id=channel_id or getattr(settings, 'FCM_CHAT_CHANNEL_ID', 'delivery_general'),
        sound=sound,
        ios_sound=ios_sound,
        high_priority=high_priority,
        exclude_tokens=exclude_tokens,
        exclude_device_ids=exclude_device_ids,
        ttl=ttl,
        click_action=click_action,
        notification_priority=notification_priority,
        tag=tag,
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
    ttl=None,
    click_action=None,
    notification_priority=None,
    tag=None,
):
    token_records = list(
        FCMDeviceToken.objects.filter(
            user_type=user_type,
            user_id=user_id,
            is_active=True,
        ).order_by('-updated_at')
    )
    logger.info(
        'fcm.user.lookup user_type=%s user_id=%s active_tokens=%s',
        user_type,
        user_id,
        len(token_records),
    )
    token_records = _filter_token_records(
        token_records,
        exclude_tokens=exclude_tokens,
        exclude_device_ids=exclude_device_ids,
    )
    logger.info(
        'fcm.user.lookup.filtered user_type=%s user_id=%s tokens_after_filter=%s',
        user_type,
        user_id,
        len(token_records),
    )
    summary = _send_push_to_token_records(
        token_records,
        title=title,
        body=body,
        data=data,
        channel_id=channel_id,
        sound=sound,
        ios_sound=ios_sound,
        high_priority=high_priority,
        ttl=ttl,
        click_action=click_action,
        notification_priority=notification_priority,
        tag=tag,
    )
    summary['users_targeted'] = 1 if token_records else 0
    return summary


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
    ttl=None,
    click_action=None,
    notification_priority=None,
    tag=None,
):
    identities = [resolve_user_identity(user) for user in users]
    summary = send_push_to_identities(
        identities,
        title=title,
        body=body,
        data=data or {},
        channel_id=channel_id or getattr(settings, 'FCM_CHAT_CHANNEL_ID', 'delivery_general'),
        sound=sound,
        ios_sound=ios_sound,
        high_priority=high_priority,
        exclude_tokens=exclude_tokens,
        exclude_device_ids=exclude_device_ids,
        ttl=ttl,
        click_action=click_action,
        notification_priority=notification_priority,
        tag=tag,
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
    ttl=None,
    click_action=None,
    notification_priority=None,
    tag=None,
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
            ttl=ttl,
            click_action=click_action,
            notification_priority=notification_priority,
            tag=tag,
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
    ttl=None,
    click_action=None,
    notification_priority=None,
    tag=None,
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
            channel_id=channel_id or getattr(settings, 'FCM_CHAT_CHANNEL_ID', 'delivery_general'),
            sound=sound,
            ios_sound=ios_sound,
            high_priority=high_priority,
            ttl=ttl,
            click_action=click_action,
            notification_priority=notification_priority,
            tag=tag,
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
    ttl=None,
    click_action=None,
    notification_priority=None,
    tag=None,
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
            ttl=ttl,
            click_action=click_action,
            notification_priority=notification_priority,
            tag=tag,
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
        channel_id=channel_id or getattr(settings, 'FCM_CHAT_CHANNEL_ID', 'delivery_general'),
        sound=sound,
        ios_sound=ios_sound,
        high_priority=high_priority,
        ttl=ttl,
        click_action=click_action,
        notification_priority=notification_priority,
        tag=tag,
    )
    summary['users_targeted'] = queryset.values('user_type', 'user_id').distinct().count()
    return summary


def _create_driver_notification_record(
    driver,
    *,
    notification_type,
    title,
    body,
    data,
    order_id=None,
    store_id=None,
    image_url=None,
    reference_id=None,
    idempotency_key=None,
):
    payload = {
        'driver': driver,
        'notification_type': notification_type,
        'title': _trim_text(title, max_length=200),
        'message': _trim_text(body, max_length=400),
        'order_id': order_id,
        'store_id': store_id,
        'image_url': image_url,
        'reference_id': str(reference_id).strip() if reference_id not in (None, '') else None,
        'idempotency_key': str(idempotency_key).strip() if idempotency_key not in (None, '') else None,
        'data': data or {},
    }

    if payload['idempotency_key']:
        existing = Notification.objects.filter(
            driver=driver,
            idempotency_key=payload['idempotency_key'],
        ).first()
        if existing:
            updated_fields = []
            for field in ('notification_type', 'title', 'message', 'order_id', 'store_id', 'image_url', 'data'):
                if getattr(existing, field) != payload[field]:
                    setattr(existing, field, payload[field])
                    updated_fields.append(field)
            if updated_fields:
                existing.save(update_fields=updated_fields)
            return existing

    return Notification.objects.create(**payload)


def _send_driver_push(
    driver,
    *,
    notification_type,
    title,
    body,
    data=None,
    reference_id=None,
    idempotency_key=None,
    image_url=None,
    order_id=None,
    store_id=None,
    create_record=False,
):
    data = dict(data or {})
    if image_url:
        data.setdefault('image_url', image_url)

    notification = None
    payload = {
        'type': notification_type,
        **data,
    }

    if create_record:
        notification = _create_driver_notification_record(
            driver,
            notification_type=notification_type,
            title=title,
            body=body,
            data=data,
            order_id=order_id,
            store_id=store_id,
            image_url=image_url,
            reference_id=reference_id,
            idempotency_key=idempotency_key,
        )
        return send_driver_notification_from_record(driver, notification)

    profile = _driver_notification_profile(notification_type)
    return {
        'notification': notification,
        'push': send_to_user(
            driver,
            title=title,
            body=body,
            data=payload,
            high_priority=profile['high_priority'],
            channel_id=profile['channel_id'],
            sound=profile['sound'],
            ios_sound=profile['ios_sound'],
            ttl=profile['ttl'],
            click_action='FLUTTER_NOTIFICATION_CLICK',
            notification_priority=profile['notification_priority'],
            tag=str(data.get('tag') or f"{notification_type}_{notification.id if notification else driver.id}"),
        ),
    }


def send_driver_notification(
    driver,
    *,
    notification_type,
    title,
    body,
    data=None,
    reference_id=None,
    idempotency_key=None,
    image_url=None,
    order_id=None,
    store_id=None,
):
    return _send_driver_push(
        driver,
        notification_type=notification_type,
        title=title,
        body=body,
        data=data,
        reference_id=reference_id,
        idempotency_key=idempotency_key,
        image_url=image_url,
        order_id=order_id,
        store_id=store_id,
        create_record=True,
    )


def send_driver_push_only_notification(
    driver,
    *,
    notification_type,
    title,
    body,
    data=None,
    image_url=None,
    order_id=None,
    store_id=None,
):
    return _send_driver_push(
        driver,
        notification_type=notification_type,
        title=title,
        body=body,
        data=data,
        image_url=image_url,
        order_id=order_id,
        store_id=store_id,
        create_record=False,
    )


def send_driver_system_notification(
    driver,
    *,
    title,
    body,
    data=None,
    notification_type='general_notification',
    reference_id=None,
    idempotency_key=None,
    image_url=None,
    order_id=None,
    store_id=None,
):
    payload_data = dict(data or {})
    payload_data.setdefault('screen', 'notifications')
    return send_driver_notification(
        driver,
        notification_type=notification_type,
        title=title,
        body=body,
        data=payload_data,
        reference_id=reference_id,
        idempotency_key=idempotency_key,
        image_url=image_url,
        order_id=order_id,
        store_id=store_id,
    )


def send_driver_system_notifications(
    drivers,
    *,
    title,
    body,
    data=None,
    notification_type='general_notification',
    reference_id=None,
    idempotency_key=None,
    image_url=None,
    order_id=None,
    store_id=None,
):
    summary = {
        'drivers_targeted': 0,
        'notifications_created': 0,
        'tokens_total': 0,
        'tokens_sent': 0,
        'tokens_failed': 0,
        'tokens_invalidated': 0,
        'notification_ids': [],
    }

    for driver in drivers:
        result = send_driver_system_notification(
            driver,
            title=title,
            body=body,
            data=data,
            notification_type=notification_type,
            reference_id=reference_id,
            idempotency_key=(
                f'{idempotency_key}:driver:{driver.id}'
                if idempotency_key not in (None, '')
                else None
            ),
            image_url=image_url,
            order_id=order_id,
            store_id=store_id,
        )
        summary['drivers_targeted'] += 1
        notification = result.get('notification')
        if notification is not None:
            summary['notifications_created'] += 1
            summary['notification_ids'].append(notification.id)
        push_summary = result.get('push') or {}
        summary['tokens_total'] += int(push_summary.get('tokens_total') or 0)
        summary['tokens_sent'] += int(push_summary.get('tokens_sent') or 0)
        summary['tokens_failed'] += int(push_summary.get('tokens_failed') or 0)
        summary['tokens_invalidated'] += int(push_summary.get('tokens_invalidated') or 0)

    return summary


def send_driver_system_broadcast_notification(
    *,
    title,
    body,
    data=None,
    notification_type='general_notification',
    reference_id=None,
    idempotency_key=None,
    image_url=None,
    order_id=None,
    store_id=None,
    drivers_queryset=None,
):
    drivers = list((drivers_queryset or Driver.objects.all()).order_by('id'))
    return send_driver_system_notifications(
        drivers,
        title=title,
        body=body,
        data=data,
        notification_type=notification_type,
        reference_id=reference_id,
        idempotency_key=idempotency_key,
        image_url=image_url,
        order_id=order_id,
        store_id=store_id,
    )


def send_driver_new_order_notification(driver, order, *, request=None, scope=None, base_url=None):
    shop_owner = getattr(order, 'shop_owner', None)
    store_name = _trim_text(getattr(shop_owner, 'shop_name', None), default='Mr Delivery', max_length=120)
    image_url = build_absolute_file_url(
        getattr(shop_owner, 'profile_image', None),
        request=request,
        scope=scope,
        base_url=base_url,
    )
    return send_driver_push_only_notification(
        driver,
        notification_type='new_delivery_order',
        title='في طلب جديد جاهز للاستلام',
        body=f'{store_name} أضافت طلب توصيل جديد ومتاح لك الآن.',
        image_url=image_url,
        order_id=order.id,
        store_id=getattr(shop_owner, 'id', None),
        data={
            'order_id': order.id,
            'store_id': getattr(shop_owner, 'id', None),
            'store_name': getattr(shop_owner, 'shop_name', None),
            'screen': 'order_details',
            'sound': getattr(settings, 'FCM_DRIVER_ORDER_SOUND', 'order_ring'),
            'tag': f'order_{order.id}',
        },
    )


def send_driver_store_invite_notification(driver, shop_owner, invitation, *, request=None, scope=None, base_url=None):
    image_url = build_absolute_file_url(
        getattr(shop_owner, 'profile_image', None),
        request=request,
        scope=scope,
        base_url=base_url,
    )
    return send_driver_push_only_notification(
        driver,
        notification_type='store_invite',
        title='دعوة انضمام لمتجر',
        body=f'لديك دعوة جديدة من {shop_owner.shop_name}.',
        image_url=image_url,
        store_id=shop_owner.id,
        data={
            'invitation_id': invitation.id,
            'store_id': shop_owner.id,
            'store_name': shop_owner.shop_name,
            'screen': 'driver_invitations',
        },
    )


def send_driver_order_update_notification(driver, order, *, update_kind='order_update', body=None, request=None, scope=None, base_url=None):
    shop_owner = getattr(order, 'shop_owner', None)
    store_name = _trim_text(getattr(shop_owner, 'shop_name', None), default='Mr Delivery', max_length=120)
    image_url = build_absolute_file_url(
        getattr(shop_owner, 'profile_image', None),
        request=request,
        scope=scope,
        base_url=base_url,
    )
    order_number = getattr(order, 'order_number', order.id)
    return send_driver_push_only_notification(
        driver,
        notification_type='order_update',
        title='تحديث مهم على الطلب',
        body=body or f'تم تحديث الطلب #{order_number} من {store_name}.',
        image_url=image_url,
        order_id=order.id,
        store_id=getattr(shop_owner, 'id', None),
        data={
            'order_id': order.id,
            'store_id': getattr(shop_owner, 'id', None),
            'store_name': getattr(shop_owner, 'shop_name', None),
            'screen': 'order_details',
            'update_kind': update_kind,
        },
    )


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
    summary = send_push_to_identities(
        recipient_identities,
        title=_trim_text(shop_name, default='Mr Delivery', max_length=120),
        body=_trim_text(message_preview, default='رسالة جديدة', max_length=180),
        data=payload,
        channel_id=getattr(settings, 'FCM_CHAT_CHANNEL_ID', 'delivery_general'),
        sound=getattr(settings, 'FCM_CHAT_SOUND', 'default'),
        ios_sound=getattr(settings, 'FCM_CHAT_IOS_SOUND', 'default'),
        high_priority=False,
    )
    logger.info(
        'fcm.chat.result order_id=%s users_targeted=%s tokens_total=%s tokens_sent=%s tokens_failed=%s tokens_invalidated=%s',
        order.id,
        summary['users_targeted'],
        summary['tokens_total'],
        summary['tokens_sent'],
        summary['tokens_failed'],
        summary['tokens_invalidated'],
    )
    return summary


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
    targets = []
    seen_targets = set()
    for item in raw_targets:
        normalized_target = str(item or '').strip().lower()
        if not normalized_target or normalized_target in seen_targets:
            continue
        seen_targets.add(normalized_target)
        targets.append(normalized_target)
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
    customer_provider = _infer_customer_provider(getattr(order, 'customer', None))

    for target in targets:
        recipient_identities = _ring_target_identities(order, target)
        if target == 'driver':
            if not order.driver_id or _driver_has_active_socket(order.driver_id):
                continue
            payload = build_driver_customer_ring_payload(order=order, ring_payload=ring_payload)
            profile = _driver_urgent_ring_profile()
            title = payload['title']
            body = payload['body']
            channel_id = profile['channel_id']
            sound = profile['sound']
            ios_sound = profile['ios_sound']
            high_priority = profile['high_priority']
            ttl = profile['ttl']
            notification_priority = profile['notification_priority']
        else:
            if target == 'customer' and str((ring_payload or {}).get('chat_type') or '').strip() == 'driver_customer':
                payload = build_customer_driver_chat_ring_payload(
                    order=order,
                    ring_payload=ring_payload,
                    shop_name=shop_name,
                    shop_profile_image_url=shop_profile_image_url,
                )
                profile = _customer_driver_chat_ring_profile()
                title = payload['title']
                body = payload['body']
                channel_id = profile['channel_id']
                sound = profile['sound']
                ios_sound = profile['ios_sound']
                high_priority = profile['high_priority']
                ttl = profile['ttl']
                notification_priority = profile['notification_priority']
            else:
                payload = build_incoming_ring_payload(
                    order=order,
                    ring_payload=ring_payload,
                    target=target,
                    shop_name=shop_name,
                    shop_profile_image_url=shop_profile_image_url,
                )
                title = shop_name
                body = _trim_text(_ring_notification_body(order, ring_payload, target), max_length=180)
                channel_id = getattr(settings, 'FCM_RING_CHANNEL_ID', 'delivery_general')
                sound = getattr(settings, 'FCM_RING_SOUND', 'default')
                ios_sound = getattr(settings, 'FCM_RING_IOS_SOUND', 'default')
                high_priority = True
                ttl = None
                notification_priority = None
                payload['title'] = title
                payload['body'] = body
                payload['sound'] = sound
                payload['channel_id'] = channel_id

        logger.info(
            'fcm.ring.dispatch order_id=%s target=%s sender_type=%s recipients=%s customer_id=%s customer_provider=%s payload_type=%s chat_type=%s conversation_id=%s ring_id=%s',
            order.id,
            target,
            (ring_payload or {}).get('sender_type'),
            recipient_identities,
            getattr(order, 'customer_id', None),
            customer_provider,
            payload.get('type'),
            payload.get('chat_type'),
            payload.get('conversation_id'),
            payload.get('ring_id'),
        )
        target_summary = send_push_to_identities(
            recipient_identities,
            title=title,
            body=body,
            data=payload,
            channel_id=channel_id,
            sound=sound,
            ios_sound=ios_sound,
            high_priority=high_priority,
            ttl=ttl,
            notification_priority=notification_priority,
            click_action='FLUTTER_NOTIFICATION_CLICK',
            tag=str(payload.get('ring_id') or f'ring_{order.id}_{target}'),
        )
        summary['users_targeted'] += target_summary['users_targeted']
        summary['tokens_total'] += target_summary['tokens_total']
        summary['tokens_sent'] += target_summary['tokens_sent']
        summary['tokens_failed'] += target_summary['tokens_failed']
        summary['tokens_invalidated'] += target_summary['tokens_invalidated']
        logger.info(
            'fcm.ring.result order_id=%s target=%s users_targeted=%s tokens_total=%s tokens_sent=%s tokens_failed=%s tokens_invalidated=%s customer_id=%s customer_provider=%s',
            order.id,
            target,
            target_summary['users_targeted'],
            target_summary['tokens_total'],
            target_summary['tokens_sent'],
            target_summary['tokens_failed'],
            target_summary['tokens_invalidated'],
            getattr(order, 'customer_id', None),
            customer_provider,
        )

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


def build_driver_store_chat_message_payload(*, conversation, message_payload, order_id=None, shop_name=None, shop_profile_image_url=None):
    message_payload = message_payload or {}
    return {
        'type': 'chat_message',
        'screen': 'chat',
        'route': '/driver-chats',
        'click_action': 'OPEN_CHAT',
        'conversation_id': conversation.public_id,
        'order_id': order_id or '',
        'shop_id': conversation.shop_owner_id,
        'shop_name': shop_name or getattr(conversation.shop_owner, 'shop_name', '') or 'Mr Delivery',
        'shop_profile_image_url': shop_profile_image_url or '',
        'sender_type': message_payload.get('sender') or message_payload.get('sender_type') or '',
        'message_type': message_payload.get('type') or message_payload.get('message_type') or 'text',
        'message_preview': _message_preview(message_payload),
    }


def send_driver_chat_push_fallback(conversation, message_payload, *, request=None, scope=None, base_url=None):
    if not conversation or not getattr(conversation, 'driver_id', None):
        return {'users_targeted': 0, 'tokens_total': 0, 'tokens_sent': 0, 'tokens_failed': 0, 'tokens_invalidated': 0}

    sender_type = str((message_payload or {}).get('sender') or (message_payload or {}).get('sender_type') or '').strip()
    if sender_type != 'store':
        return {'users_targeted': 0, 'tokens_total': 0, 'tokens_sent': 0, 'tokens_failed': 0, 'tokens_invalidated': 0}

    shop_name = getattr(conversation.shop_owner, 'shop_name', '') or 'Mr Delivery'
    shop_profile_image_url = build_absolute_file_url(
        getattr(conversation.shop_owner, 'profile_image', None),
        request=request,
        scope=scope,
        base_url=base_url,
    )

    order_link = (
        conversation.orders
        .select_related('order')
        .order_by('-is_active', '-updated_at', '-created_at')
        .first()
    )
    order_id = order_link.order_id if order_link else None
    payload = build_driver_store_chat_message_payload(
        conversation=conversation,
        message_payload=message_payload,
        order_id=order_id,
        shop_name=shop_name,
        shop_profile_image_url=shop_profile_image_url,
    )
    logger.info(
        'fcm.driver_chat.dispatch conversation_id=%s driver_id=%s sender_type=%s',
        conversation.public_id,
        conversation.driver_id,
        sender_type,
    )
    summary = send_push_to_user(
        user_type='driver',
        user_id=conversation.driver_id,
        title=_trim_text(shop_name, default='Mr Delivery', max_length=120),
        body=_trim_text(_message_preview(message_payload), default='لديك رسالة جديدة', max_length=180),
        data=payload,
        channel_id=getattr(settings, 'FCM_CHAT_CHANNEL_ID', 'delivery_general'),
        sound=getattr(settings, 'FCM_CHAT_SOUND', 'default'),
        ios_sound=getattr(settings, 'FCM_CHAT_IOS_SOUND', 'default'),
        high_priority=False,
    )
    logger.info(
        'fcm.driver_chat.result conversation_id=%s users_targeted=%s tokens_total=%s tokens_sent=%s tokens_failed=%s tokens_invalidated=%s',
        conversation.public_id,
        summary['users_targeted'],
        summary['tokens_total'],
        summary['tokens_sent'],
        summary['tokens_failed'],
        summary['tokens_invalidated'],
    )
    return summary


def send_driver_chat_call_ringing_push_fallback(conversation, call, *, request=None, scope=None, base_url=None):
    if not conversation or not getattr(conversation, 'driver_id', None):
        return {'users_targeted': 0, 'tokens_total': 0, 'tokens_sent': 0, 'tokens_failed': 0, 'tokens_invalidated': 0}

    if getattr(call, 'initiated_by', '') != 'store':
        return {'users_targeted': 0, 'tokens_total': 0, 'tokens_sent': 0, 'tokens_failed': 0, 'tokens_invalidated': 0}

    if _driver_has_active_socket(conversation.driver_id):
        return {'users_targeted': 0, 'tokens_total': 0, 'tokens_sent': 0, 'tokens_failed': 0, 'tokens_invalidated': 0}

    payload = build_driver_shop_call_ringing_payload(conversation=conversation, call=call)
    profile = _driver_urgent_ring_profile()
    logger.info(
        'fcm.driver_chat.call_ringing.dispatch conversation_id=%s driver_id=%s call_id=%s',
        conversation.public_id,
        conversation.driver_id,
        getattr(call, 'public_id', None),
    )
    summary = send_push_to_user(
        user_type='driver',
        user_id=conversation.driver_id,
        title=payload['title'],
        body=payload['body'],
        data=payload,
        channel_id=profile['channel_id'],
        sound=profile['sound'],
        ios_sound=profile['ios_sound'],
        high_priority=profile['high_priority'],
        ttl=profile['ttl'],
        click_action='FLUTTER_NOTIFICATION_CLICK',
        notification_priority=profile['notification_priority'],
        tag=str(payload.get('call_id') or f'call_{conversation.public_id}'),
    )
    logger.info(
        'fcm.driver_chat.call_ringing.result conversation_id=%s users_targeted=%s tokens_total=%s tokens_sent=%s tokens_failed=%s tokens_invalidated=%s',
        conversation.public_id,
        summary['users_targeted'],
        summary['tokens_total'],
        summary['tokens_sent'],
        summary['tokens_failed'],
        summary['tokens_invalidated'],
    )
    return summary


def build_incoming_ring_payload(*, order, ring_payload, target, shop_name=None, shop_profile_image_url=None):
    ring_payload = ring_payload or {}
    resolved_shop_name = shop_name or getattr(order.shop_owner, 'shop_name', '') or 'Mr Delivery'
    driver_image_url = ring_payload.get('driver_image_url')
    if driver_image_url is None and ring_payload.get('sender_type') == 'driver':
        driver_image_url = build_absolute_file_url(getattr(order.driver, 'profile_image', None))
    customer = getattr(order, 'customer', None)
    customer_name = _trim_text(getattr(customer, 'name', None), default='العميل', max_length=120)
    sender_name = _trim_text(ring_payload.get('sender_name'), default='طرف آخر', max_length=120)
    conversation_id = ring_payload.get('conversation_id')
    chat_type = ring_payload.get('chat_type') or ''
    if not conversation_id and chat_type in {'shop_customer', 'driver_customer'}:
        conversation_id = f'order_{order.id}_{chat_type}'
    screen = 'chat' if chat_type in {'shop_customer', 'driver_customer'} else 'incoming_ring'
    route = '/chat' if screen == 'chat' else '/incoming-ring'

    return {
        'type': 'incoming_ring',
        'ring_id': ring_payload.get('ring_id') or '',
        'call_id': ring_payload.get('call_id') or ring_payload.get('ring_id') or '',
        'order_id': order.id,
        'order_number': order.order_number,
        'shop_id': order.shop_owner_id,
        'store_id': order.shop_owner_id,
        'shop_name': resolved_shop_name,
        'store_name': resolved_shop_name,
        'shop_profile_image_url': shop_profile_image_url or '',
        'target': target,
        'targets': ring_payload.get('targets') or ([target] if target else []),
        'chat_type': chat_type,
        'conversation_id': conversation_id or '',
        'sender_id': ring_payload.get('sender_id') or '',
        'sender_type': ring_payload.get('sender_type') or '',
        'sender_name': sender_name,
        'customer_id': getattr(customer, 'id', '') or '',
        'customer_name': customer_name,
        'driver_id': getattr(order, 'driver_id', '') or '',
        'driver_image_url': driver_image_url,
        'caller_name': ring_payload.get('caller_name') or sender_name,
        'notification_kind': ring_payload.get('notification_kind') or 'ring',
        'play_sound_on_frontend': ring_payload.get('play_sound_on_frontend', True),
        'created_at': ring_payload.get('created_at') or '',
        'screen': screen,
        'route': route,
        'click_action': 'OPEN_CHAT',
    }


def build_driver_customer_ring_payload(*, order, ring_payload):
    ring_payload = ring_payload or {}
    customer = getattr(order, 'customer', None)
    customer_name = _trim_text(
        ring_payload.get('customer_name') or ring_payload.get('sender_name') or getattr(customer, 'name', None),
        default='العميل',
        max_length=120,
    )
    profile = _driver_urgent_ring_profile()
    return {
        'type': 'driver_customer.call_ringing',
        'chat_type': 'driver_customer',
        'order_id': str(order.id),
        'customer_id': str(getattr(customer, 'id', '') or ''),
        'ring_id': str(ring_payload.get('ring_id') or ''),
        'conversation_id': str(ring_payload.get('conversation_id') or f'order_{order.id}_driver_customer'),
        'customer_name': customer_name,
        'title': f'{customer_name} يتصل بك',
        'body': 'اضغط لفتح محادثة العميل',
        'sound': profile['sound'],
        'channel_id': profile['channel_id'],
    }


def build_customer_driver_chat_ring_payload(*, order, ring_payload, shop_name=None, shop_profile_image_url=None):
    ring_payload = ring_payload or {}
    customer = getattr(order, 'customer', None)
    sender_name = _trim_text(
        ring_payload.get('sender_name') or getattr(order.driver, 'name', None),
        default='المندوب',
        max_length=120,
    )
    customer_name = _trim_text(getattr(customer, 'name', None), default='العميل', max_length=120)
    conversation_id = str(ring_payload.get('conversation_id') or f'order_{order.id}_driver_customer')
    profile = _customer_driver_chat_ring_profile()
    payload = build_incoming_ring_payload(
        order=order,
        ring_payload={
            **ring_payload,
            'conversation_id': conversation_id,
            'chat_type': 'driver_customer',
        },
        target='customer',
        shop_name=shop_name,
        shop_profile_image_url=shop_profile_image_url,
    )
    payload.update({
        'type': 'driver_customer.call_ringing',
        'chat_type': 'driver_customer',
        'order_id': str(order.id),
        'customer_id': str(getattr(customer, 'id', '') or ''),
        'customer_name': customer_name,
        'driver_id': str(getattr(order, 'driver_id', '') or ''),
        'driver_name': sender_name,
        'sender_type': ring_payload.get('sender_type') or 'driver',
        'sender_name': sender_name,
        'ring_id': str(ring_payload.get('ring_id') or ''),
        'call_id': str(ring_payload.get('call_id') or ring_payload.get('ring_id') or ''),
        'conversation_id': conversation_id,
        'title': f'{sender_name} يتصل بك',
        'body': 'اضغط لفتح محادثة المندوب',
        'sound': profile['sound'],
        'channel_id': profile['channel_id'],
        'screen': 'chat',
        'route': '/chat',
        'click_action': 'OPEN_CHAT',
    })
    return payload


def build_driver_shop_call_ringing_payload(*, conversation, call):
    shop_owner = getattr(conversation, 'shop_owner', None)
    profile = _driver_urgent_ring_profile()
    store_name = _trim_text(getattr(shop_owner, 'shop_name', None), default='Mr Delivery', max_length=120)
    return {
        'type': 'driver_chat.call_ringing',
        'chat_type': 'driver_store',
        'screen': 'chat',
        'route': '/driver-chats',
        'call_id': str(getattr(call, 'public_id', '') or ''),
        'conversation_id': str(getattr(conversation, 'public_id', '') or ''),
        'shop_id': str(getattr(shop_owner, 'id', '') or ''),
        'store_id': str(getattr(shop_owner, 'id', '') or ''),
        'store_name': store_name,
        'shop_name': store_name,
        'title': f'{store_name} يتصل بك',
        'body': 'اضغط لفتح محادثة المحل',
        'sound': profile['sound'],
        'channel_id': profile['channel_id'],
    }


def build_broadcast_payload(*, notification_type='broadcast', route='/notifications', extra_data=None):
    payload = {
        'type': notification_type,
        'route': route,
        'click_action': 'OPEN_NOTIFICATIONS',
    }
    payload.update(_stringify_payload(extra_data or {}))
    return payload
