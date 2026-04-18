from rest_framework import serializers

from user.models import ShopOwner
from user.utils import build_absolute_file_url

from ..models import (
    CustomerSupportConversation,
    CustomerSupportMessage,
    ShopSupportTicket,
    ShopSupportTicketMessage,
)
from ..realtime.presence import format_utc_iso8601


def _context_file_url(serializer, file_field):
    return build_absolute_file_url(
        file_field,
        request=serializer.context.get('request'),
        scope=serializer.context.get('scope'),
        base_url=serializer.context.get('base_url'),
    )


class CustomerSupportMessageSerializer(serializers.ModelSerializer):
    sender_type_display = serializers.CharField(source='get_sender_type_display', read_only=True)
    message_type_display = serializers.CharField(source='get_message_type_display', read_only=True)
    sender_name = serializers.CharField(read_only=True)
    sender_id = serializers.SerializerMethodField()
    customer_profile_image_url = serializers.SerializerMethodField()
    support_conversation_id = serializers.CharField(source='conversation.public_id', read_only=True)
    thread_id = serializers.CharField(source='conversation.public_id', read_only=True)
    chat_type = serializers.SerializerMethodField()
    conversation_type = serializers.CharField(source='conversation.conversation_type', read_only=True)
    conversation_type_display = serializers.CharField(source='conversation.get_conversation_type_display', read_only=True)
    audio_file_url = serializers.SerializerMethodField()
    image_file_url = serializers.SerializerMethodField()
    content = serializers.SerializerMethodField()

    class Meta:
        model = CustomerSupportMessage
        fields = [
            'id',
            'support_conversation_id',
            'thread_id',
            'chat_type',
            'conversation_type',
            'conversation_type_display',
            'sender_type',
            'sender_type_display',
            'sender_name',
            'sender_id',
            'customer_profile_image_url',
            'message_type',
            'message_type_display',
            'content',
            'audio_file',
            'audio_file_url',
            'image_file',
            'image_file_url',
            'latitude',
            'longitude',
            'is_read',
            'created_at',
        ]
        read_only_fields = ['id', 'created_at']

    def get_chat_type(self, obj):
        return 'support_customer'

    def get_content(self, obj):
        from user.utils import localize_message

        request = self.context.get('request')
        lang = self.context.get('lang')
        return localize_message(request, obj.content, lang=lang)

    def get_sender_id(self, obj):
        if obj.sender_type == 'customer' and obj.sender_customer:
            return obj.sender_customer.id
        if obj.sender_type == 'shop_owner' and obj.sender_shop_owner:
            return obj.sender_shop_owner.id
        if obj.sender_type == 'employee' and obj.sender_employee:
            return obj.sender_employee.id
        return None

    def get_customer_profile_image_url(self, obj):
        customer = getattr(getattr(obj, 'conversation', None), 'customer', None)
        if not customer or not customer.profile_image:
            return None
        return _context_file_url(self, customer.profile_image)

    def get_audio_file_url(self, obj):
        if obj.audio_file:
            return _context_file_url(self, obj.audio_file)
        return None

    def get_image_file_url(self, obj):
        if obj.image_file:
            return _context_file_url(self, obj.image_file)
        return None


class CustomerSupportConversationCreateSerializer(serializers.Serializer):
    """Create a standalone customer support chat with a shop."""

    conversation_type = serializers.ChoiceField(choices=CustomerSupportConversation.CONVERSATION_TYPE_CHOICES)
    initial_message = serializers.CharField(required=False, allow_blank=True, write_only=True)
    shop_owner_id = serializers.IntegerField(required=False, allow_null=True, write_only=True)
    shop_id = serializers.IntegerField(required=False, allow_null=True, write_only=True)
    id = serializers.IntegerField(required=False, allow_null=True, write_only=True)
    shop_number = serializers.CharField(required=False, allow_blank=True, write_only=True)

    def validate(self, attrs):
        customer = self.context['customer']
        requested_shop_id = attrs.get('shop_owner_id') or attrs.get('shop_id') or attrs.get('id')
        requested_shop_number = str(attrs.get('shop_number') or '').strip()

        shop_owner = None
        if requested_shop_id:
            shop_owner = ShopOwner.objects.filter(id=requested_shop_id, is_active=True).first()
            if not shop_owner:
                raise serializers.ValidationError({'shop': 'المحل غير موجود'})
        elif requested_shop_number:
            shop_owner = ShopOwner.objects.filter(shop_number=requested_shop_number, is_active=True).first()
            if not shop_owner:
                raise serializers.ValidationError({'shop': 'المحل غير موجود'})
        else:
            shop_owner = getattr(customer, 'shop_owner', None)

        if not shop_owner:
            raise serializers.ValidationError({
                'shop': 'العميل غير مرتبط بمحل. يرجى اختيار المحل أولاً أو إرسال shop_owner_id.'
            })

        attrs['resolved_shop_owner'] = shop_owner
        return attrs

    def create(self, validated_data):
        customer = self.context['customer']
        shop_owner = validated_data.pop('resolved_shop_owner', None) or getattr(customer, 'shop_owner', None)
        validated_data.pop('shop_owner_id', None)
        validated_data.pop('shop_id', None)
        validated_data.pop('id', None)
        validated_data.pop('shop_number', None)

        if not shop_owner:
            raise serializers.ValidationError({
                'shop': 'العميل غير مرتبط بمحل. يرجى اختيار المحل أولاً أو إرسال shop_owner_id.'
            })

        if customer.shop_owner_id != shop_owner.id:
            customer.shop_owner = shop_owner
            customer.save(update_fields=['shop_owner'])

        return CustomerSupportConversation.objects.create(
            shop_owner=shop_owner,
            customer=customer,
            conversation_type=validated_data['conversation_type'],
        )


class CustomerSupportConversationSerializer(serializers.ModelSerializer):
    support_conversation_id = serializers.CharField(source='public_id', read_only=True)
    conversation_type_display = serializers.CharField(source='get_conversation_type_display', read_only=True)
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    shop_id = serializers.IntegerField(source='shop_owner.id', read_only=True)
    shop_name = serializers.CharField(source='shop_owner.shop_name', read_only=True)
    shop_logo_url = serializers.SerializerMethodField()
    customer_id = serializers.IntegerField(source='customer.id', read_only=True)
    customer_name = serializers.CharField(source='customer.name', read_only=True)
    customer_profile_image_url = serializers.SerializerMethodField()
    customer = serializers.SerializerMethodField()
    subtitle = serializers.SerializerMethodField()
    last_message_preview = serializers.SerializerMethodField()
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
            'customer_name',
            'customer_profile_image_url',
            'customer',
            'subtitle',
            'last_message_preview',
            'last_message_at',
            'unread_for_customer_count',
            'unread_for_shop_count',
            'created_at',
            'updated_at',
            'chat',
        ]

    def get_shop_logo_url(self, obj):
        return build_absolute_file_url(
            getattr(obj.shop_owner, 'profile_image', None),
            request=self.context.get('request'),
            scope=self.context.get('scope'),
            base_url=self.context.get('base_url'),
        )

    def get_customer_profile_image_url(self, obj):
        return build_absolute_file_url(
            getattr(obj.customer, 'profile_image', None),
            request=self.context.get('request'),
            scope=self.context.get('scope'),
            base_url=self.context.get('base_url'),
        )

    def get_customer(self, obj):
        customer = getattr(obj, 'customer', None)
        if not customer:
            return None

        return {
            'id': customer.id,
            'name': customer.name,
            'phone_number': customer.phone_number,
            'profile_image_url': self.get_customer_profile_image_url(obj),
            'is_online': bool(customer.is_online),
            'last_seen': format_utc_iso8601(customer.last_seen),
        }

    def get_last_message_preview(self, obj):
        from user.utils import localize_message

        request = self.context.get('request')
        lang = self.context.get('lang')
        return localize_message(request, obj.last_message_preview, lang=lang)

    def get_subtitle(self, obj):
        preview = self.get_last_message_preview(obj)
        if preview:
            return preview
        return f"{obj.get_conversation_type_display()} مفتوح"

    def get_chat(self, obj):
        return {
            'thread_id': obj.public_id,
            'support_conversation_id': obj.public_id,
            'chat_type': 'support_customer',
            'conversation_type': obj.conversation_type,
            'shop_id': obj.shop_owner_id,
        }


class ShopSupportTicketMessageSerializer(serializers.ModelSerializer):
    sender_type_display = serializers.CharField(source='get_sender_type_display', read_only=True)
    message_type_display = serializers.CharField(source='get_message_type_display', read_only=True)
    sender_name = serializers.CharField(read_only=True)
    sender_id = serializers.SerializerMethodField()
    ticket_id = serializers.CharField(source='ticket.public_id', read_only=True)
    thread_id = serializers.CharField(source='ticket.public_id', read_only=True)
    created_at = serializers.SerializerMethodField()

    class Meta:
        model = ShopSupportTicketMessage
        fields = [
            'id',
            'ticket_id',
            'thread_id',
            'sender_type',
            'sender_type_display',
            'sender_name',
            'sender_id',
            'message_type',
            'message_type_display',
            'content',
            'image_url',
            'audio_url',
            'latitude',
            'longitude',
            'metadata',
            'is_read',
            'created_at',
        ]
        read_only_fields = ['id']

    def get_sender_id(self, obj):
        if obj.sender_type == 'shop_owner' and obj.sender_shop_owner_id:
            return obj.sender_shop_owner_id
        if obj.sender_type == 'employee' and obj.sender_employee_id:
            return obj.sender_employee_id
        if obj.sender_type == 'admin_desktop' and obj.sender_admin_id:
            return obj.sender_admin_id
        return None

    def get_created_at(self, obj):
        return format_utc_iso8601(obj.created_at)


class ShopSupportTicketSerializer(serializers.ModelSerializer):
    ticket_id = serializers.CharField(source='public_id', read_only=True)
    priority_display = serializers.CharField(source='get_priority_display', read_only=True)
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    shop = serializers.SerializerMethodField()
    created_by = serializers.SerializerMethodField()
    assigned_admin = serializers.SerializerMethodField()
    created_at = serializers.SerializerMethodField()
    updated_at = serializers.SerializerMethodField()
    last_message_at = serializers.SerializerMethodField()
    resolved_at = serializers.SerializerMethodField()
    closed_at = serializers.SerializerMethodField()
    chat = serializers.SerializerMethodField()

    class Meta:
        model = ShopSupportTicket
        fields = [
            'ticket_id',
            'subject',
            'priority',
            'priority_display',
            'status',
            'status_display',
            'shop',
            'created_by',
            'assigned_admin',
            'unread_for_shop_count',
            'unread_for_admin_count',
            'last_message_preview',
            'last_message_at',
            'resolved_at',
            'closed_at',
            'created_at',
            'updated_at',
            'chat',
        ]

    def get_shop(self, obj):
        return {
            'id': obj.shop_owner_id,
            'shop_name': getattr(obj.shop_owner, 'shop_name', None),
            'shop_number': getattr(obj.shop_owner, 'shop_number', None),
            'owner_name': getattr(obj.shop_owner, 'owner_name', None),
            'profile_image_url': build_absolute_file_url(
                getattr(obj.shop_owner, 'profile_image', None),
                request=self.context.get('request'),
                scope=self.context.get('scope'),
                base_url=self.context.get('base_url'),
            ),
        }

    def get_created_by(self, obj):
        if obj.created_by_employee_id:
            return {
                'type': 'employee',
                'id': obj.created_by_employee_id,
                'name': getattr(obj.created_by_employee, 'name', None),
            }
        return {
            'type': 'shop_owner',
            'id': obj.shop_owner_id,
            'name': getattr(obj.shop_owner, 'owner_name', None),
        }

    def get_assigned_admin(self, obj):
        if not obj.assigned_admin_id:
            return None
        return {
            'id': obj.assigned_admin_id,
            'name': getattr(obj.assigned_admin, 'name', None),
            'role': getattr(obj.assigned_admin, 'role', None),
            'role_display': obj.assigned_admin.get_role_display() if getattr(obj, 'assigned_admin', None) else None,
            'profile_image_url': build_absolute_file_url(
                getattr(obj.assigned_admin, 'profile_image', None),
                request=self.context.get('request'),
                scope=self.context.get('scope'),
                base_url=self.context.get('base_url'),
            ),
        }

    def get_last_message_at(self, obj):
        return format_utc_iso8601(obj.last_message_at)

    def get_created_at(self, obj):
        return format_utc_iso8601(obj.created_at)

    def get_updated_at(self, obj):
        return format_utc_iso8601(obj.updated_at)

    def get_resolved_at(self, obj):
        return format_utc_iso8601(obj.resolved_at)

    def get_closed_at(self, obj):
        return format_utc_iso8601(obj.closed_at)

    def get_chat(self, obj):
        return {
            'thread_id': obj.public_id,
            'ticket_id': obj.public_id,
            'chat_type': 'shop_admin_support',
        }
