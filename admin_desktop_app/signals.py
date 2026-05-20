from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver

from shop.models import ChatMessage, Order, ShopStatus
from user.models import ShopOwner

from .store_monitoring import broadcast_store_monitor_store_updated


def _broadcast_for_store(store_id):
    if store_id:
        broadcast_store_monitor_store_updated(store_id)


@receiver(post_save, sender=ChatMessage)
@receiver(post_delete, sender=ChatMessage)
def _store_monitor_chat_message_changed(sender, instance, **kwargs):
    _broadcast_for_store(getattr(instance.order, "shop_owner_id", None))


@receiver(post_save, sender=Order)
@receiver(post_delete, sender=Order)
def _store_monitor_order_changed(sender, instance, **kwargs):
    _broadcast_for_store(getattr(instance, "shop_owner_id", None))


@receiver(post_save, sender=ShopStatus)
@receiver(post_delete, sender=ShopStatus)
def _store_monitor_status_changed(sender, instance, **kwargs):
    _broadcast_for_store(getattr(instance, "shop_owner_id", None))


@receiver(post_save, sender=ShopOwner)
def _store_monitor_shop_changed(sender, instance, **kwargs):
    _broadcast_for_store(getattr(instance, "id", None))
