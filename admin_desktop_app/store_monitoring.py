from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.db.models import Count, F, Max, Min, OuterRef, Q, Subquery

from shop.models import ChatMessage, Order, ShopStatus
from shop.realtime.presence import format_utc_iso8601
from user.models import ShopOwner


STORE_MONITOR_GROUP = "admin_desktop_store_monitoring"
STORE_SIDE_SENDER_TYPES = ("shop_owner", "employee")


def store_monitor_group_name():
    return STORE_MONITOR_GROUP


def _is_store_online(status_value):
    return str(status_value or "").strip().lower() in {"open", "busy"}


def _latest_store_reply_subquery():
    return (
        ChatMessage.objects.filter(
            order_id=OuterRef("order_id"),
            chat_type="shop_customer",
            sender_type__in=STORE_SIDE_SENDER_TYPES,
        )
        .order_by("-created_at")
        .values("created_at")[:1]
    )


def _build_store_snapshot_map():
    stores = (
        ShopOwner.objects.select_related("shop_status")
        .all()
        .order_by("shop_name", "id")
    )

    pending_messages_qs = (
        ChatMessage.objects.filter(
            chat_type="shop_customer",
            sender_type="customer",
        )
        .annotate(last_store_reply_at=Subquery(_latest_store_reply_subquery()))
        .filter(
            Q(last_store_reply_at__isnull=True)
            | Q(created_at__gt=F("last_store_reply_at"))
        )
    )

    pending_messages_by_store = {
        item["order__shop_owner_id"]: item
        for item in pending_messages_qs.values("order__shop_owner_id").annotate(
            unanswered_messages=Count("id"),
            oldest_pending_message_at=Min("created_at"),
            last_message_activity_at=Max("created_at"),
        )
    }
    pending_orders_by_store = {
        item["shop_owner_id"]: item
        for item in Order.objects.filter(status="new").values("shop_owner_id").annotate(
            unanswered_orders=Count("id"),
            oldest_pending_order_at=Min("created_at"),
            last_pending_order_activity_at=Max("updated_at"),
        )
    }
    order_activity_by_store = {
        item["shop_owner_id"]: item["last_order_activity_at"]
        for item in Order.objects.values("shop_owner_id").annotate(
            last_order_activity_at=Max("updated_at")
        )
    }
    message_activity_by_store = {
        item["order__shop_owner_id"]: item["last_message_activity_at"]
        for item in ChatMessage.objects.filter(chat_type="shop_customer")
        .values("order__shop_owner_id")
        .annotate(last_message_activity_at=Max("created_at"))
    }
    status_activity_by_store = {
        item["shop_owner_id"]: item["last_status_activity_at"]
        for item in ShopStatus.objects.values("shop_owner_id").annotate(
            last_status_activity_at=Max("updated_at")
        )
    }

    snapshot_map = {}
    for store in stores:
        message_stats = pending_messages_by_store.get(store.id, {})
        order_stats = pending_orders_by_store.get(store.id, {})
        unanswered_messages = int(message_stats.get("unanswered_messages") or 0)
        unanswered_orders = int(order_stats.get("unanswered_orders") or 0)
        total_pending = unanswered_messages + unanswered_orders

        oldest_candidates = [
            message_stats.get("oldest_pending_message_at"),
            order_stats.get("oldest_pending_order_at"),
        ]
        oldest_pending_at = min(
            [value for value in oldest_candidates if value is not None],
            default=None,
        )

        last_activity_candidates = [
            getattr(store, "updated_at", None),
            order_activity_by_store.get(store.id),
            message_activity_by_store.get(store.id),
            status_activity_by_store.get(store.id),
        ]
        last_activity_at = max(
            [value for value in last_activity_candidates if value is not None],
            default=None,
        )

        status_obj = getattr(store, "shop_status", None)
        snapshot_map[store.id] = {
            "store_id": store.id,
            "store_name": store.shop_name,
            "owner_name": store.owner_name,
            "phone": store.phone_number,
            "is_online": _is_store_online(getattr(status_obj, "status", None)),
            "unanswered_messages": unanswered_messages,
            "unanswered_orders": unanswered_orders,
            "total_pending": total_pending,
            "oldest_pending_at": format_utc_iso8601(oldest_pending_at) if total_pending else None,
            "last_activity_at": format_utc_iso8601(last_activity_at) if last_activity_at else None,
        }
    return snapshot_map


def get_store_monitoring_snapshot(*, store_id=None):
    snapshot_map = _build_store_snapshot_map()
    if store_id is not None:
        return snapshot_map.get(store_id)
    stores = sorted(
        snapshot_map.values(),
        key=lambda item: (-int(item["total_pending"]), item["store_name"] or "", int(item["store_id"])),
    )
    return {"stores": stores}


def _group_send(payload):
    channel_layer = get_channel_layer()
    if not channel_layer:
        return
    async_to_sync(channel_layer.group_send)(
        store_monitor_group_name(),
        {
            "type": "store_monitor_event",
            "payload": payload,
        },
    )


def broadcast_store_monitor_snapshot():
    _group_send(
        {
            "type": "store_monitor.snapshot",
            "data": get_store_monitoring_snapshot(),
        }
    )


def broadcast_store_monitor_store_updated(store_id):
    store_snapshot = get_store_monitoring_snapshot(store_id=store_id)
    if not store_snapshot:
        return
    _group_send(
        {
            "type": "store_monitor.store_updated",
            "data": {
                "store": store_snapshot,
            },
        }
    )
