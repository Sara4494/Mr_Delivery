from rest_framework import serializers

from user.utils import build_absolute_file_url, localize_message

from ..models import ChatMessage, CustomerSupportConversation, Order
from .presence import format_utc_iso8601
from ..serializers import _order_items_to_representation


CUSTOMER_ACTIVE_ORDER_STATUSES = frozenset(
    {
        'new',
        'pending_customer_confirm',
        'confirmed',
        'preparing',
        'on_way',
    }
)

CUSTOMER_ON_WAY_ORDER_STATUSES = frozenset(
    {
        'confirmed',
        'preparing',
        'on_way',
    }
)

CUSTOMER_ORDER_CHAT_TYPE = 'shop_customer'
CUSTOMER_SUPPORT_CHAT_TYPE = 'support_customer'
CUSTOMER_DRIVER_CHAT_TYPE = 'driver_customer'

SHOP_ORDER_MESSAGES_ATTR = 'customer_app_shop_messages_desc'
SUPPORT_MESSAGES_ATTR = 'customer_app_support_messages_desc'


def is_customer_active_order(order):
    return order.status in CUSTOMER_ACTIVE_ORDER_STATUSES


def is_customer_on_way_order(order):
    return order.status in CUSTOMER_ON_WAY_ORDER_STATUSES


def get_order_shop_messages(order):
    prefetched_messages = getattr(order, SHOP_ORDER_MESSAGES_ATTR, None)
    if prefetched_messages is not None:
        return prefetched_messages

    return list(
        order.messages.filter(chat_type=CUSTOMER_ORDER_CHAT_TYPE)
        .select_related(
            'sender_customer',
            'sender_shop_owner',
            'sender_employee',
            'sender_driver',
        )
        .order_by('-created_at')
    )


def get_support_messages(conversation):
    prefetched_messages = getattr(conversation, SUPPORT_MESSAGES_ATTR, None)
    if prefetched_messages is not None:
        return prefetched_messages

    return list(
        conversation.messages.select_related(
            'sender_customer',
            'sender_shop_owner',
            'sender_employee',
        ).order_by('-created_at')
    )


def get_latest_order_shop_message(order):
    messages = get_order_shop_messages(order)
    return messages[0] if messages else None


def get_latest_support_message(conversation):
    messages = get_support_messages(conversation)
    return messages[0] if messages else None


def get_order_customer_unread_count(order):
    return sum(
        1
        for message in get_order_shop_messages(order)
        if not message.is_read and message.sender_type != 'customer'
    )


def get_support_customer_unread_count(conversation):
    return int(conversation.unread_for_customer_count or 0)


def get_order_shop_interaction_at(order):
    latest_message = get_latest_order_shop_message(order)
    return getattr(latest_message, 'created_at', None) or order.created_at


def get_support_interaction_at(conversation):
    return conversation.last_message_at or conversation.created_at


def get_order_sort_key(order):
    latest_message = get_latest_order_shop_message(order)
    candidates = [order.updated_at, order.created_at]
    if latest_message and latest_message.created_at:
        candidates.append(latest_message.created_at)
    return max(candidate for candidate in candidates if candidate is not None)


def get_on_way_sort_key(order):
    candidates = [order.updated_at, order.created_at]
    driver = getattr(order, 'driver', None)
    if driver and driver.location_updated_at:
        candidates.append(driver.location_updated_at)
    return max(candidate for candidate in candidates if candidate is not None)


def get_history_ordered_at_for_order(order):
    return order.created_at


def get_history_ordered_at_for_support(conversation):
    return conversation.created_at


def get_support_history_chat_status(conversation):
    latest_message = get_latest_support_message(conversation)
    if latest_message and latest_message.sender_type != 'customer':
        return 'answered'
    return 'waiting_reply'


def get_support_history_chat_status_display(conversation):
    status_key = get_support_history_chat_status(conversation)
    return {
        'waiting_reply': 'بانتظار الرد',
        'answered': 'تم الرد',
    }.get(status_key, status_key)


def get_order_history_status(order):
    if order.status == 'delivered':
        return 'delivered'
    if order.status == 'cancelled':
        return 'cancelled'
    return 'in_progress'


def _context_file_url(serializer, file_field):
    return build_absolute_file_url(
        file_field,
        request=serializer.context.get('request'),
        scope=serializer.context.get('scope'),
        base_url=serializer.context.get('base_url'),
    )


def _localized_content(serializer, content):
    return localize_message(
        serializer.context.get('request'),
        content,
        lang=serializer.context.get('lang'),
    )


def _build_message_preview(serializer, *, message_type, content):
    localized_content = _localized_content(serializer, content)
    localized_content = str(localized_content or '').strip()
    if localized_content:
        return localized_content

    return {
        'audio': 'رسالة صوتية',
        'image': 'صورة',
        'location': 'موقع',
        'text': '',
    }.get(message_type, '')


def _normalize_item(item):
    if isinstance(item, dict):
        quantity = item.get('quantity')
        if quantity in (None, ''):
            quantity = item.get('qty')
        if quantity in (None, ''):
            quantity = 1
        try:
            quantity = int(quantity)
        except (TypeError, ValueError):
            quantity = 1
        quantity = max(quantity, 1)

        name = (
            item.get('name')
            or item.get('title')
            or item.get('product_name')
            or item.get('item')
            or item.get('label')
            or ''
        )
        name = str(name or '').strip()
        if not name:
            name = 'Item'
        return quantity, name

    item_text = str(item or '').strip()
    if not item_text:
        return 0, ''
    return 1, item_text


def build_items_summary_and_count(order):
    raw_items = _order_items_to_representation(order.items)
    count = 0
    parts = []

    for item in raw_items:
        quantity, name = _normalize_item(item)
        if quantity <= 0 or not name:
            continue
        count += quantity
        parts.append(f'{quantity}x {name}')

    return ', '.join(parts), count


class CustomerAppRealtimeOrderMessageSerializer(serializers.ModelSerializer):
    sender_name = serializers.CharField(read_only=True)
    created_at = serializers.SerializerMethodField()
    content = serializers.SerializerMethodField()

    class Meta:
        model = ChatMessage
        fields = [
            'id',
            'chat_type',
            'sender_type',
            'sender_name',
            'message_type',
            'content',
            'is_read',
            'created_at',
        ]
        read_only_fields = fields

    def get_content(self, obj):
        return _build_message_preview(
            self,
            message_type=obj.message_type,
            content=obj.content,
        )

    def get_created_at(self, obj):
        return format_utc_iso8601(obj.created_at)


class CustomerAppRealtimeOrderSerializer(serializers.ModelSerializer):
    shop_id = serializers.IntegerField(source='shop_owner_id', read_only=True)
    shop_name = serializers.CharField(source='shop_owner.shop_name', read_only=True)
    shop_logo_url = serializers.SerializerMethodField()
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    item_count = serializers.SerializerMethodField()
    items_summary = serializers.SerializerMethodField()
    total_amount = serializers.SerializerMethodField()
    delivery_fee = serializers.SerializerMethodField()
    notes = serializers.SerializerMethodField()
    unread_messages_count = serializers.SerializerMethodField()
    has_unread_messages = serializers.SerializerMethodField()
    chat = serializers.SerializerMethodField()
    last_message = serializers.SerializerMethodField()
    created_at = serializers.SerializerMethodField()
    updated_at = serializers.SerializerMethodField()

    class Meta:
        model = Order
        fields = [
            'id',
            'order_number',
            'shop_id',
            'shop_name',
            'shop_logo_url',
            'status',
            'status_display',
            'items_summary',
            'item_count',
            'total_amount',
            'delivery_fee',
            'address',
            'notes',
            'unread_messages_count',
            'has_unread_messages',
            'chat',
            'last_message',
            'created_at',
            'updated_at',
        ]
        read_only_fields = fields

    def get_shop_logo_url(self, obj):
        return _context_file_url(self, getattr(obj.shop_owner, 'profile_image', None))

    def get_item_count(self, obj):
        return build_items_summary_and_count(obj)[1]

    def get_items_summary(self, obj):
        return build_items_summary_and_count(obj)[0]

    def get_total_amount(self, obj):
        return str(obj.total_amount) if obj.total_amount is not None else None

    def get_delivery_fee(self, obj):
        return str(obj.delivery_fee) if obj.delivery_fee is not None else None

    def get_notes(self, obj):
        return str(obj.notes or '')

    def get_unread_messages_count(self, obj):
        return get_order_customer_unread_count(obj)

    def get_has_unread_messages(self, obj):
        return self.get_unread_messages_count(obj) > 0

    def get_chat(self, obj):
        return {
            'thread_id': str(obj.id),
            'order_id': obj.id,
            'chat_type': CUSTOMER_ORDER_CHAT_TYPE,
            'shop_id': obj.shop_owner_id,
        }

    def get_last_message(self, obj):
        latest_message = get_latest_order_shop_message(obj)
        if not latest_message:
            return None
        return CustomerAppRealtimeOrderMessageSerializer(
            latest_message,
            context=self.context,
        ).data

    def get_created_at(self, obj):
        return format_utc_iso8601(obj.created_at)

    def get_updated_at(self, obj):
        return format_utc_iso8601(obj.updated_at)


class CustomerAppRealtimeOrderShopEntrySerializer(serializers.ModelSerializer):
    shop_id = serializers.IntegerField(source='shop_owner_id', read_only=True)
    shop_name = serializers.CharField(source='shop_owner.shop_name', read_only=True)
    shop_logo_url = serializers.SerializerMethodField()
    subtitle = serializers.SerializerMethodField()
    last_message_preview = serializers.SerializerMethodField()
    updated_at = serializers.SerializerMethodField()
    unread_messages_count = serializers.SerializerMethodField()
    has_unread_messages = serializers.SerializerMethodField()
    chat = serializers.SerializerMethodField()

    class Meta:
        model = Order
        fields = [
            'shop_id',
            'shop_name',
            'shop_logo_url',
            'subtitle',
            'last_message_preview',
            'updated_at',
            'unread_messages_count',
            'has_unread_messages',
            'chat',
        ]
        read_only_fields = fields

    def get_shop_logo_url(self, obj):
        return _context_file_url(self, getattr(obj.shop_owner, 'profile_image', None))

    def get_last_message_preview(self, obj):
        latest_message = get_latest_order_shop_message(obj)
        if latest_message:
            return CustomerAppRealtimeOrderMessageSerializer(
                latest_message,
                context=self.context,
            ).data.get('content')
        return obj.get_status_display()

    def get_subtitle(self, obj):
        return self.get_last_message_preview(obj)

    def get_updated_at(self, obj):
        return format_utc_iso8601(get_order_shop_interaction_at(obj))

    def get_unread_messages_count(self, obj):
        return get_order_customer_unread_count(obj)

    def get_has_unread_messages(self, obj):
        return self.get_unread_messages_count(obj) > 0

    def get_chat(self, obj):
        return {
            'thread_id': str(obj.id),
            'order_id': obj.id,
            'chat_type': CUSTOMER_ORDER_CHAT_TYPE,
            'shop_id': obj.shop_owner_id,
        }


class CustomerAppRealtimeSupportConversationSerializer(serializers.ModelSerializer):
    support_conversation_id = serializers.CharField(source='public_id', read_only=True)
    conversation_type_display = serializers.CharField(
        source='get_conversation_type_display',
        read_only=True,
    )
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    shop_id = serializers.IntegerField(source='shop_owner_id', read_only=True)
    shop_name = serializers.CharField(source='shop_owner.shop_name', read_only=True)
    shop_logo_url = serializers.SerializerMethodField()
    customer_id = serializers.IntegerField(read_only=True)
    subtitle = serializers.SerializerMethodField()
    last_message_preview = serializers.SerializerMethodField()
    last_message_at = serializers.SerializerMethodField()
    unread_for_customer_count = serializers.IntegerField(read_only=True)
    unread_for_shop_count = serializers.IntegerField(read_only=True)
    created_at = serializers.SerializerMethodField()
    updated_at = serializers.SerializerMethodField()
    chat = serializers.SerializerMethodField()

    class Meta:
        model = CustomerSupportConversation
        fields = [
            'support_conversation_id',
            'conversation_type',
            'conversation_type_display',
            'status',
            'status_display',
            'shop_id',
            'shop_name',
            'shop_logo_url',
            'customer_id',
            'subtitle',
            'last_message_preview',
            'last_message_at',
            'unread_for_customer_count',
            'unread_for_shop_count',
            'created_at',
            'updated_at',
            'chat',
        ]
        read_only_fields = fields

    def get_shop_logo_url(self, obj):
        return _context_file_url(self, getattr(obj.shop_owner, 'profile_image', None))

    def get_subtitle(self, obj):
        return self.get_last_message_preview(obj) or obj.get_conversation_type_display()

    def get_last_message_preview(self, obj):
        preview = str(obj.last_message_preview or '').strip()
        if preview:
            return _localized_content(self, preview)
        return obj.get_conversation_type_display()

    def get_last_message_at(self, obj):
        return format_utc_iso8601(obj.last_message_at or obj.created_at)

    def get_created_at(self, obj):
        return format_utc_iso8601(obj.created_at)

    def get_updated_at(self, obj):
        return format_utc_iso8601(obj.updated_at)

    def get_chat(self, obj):
        return {
            'thread_id': obj.public_id,
            'support_conversation_id': obj.public_id,
            'order_id': None,
            'chat_type': CUSTOMER_SUPPORT_CHAT_TYPE,
            'conversation_type': obj.conversation_type,
            'shop_id': obj.shop_owner_id,
        }


class CustomerAppRealtimeSupportShopEntrySerializer(serializers.ModelSerializer):
    shop_id = serializers.IntegerField(source='shop_owner_id', read_only=True)
    shop_name = serializers.CharField(source='shop_owner.shop_name', read_only=True)
    shop_logo_url = serializers.SerializerMethodField()
    subtitle = serializers.SerializerMethodField()
    last_message_preview = serializers.SerializerMethodField()
    updated_at = serializers.SerializerMethodField()
    unread_messages_count = serializers.SerializerMethodField()
    has_unread_messages = serializers.SerializerMethodField()
    chat = serializers.SerializerMethodField()
    support_conversation = serializers.SerializerMethodField()

    class Meta:
        model = CustomerSupportConversation
        fields = [
            'shop_id',
            'shop_name',
            'shop_logo_url',
            'subtitle',
            'last_message_preview',
            'updated_at',
            'unread_messages_count',
            'has_unread_messages',
            'chat',
            'support_conversation',
        ]
        read_only_fields = fields

    def get_shop_logo_url(self, obj):
        return _context_file_url(self, getattr(obj.shop_owner, 'profile_image', None))

    def get_subtitle(self, obj):
        return CustomerAppRealtimeSupportConversationSerializer(
            obj,
            context=self.context,
        ).data.get('subtitle')

    def get_last_message_preview(self, obj):
        return CustomerAppRealtimeSupportConversationSerializer(
            obj,
            context=self.context,
        ).data.get('last_message_preview')

    def get_updated_at(self, obj):
        return format_utc_iso8601(get_support_interaction_at(obj))

    def get_unread_messages_count(self, obj):
        return get_support_customer_unread_count(obj)

    def get_has_unread_messages(self, obj):
        return self.get_unread_messages_count(obj) > 0

    def get_chat(self, obj):
        return CustomerAppRealtimeSupportConversationSerializer(
            obj,
            context=self.context,
        ).data.get('chat')

    def get_support_conversation(self, obj):
        return CustomerAppRealtimeSupportConversationSerializer(
            obj,
            context=self.context,
        ).data


class CustomerAppRealtimeOnWaySerializer(serializers.ModelSerializer):
    order_id = serializers.IntegerField(source='id', read_only=True)
    shop_id = serializers.IntegerField(source='shop_owner_id', read_only=True)
    shop_name = serializers.CharField(source='shop_owner.shop_name', read_only=True)
    shop_logo_url = serializers.SerializerMethodField()
    driver_id = serializers.IntegerField(read_only=True)
    driver_name = serializers.CharField(source='driver.name', read_only=True)
    driver_image_url = serializers.SerializerMethodField()
    driver_role_label = serializers.SerializerMethodField()
    status_key = serializers.CharField(source='status', read_only=True)
    status_label = serializers.CharField(source='get_status_display', read_only=True)
    last_delivery_update_at = serializers.SerializerMethodField()
    chat = serializers.SerializerMethodField()

    class Meta:
        model = Order
        fields = [
            'order_id',
            'order_number',
            'shop_id',
            'shop_name',
            'shop_logo_url',
            'driver_id',
            'driver_name',
            'driver_image_url',
            'driver_role_label',
            'status_key',
            'status_label',
            'last_delivery_update_at',
            'chat',
        ]
        read_only_fields = fields

    def get_shop_logo_url(self, obj):
        return _context_file_url(self, getattr(obj.shop_owner, 'profile_image', None))

    def get_driver_image_url(self, obj):
        driver = getattr(obj, 'driver', None)
        return _context_file_url(self, getattr(driver, 'profile_image', None)) if driver else None

    def get_driver_role_label(self, obj):
        return 'مندوب' if obj.driver_id else None

    def get_last_delivery_update_at(self, obj):
        return format_utc_iso8601(get_on_way_sort_key(obj))

    def get_chat(self, obj):
        return {
            'thread_id': f'delivery_{obj.id}',
            'order_id': obj.id,
            'chat_type': CUSTOMER_DRIVER_CHAT_TYPE,
            'can_open': bool(getattr(obj, 'driver_accepted_at', None)),
        }


class CustomerAppRealtimeOrderHistoryOrderEntrySerializer(serializers.ModelSerializer):
    id = serializers.SerializerMethodField()
    entry_type = serializers.SerializerMethodField()
    ordered_at = serializers.SerializerMethodField()
    shop_id = serializers.IntegerField(source='shop_owner_id', read_only=True)
    store_name = serializers.CharField(source='shop_owner.shop_name', read_only=True)
    shop_logo_url = serializers.SerializerMethodField()
    has_unread_messages = serializers.SerializerMethodField()
    order = serializers.SerializerMethodField()

    class Meta:
        model = Order
        fields = [
            'id',
            'entry_type',
            'ordered_at',
            'shop_id',
            'store_name',
            'shop_logo_url',
            'has_unread_messages',
            'order',
        ]
        read_only_fields = fields

    def get_id(self, obj):
        return f'order_{obj.id}'

    def get_entry_type(self, obj):
        return 'order'

    def get_ordered_at(self, obj):
        return format_utc_iso8601(get_history_ordered_at_for_order(obj))

    def get_shop_logo_url(self, obj):
        return _context_file_url(self, getattr(obj.shop_owner, 'profile_image', None))

    def get_has_unread_messages(self, obj):
        return get_order_customer_unread_count(obj) > 0

    def get_order(self, obj):
        items_summary, item_count = build_items_summary_and_count(obj)
        return {
            'order_id': obj.id,
            'order_number': obj.order_number,
            'items_summary': items_summary,
            'item_count': item_count,
            'total_amount': str(obj.total_amount) if obj.total_amount is not None else None,
            'status_key': obj.status,
            'status_label': obj.get_status_display(),
            'history_status': get_order_history_status(obj),
            'chat_type': CUSTOMER_ORDER_CHAT_TYPE,
        }


class CustomerAppRealtimeOrderHistoryChatEntrySerializer(serializers.ModelSerializer):
    id = serializers.CharField(source='public_id', read_only=True)
    entry_type = serializers.SerializerMethodField()
    ordered_at = serializers.SerializerMethodField()
    shop_id = serializers.IntegerField(source='shop_owner_id', read_only=True)
    store_name = serializers.CharField(source='shop_owner.shop_name', read_only=True)
    shop_logo_url = serializers.SerializerMethodField()
    has_unread_messages = serializers.SerializerMethodField()
    chat = serializers.SerializerMethodField()

    class Meta:
        model = CustomerSupportConversation
        fields = [
            'id',
            'entry_type',
            'ordered_at',
            'shop_id',
            'store_name',
            'shop_logo_url',
            'has_unread_messages',
            'chat',
        ]
        read_only_fields = fields

    def get_entry_type(self, obj):
        return 'chat'

    def get_ordered_at(self, obj):
        return format_utc_iso8601(get_history_ordered_at_for_support(obj))

    def get_shop_logo_url(self, obj):
        return _context_file_url(self, getattr(obj.shop_owner, 'profile_image', None))

    def get_has_unread_messages(self, obj):
        return get_support_customer_unread_count(obj) > 0

    def get_chat(self, obj):
        preview = CustomerAppRealtimeSupportConversationSerializer(
            obj,
            context=self.context,
        ).data.get('last_message_preview')
        return {
            'support_conversation_id': obj.public_id,
            'chat_type': CUSTOMER_SUPPORT_CHAT_TYPE,
            'conversation_type': obj.conversation_type,
            'conversation_type_display': obj.get_conversation_type_display(),
            'chat_status': get_support_history_chat_status(obj),
            'chat_status_display': get_support_history_chat_status_display(obj),
            'title': obj.get_conversation_type_display(),
            'preview': preview,
            'order_id': None,
            'order_number': None,
        }
