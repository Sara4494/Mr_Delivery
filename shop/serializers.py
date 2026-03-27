from datetime import datetime, time
import secrets
import string

from django.utils import timezone
from rest_framework import serializers
from .models import (
    ShopStatus, Customer, CustomerAddress, Driver, Order, ChatMessage,
    Invoice, Employee, Product, Category, Offer, OrderRating, PaymentMethod,
    Notification, Cart, CartItem, ShopDriver
)
from user.models import ShopOwner, ShopCategory
from user.utils import t
from user.otp_service import normalize_phone
from rest_framework_simplejwt.tokens import RefreshToken


class ShopCategorySerializer(serializers.ModelSerializer):
    """Serializer for shop categories."""

    class Meta:
        model = ShopCategory
        fields = ['id', 'name', 'is_active', 'created_at', 'updated_at']
        read_only_fields = ['id', 'created_at', 'updated_at']


class ShopStatusSerializer(serializers.ModelSerializer):
    """Serializer لحالة المتجر"""
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    
    class Meta:
        model = ShopStatus
        fields = ['id', 'status', 'status_display', 'updated_at']
        read_only_fields = ['id', 'updated_at']


class CustomerAddressSerializer(serializers.ModelSerializer):
    """Serializer لعنوان العميل"""
    title = serializers.CharField(required=False, allow_blank=True)
    full_address = serializers.CharField(required=False, allow_blank=True)
    city = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    area = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    street_name = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    landmark = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    building_number = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    floor = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    apartment = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    address_type_display = serializers.CharField(source='get_address_type_display', read_only=True)
    
    class Meta:
        model = CustomerAddress
        fields = ['id', 'title', 'address_type', 'address_type_display', 'full_address',
                  'city', 'area', 'street_name', 'landmark', 'latitude', 'longitude',
                  'building_number', 'floor', 'apartment', 'notes', 'is_default', 'created_at']
        read_only_fields = ['id', 'created_at']
        extra_kwargs = {
            'title': {'required': False, 'allow_blank': True},
            'address_type': {'required': False},
            'full_address': {'required': False, 'allow_blank': True},
        }

    @staticmethod
    def _compose_title(values, instance=None):
        def pick(key):
            if key in values:
                return str(values.get(key) or '').strip()
            if instance is not None:
                return str(getattr(instance, key, '') or '').strip()
            return ''

        explicit_title = pick('title')
        if explicit_title:
            return explicit_title

        city = pick('city')
        area = pick('area')
        landmark = pick('landmark')
        address_type = pick('address_type') or 'home'
        type_label_map = {
            'home': 'المنزل',
            'work': 'العمل',
            'other': 'عنوان',
        }

        for candidate in [city, area, landmark]:
            if candidate:
                return candidate
        return type_label_map.get(address_type, 'عنوان')

    @staticmethod
    def _compose_full_address(values, instance=None):
        def pick(key):
            if key in values:
                return str(values.get(key) or '').strip()
            if instance is not None:
                return str(getattr(instance, key, '') or '').strip()
            return ''

        explicit_full_address = pick('full_address')
        if explicit_full_address:
            return explicit_full_address

        address_parts = [
            pick('city'),
            pick('area'),
            pick('landmark'),
            pick('street_name'),
            f"رقم المبنى {pick('building_number')}" if pick('building_number') else '',
            f"الطابق {pick('floor')}" if pick('floor') else '',
            f"الشقة {pick('apartment')}" if pick('apartment') else '',
        ]
        composed = ' - '.join(part for part in address_parts if part)
        return composed.strip()

    def validate(self, attrs):
        full_address = self._compose_full_address(attrs, instance=self.instance)
        if not full_address:
            raise serializers.ValidationError({
                'full_address': ['يجب إرسال full_address أو حقول العنوان التفصيلية.']
            })
        attrs['full_address'] = full_address
        attrs['title'] = self._compose_title(attrs, instance=self.instance)
        return attrs


class CustomerSerializer(serializers.ModelSerializer):
    """Serializer للعميل"""
    profile_image_url = serializers.SerializerMethodField()
    addresses = CustomerAddressSerializer(many=True, read_only=True)
    default_address = serializers.SerializerMethodField()
    unread_messages_count = serializers.SerializerMethodField()
    last_message = serializers.SerializerMethodField()
    
    class Meta:
        model = Customer
        fields = ['id', 'name', 'phone_number',  'profile_image', 'profile_image_url',
                  'addresses', 'default_address', 'is_online', 'is_verified',
                  'unread_messages_count', 'last_message', 'created_at', 'updated_at']
        read_only_fields = ['id', 'created_at', 'updated_at']
    
    def get_profile_image_url(self, obj):
        """إرجاع رابط صورة العميل الكامل"""
        if obj.profile_image:
            request = self.context.get('request')
            if request:
                return request.build_absolute_uri(obj.profile_image.url)
            return obj.profile_image.url
        return None
    
    def get_default_address(self, obj):
        """العنوان الافتراضي"""
        addr = obj.addresses.filter(is_default=True).first()
        if addr:
            return CustomerAddressSerializer(addr).data
        return None
    
    def get_unread_messages_count(self, obj):
        """عدد الرسائل غير المقروءة للعميل"""
        return sum(order.unread_messages_count for order in obj.orders.all())

    @staticmethod
    def _build_last_message_preview(last_message):
        content = (last_message.content or '').strip()
        if content:
            return content[:50] + '...' if len(content) > 50 else content

        message_type = getattr(last_message, 'message_type', None)
        preview_map = {
            'audio': 'رسالة صوتية',
            'image': 'صورة',
            'location': 'موقع',
            'text': '',
        }
        return preview_map.get(message_type, '')
    
    def get_last_message(self, obj):
        """آخر رسالة من العميل"""
        last_order = obj.orders.order_by('-updated_at').first()
        if last_order:
            last_message = last_order.messages.order_by('-created_at').first()
            if last_message:
                return {
                    'content': self._build_last_message_preview(last_message),
                    'created_at': last_message.created_at.isoformat() if last_message.created_at else None
                }
        return None


class CustomerAppAddressSerializer(serializers.ModelSerializer):
    """Compact address payload for the customer app."""

    class Meta:
        model = CustomerAddress
        fields = [
            'id',
            'title',
            'city',
            'area',
            'street_name',
            'building_number',
            'floor',
            'is_default',
        ]
        read_only_fields = fields


class CustomerAppProfileSerializer(serializers.ModelSerializer):
    """Compact customer profile payload for the customer app."""

    profile_image_url = serializers.SerializerMethodField()
    default_address = serializers.SerializerMethodField()

    class Meta:
        model = Customer
        fields = [
            'id',
            'name',
            'phone_number',
            'profile_image',
            'profile_image_url',
            'is_verified',
            'default_address',
        ]
        read_only_fields = fields

    def get_profile_image_url(self, obj):
        if obj.profile_image:
            request = self.context.get('request')
            if request:
                return request.build_absolute_uri(obj.profile_image.url)
            return obj.profile_image.url
        return None

    def get_default_address(self, obj):
        addr = obj.addresses.filter(is_default=True).first()
        if addr:
            return CustomerAppAddressSerializer(addr, context=self.context).data
        return None


class CustomerProfileUpdateSerializer(serializers.ModelSerializer):
    """Serializer لتحديث ملف العميل من نفس endpoint."""

    profile_image = serializers.ImageField(required=False, allow_null=True)
    current_password = serializers.CharField(write_only=True, required=False, allow_blank=True)
    new_password = serializers.CharField(write_only=True, required=False, allow_blank=True)
    confirm_password = serializers.CharField(write_only=True, required=False, allow_blank=True)
    remove_profile_image = serializers.BooleanField(write_only=True, required=False, default=False)

    class Meta:
        model = Customer
        fields = [
            'name',
            'phone_number',
            'profile_image',
            'remove_profile_image',
            'current_password',
            'new_password',
            'confirm_password',
        ]

    @staticmethod
    def _phone_variants(phone_number):
        raw = str(phone_number or '').strip()
        normalized = normalize_phone(raw)
        variants = {raw, normalized}
        if normalized.startswith('+20'):
            variants.add(normalized[1:])
            variants.add(normalized[3:])
            variants.add('0' + normalized[3:])
        return [variant for variant in variants if variant]

    def validate_name(self, value):
        request = self.context.get('request')
        name = str(value or '').strip()
        if not name:
            raise serializers.ValidationError(t(request, 'name_is_required'))
        return name

    def validate_phone_number(self, value):
        request = self.context.get('request')
        raw_phone = str(value or '').strip()
        if not raw_phone:
            raise serializers.ValidationError(t(request, 'phone_number_is_required'))

        normalized_phone = normalize_phone(raw_phone)
        phone_variants = self._phone_variants(raw_phone)
        existing_customer = Customer.objects.filter(phone_number__in=phone_variants)
        if self.instance and self.instance.pk:
            existing_customer = existing_customer.exclude(pk=self.instance.pk)
        if existing_customer.exists():
            raise serializers.ValidationError(t(request, 'phone_number_is_already_registered'))

        return normalized_phone

    def validate(self, attrs):
        request = self.context.get('request')
        current_password = str(attrs.get('current_password') or '').strip()
        new_password = str(attrs.get('new_password') or '').strip()
        confirm_password = str(attrs.get('confirm_password') or '').strip()

        if current_password and not new_password:
            raise serializers.ValidationError({
                'new_password': [t(request, 'new_password_is_required')]
            })

        if new_password and not current_password:
            raise serializers.ValidationError({
                'current_password': [t(request, 'current_password_is_required')]
            })

        if new_password and len(new_password) < 6:
            raise serializers.ValidationError({
                'new_password': [t(request, 'password_must_be_at_least_6_characters')]
            })

        if new_password and confirm_password and new_password != confirm_password:
            raise serializers.ValidationError({
                'confirm_password': [t(request, 'new_password_confirmation_does_not_match')]
            })

        if new_password and self.instance and not self.instance.check_password(current_password):
            raise serializers.ValidationError({
                'current_password': [t(request, 'current_password_is_incorrect')]
            })

        return attrs

    def update(self, instance, validated_data):
        validated_data.pop('current_password', None)
        new_password = validated_data.pop('new_password', None)
        validated_data.pop('confirm_password', None)
        remove_profile_image = validated_data.pop('remove_profile_image', False)

        if remove_profile_image:
            instance.profile_image = None

        for attr, value in validated_data.items():
            setattr(instance, attr, value)

        if new_password:
            instance.set_password(new_password)

        instance.save()
        return instance


class CustomerCreateSerializer(serializers.ModelSerializer):
    """Serializer لإنشاء عميل جديد"""
    password = serializers.CharField(write_only=True, required=False)
    
    class Meta:
        model = Customer
        fields = ['name', 'phone_number',  'password', 'profile_image']
    
    def create(self, validated_data):
        password = validated_data.pop('password', None)
        customer = Customer.objects.create(**validated_data)
        if password:
            customer.set_password(password)
            customer.save()
        return customer
    
    def create(self, validated_data):
        """إنشاء عميل جديد"""
        shop_owner = self.context['shop_owner']
        customer, created = Customer.objects.get_or_create(
            shop_owner=shop_owner,
            phone_number=validated_data['phone_number'],
            defaults=validated_data
        )
        if not created:
            # تحديث البيانات إذا كان العميل موجوداً
            for attr, value in validated_data.items():
                setattr(customer, attr, value)
            customer.save()
        return customer


class DriverSerializer(serializers.ModelSerializer):
    """Serializer للسائق"""
    profile_image_url = serializers.SerializerMethodField()
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    vehicle_type_display = serializers.CharField(source='get_vehicle_type_display', read_only=True)
    
    class Meta:
        model = Driver
        fields = ['id', 'name', 'phone_number', 'profile_image', 'profile_image_url',
                  'vehicle_type', 'vehicle_type_display', 'is_verified',
                  'status', 'status_display', 'current_orders_count', 'rating', 'total_rides', 'created_at', 'updated_at']
        read_only_fields = ['id', 'created_at', 'updated_at']
    
    def get_profile_image_url(self, obj):
        """إرجاع رابط صورة السائق الكامل"""
        if obj.profile_image:
            request = self.context.get('request')
            if request:
                return request.build_absolute_uri(obj.profile_image.url)
            return obj.profile_image.url
        return None


class DriverCreateSerializer(serializers.ModelSerializer):
    """Serializer لإنشاء سائق جديد"""
    password = serializers.CharField(write_only=True, required=False, allow_blank=True)
    
    class Meta:
        model = Driver
        fields = ['name', 'phone_number', 'password', 'profile_image', 'vehicle_type', 'status']
    
    def create(self, validated_data):
        """إنشاء سائق جديد"""
        # ملاحظة: في النظام الجديد، السائق يُنشأ مستقلاً ثم يُربط بالمحل
        # هذا الكود يفترض أن الإنشاء يتم من داخل محل، لذا نربطه مباشرة
        shop_owner = self.context.get('shop_owner')
        password = validated_data.pop('password', None)
        
        driver = Driver.objects.create(**validated_data)
        if password:
            driver.set_password(password)
            driver.save()
        
        if shop_owner:
            ShopDriver.objects.create(shop_owner=shop_owner, driver=driver, status='active')
            
        return driver


class DriverAppSerializer(serializers.ModelSerializer):
    """Compact driver payload for the delivery app."""

    profile_image_url = serializers.SerializerMethodField()
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    vehicle_type_display = serializers.CharField(source='get_vehicle_type_display', read_only=True)
    active_shops = serializers.SerializerMethodField()

    class Meta:
        model = Driver
        fields = [
            'id',
            'name',
            'phone_number',
            'profile_image',
            'profile_image_url',
            'vehicle_type',
            'vehicle_type_display',
            'is_verified',
            'status',
            'status_display',
            'active_shops',
        ]
        read_only_fields = fields

    def get_profile_image_url(self, obj):
        if obj.profile_image:
            request = self.context.get('request')
            if request:
                return request.build_absolute_uri(obj.profile_image.url)
            return obj.profile_image.url
        return None

    def get_active_shops(self, obj):
        shops = obj.shops.filter(shop_drivers__status='active').values('id', 'shop_name', 'shop_number')
        return list(shops)


class DriverRegisterSerializer(serializers.ModelSerializer):
    """Serializer for self-registering a driver account in the delivery app."""

    name = serializers.CharField(required=False)
    phone_number = serializers.CharField(required=False)
    vehicle_type = serializers.CharField(required=False)
    password = serializers.CharField(write_only=True, required=False)
    confirm_password = serializers.CharField(write_only=True, required=False)
    profile_image = serializers.ImageField(required=False, allow_null=True)

    class Meta:
        model = Driver
        fields = ['name', 'phone_number', 'vehicle_type', 'password', 'confirm_password', 'profile_image']

    @staticmethod
    def _phone_variants(phone_number):
        raw = str(phone_number or '').strip()
        normalized = normalize_phone(raw)
        variants = {raw, normalized}
        if normalized.startswith('+20'):
            variants.add(normalized[1:])
            variants.add(normalized[3:])
            variants.add('0' + normalized[3:])
        return [variant for variant in variants if variant]

    def validate_name(self, value):
        request = self.context.get('request')
        name = str(value or '').strip()
        if not name:
            raise serializers.ValidationError(t(request, 'name_is_required'))
        return name

    def validate_phone_number(self, value):
        request = self.context.get('request')
        normalized_phone = normalize_phone(value)
        if not normalized_phone:
            raise serializers.ValidationError(t(request, 'phone_number_is_required'))

        existing_driver = Driver.objects.filter(
            phone_number__in=self._phone_variants(normalized_phone)
        ).order_by('-updated_at').first()
        if existing_driver and existing_driver.is_verified:
            raise serializers.ValidationError(t(request, 'phone_number_is_already_registered_and_verified'))
        if existing_driver and not existing_driver.is_verified:
            raise serializers.ValidationError(t(request, 'driver_account_exists_but_not_verified'))
        return normalized_phone

    def validate_vehicle_type(self, value):
        request = self.context.get('request')
        if not value:
            raise serializers.ValidationError(t(request, 'vehicle_type_is_required'))
        if value not in {choice[0] for choice in Driver.VEHICLE_TYPE_CHOICES}:
            raise serializers.ValidationError(t(request, 'invalid_vehicle_type'))
        return value

    def validate(self, attrs):
        request = self.context.get('request')
        if not str(attrs.get('name') or '').strip():
            raise serializers.ValidationError({'name': [t(request, 'name_is_required')]})
        if not str(attrs.get('phone_number') or '').strip():
            raise serializers.ValidationError({'phone_number': [t(request, 'phone_number_is_required')]})
        if not attrs.get('vehicle_type'):
            raise serializers.ValidationError({'vehicle_type': [t(request, 'vehicle_type_is_required')]})

        password = attrs.get('password')
        confirm_password = attrs.pop('confirm_password', None)

        if not password:
            raise serializers.ValidationError({'password': [t(request, 'password_is_required')]})
        if len(password) < 6:
            raise serializers.ValidationError({'password': [t(request, 'password_must_be_at_least_6_characters')]})
        if not confirm_password:
            raise serializers.ValidationError({'confirm_password': [t(request, 'confirm_password_is_required')]})
        if password != confirm_password:
            raise serializers.ValidationError({'confirm_password': [t(request, 'new_password_confirmation_does_not_match')]})

        return attrs

    def create(self, validated_data):
        password = validated_data.pop('password')
        driver = Driver.objects.create(is_verified=False, **validated_data)
        driver.set_password(password)
        driver.save()
        return driver


def _build_chat_message_invoice_payload(obj):
    from user.utils import _resolve_message_key

    message_key = _resolve_message_key(obj.content)
    if message_key not in {'order_priced_please_confirm', 'invoice_modified_waiting_for_confirmation'}:
        return None

    order = getattr(obj, 'order', None)
    if not order:
        return None

    return {
        'order_id': order.id,
        'order_number': order.order_number,
        'status': order.status,
        'status_display': order.get_status_display(),
        'items': _order_items_to_representation(order.items),
        'delivery_fee': str(order.delivery_fee) if order.delivery_fee is not None else None,
        'total_amount': str(order.total_amount) if order.total_amount is not None else None,
        'address': order.address,
        'notes': order.notes,
    }


class ChatMessageSerializer(serializers.ModelSerializer):
    """Serializer لرسائل المحادثة"""
    sender_type_display = serializers.CharField(source='get_sender_type_display', read_only=True)
    chat_type_display = serializers.CharField(source='get_chat_type_display', read_only=True)
    message_type_display = serializers.CharField(source='get_message_type_display', read_only=True)
    sender_name = serializers.CharField(read_only=True)
    sender_id = serializers.SerializerMethodField()
    audio_file_url = serializers.SerializerMethodField()
    image_file_url = serializers.SerializerMethodField()
    content = serializers.SerializerMethodField()
    invoice = serializers.SerializerMethodField()
    
    class Meta:
        model = ChatMessage
        fields = ['id', 'chat_type', 'chat_type_display', 'sender_type', 'sender_type_display',
                  'sender_name', 'sender_id', 'message_type', 'message_type_display',
                  'content', 'audio_file', 'audio_file_url', 'image_file', 'image_file_url',
                  'latitude', 'longitude', 'invoice', 'is_read', 'created_at']
        read_only_fields = ['id', 'created_at']
    
    def get_content(self, obj):
        from user.utils import localize_message
        request = self.context.get('request')
        lang = self.context.get('lang')
        return localize_message(request, obj.content, lang=lang)

    def get_invoice(self, obj):
        return _build_chat_message_invoice_payload(obj)

    def get_sender_id(self, obj):
        """إرجاع ID المرسل"""
        if obj.sender_type == 'customer' and obj.sender_customer:
            return obj.sender_customer.id
        elif obj.sender_type == 'shop_owner' and obj.sender_shop_owner:
            return obj.sender_shop_owner.id
        elif obj.sender_type == 'employee' and obj.sender_employee:
            return obj.sender_employee.id
        elif obj.sender_type == 'driver' and obj.sender_driver:
            return obj.sender_driver.id
        return None
    
    def get_audio_file_url(self, obj):
        """إرجاع رابط الملف الصوتي"""
        if obj.audio_file:
            request = self.context.get('request')
            if request:
                return request.build_absolute_uri(obj.audio_file.url)
            return obj.audio_file.url
        return None
    
    def get_image_file_url(self, obj):
        """إرجاع رابط الصورة"""
        if obj.image_file:
            request = self.context.get('request')
            if request:
                return request.build_absolute_uri(obj.image_file.url)
            return obj.image_file.url
        return None


def _order_items_to_representation(value):
    """تحويل items من نص/JSON إلى قائمة (بند 1، بند 2، ...) للعرض"""
    if not value:
        return []
    import json
    try:
        parsed = json.loads(value)
        if isinstance(parsed, list):
            return parsed
        return [value]
    except (TypeError, ValueError):
        return [value] if isinstance(value, str) else []


class OrderSerializer(serializers.ModelSerializer):
    """Serializer للطلب"""
    customer = CustomerSerializer(read_only=True)
    employee = serializers.SerializerMethodField()
    driver = DriverSerializer(read_only=True)
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    last_message = serializers.SerializerMethodField()
    items = serializers.SerializerMethodField()
    
    class Meta:
        model = Order
        fields = ['id', 'order_number', 'customer', 'employee', 'driver', 'status', 'status_display',
                  'items', 'total_amount', 'delivery_fee', 'address', 'notes',
                  'unread_messages_count', 'last_message', 'created_at', 'updated_at']
        read_only_fields = ['id', 'order_number', 'created_at', 'updated_at']
    
    def get_items(self, obj):
        """عرض الأصناف كقائمة (بند 1، بند 2، ...)"""
        return _order_items_to_representation(obj.items)
    
    def get_employee(self, obj):
        """الموظف المسؤول (معرف + اسم)"""
        if obj.employee_id:
            return {'id': obj.employee.id, 'name': obj.employee.name}
        return None
    
    def get_last_message(self, obj):
        """آخر رسالة في الطلب"""
        last_message = obj.messages.order_by('-created_at').first()
        if last_message:
            serializer = ChatMessageSerializer(last_message, context=self.context)
            return serializer.data
        return None


class ShopOrderListSerializer(serializers.ModelSerializer):
    customer_name = serializers.CharField(source='customer.name', read_only=True)
    customer_phone_number = serializers.CharField(source='customer.phone_number', read_only=True)
    customer_profile_image_url = serializers.SerializerMethodField()
    status_display = serializers.CharField(source='get_status_display', read_only=True)

    def get_customer_profile_image_url(self, obj):
        customer = getattr(obj, 'customer', None)
        if not customer or not customer.profile_image:
            return None

        request = self.context.get('request')
        if request:
            return request.build_absolute_uri(customer.profile_image.url)
        return customer.profile_image.url

    class Meta:
        model = Order
        fields = [
            'id',
            'order_number',
            'customer_name',
            'customer_phone_number',
            'customer_profile_image_url',
            'address',
            'status',
            'status_display',
            'total_amount',
            'delivery_fee',
            'unread_messages_count',
            'created_at',
        ]
        read_only_fields = fields


def _items_to_db_value(value):
    """تحويل items من قائمة أو نص إلى JSON string للحفظ"""
    import json
    if isinstance(value, list):
        return json.dumps(value, ensure_ascii=False)
    return value if value else '[]'


def _generate_short_order_number():
    alphabet = string.ascii_uppercase + string.digits
    prefix = 'OD'

    for _ in range(20):
        order_number = prefix + ''.join(secrets.choice(alphabet) for _ in range(6))
        if not Order.objects.filter(order_number=order_number).exists():
            return order_number

    raise serializers.ValidationError({'order_number': 'Failed to generate a unique order number.'})

class OrderCreateSerializer(serializers.Serializer):
    """Serializer لإنشاء طلب جديد (من المحل)"""
    customer_id = serializers.IntegerField(required=True)
    employee_id = serializers.IntegerField(required=False, allow_null=True)
    driver_id = serializers.IntegerField(required=False, allow_null=True)
    items = serializers.JSONField(required=True)  # قائمة أصناف [بند1، بند2، ...] أو نص قديم
    total_amount = serializers.DecimalField(max_digits=10, decimal_places=2, required=True)
    delivery_fee = serializers.DecimalField(max_digits=10, decimal_places=2, default=0)
    address = serializers.CharField(required=True)
    notes = serializers.CharField(required=False, allow_blank=True)
    
    def validate_items(self, value):
        if value is None:
            raise serializers.ValidationError('تفاصيل الطلب (البند) مطلوبة')
        if isinstance(value, list):
            if len(value) == 0:
                raise serializers.ValidationError('تفاصيل الطلب (البند) مطلوبة')
            return _items_to_db_value(value)
        return _items_to_db_value([value]) if isinstance(value, str) else value
    
    def validate_customer_id(self, value):
        """التحقق من وجود العميل"""
        shop_owner = self.context['shop_owner']
        try:
            Customer.objects.get(id=value, shop_owner=shop_owner)
        except Customer.DoesNotExist:
            raise serializers.ValidationError('العميل غير موجود')
        return value
    
    def validate_employee_id(self, value):
        """التحقق من وجود الموظف"""
        if value is None:
            return value
        shop_owner = self.context['shop_owner']
        try:
            Employee.objects.get(id=value, shop_owner=shop_owner)
        except Employee.DoesNotExist:
            raise serializers.ValidationError('الموظف غير موجود')
        return value
    
    def validate_driver_id(self, value):
        """التحقق من وجود السائق"""
        if value is None:
            return value
        shop_owner = self.context['shop_owner']
        try:
            ShopDriver.objects.select_related('driver').get(
                shop_owner=shop_owner,
                driver_id=value,
                status='active',
            )
        except ShopDriver.DoesNotExist:
            raise serializers.ValidationError('السائق غير موجود')
        return value
    
    def create(self, validated_data):
        """إنشاء طلب جديد"""
        shop_owner = self.context['shop_owner']
        customer_id = validated_data.pop('customer_id')
        employee_id = validated_data.pop('employee_id', None)
        driver_id = validated_data.pop('driver_id', None)
        
        customer = Customer.objects.get(id=customer_id, shop_owner=shop_owner)
        employee = None
        if employee_id:
            employee = Employee.objects.get(id=employee_id, shop_owner=shop_owner)
        driver = None
        if driver_id:
            driver = ShopDriver.objects.select_related('driver').get(
                shop_owner=shop_owner,
                driver_id=driver_id,
                status='active',
            ).driver
        
        # إنشاء رقم طلب تلقائي
        order_number = _generate_short_order_number()
        
        order = Order.objects.create(
            shop_owner=shop_owner,
            customer=customer,
            employee=employee,
            driver=driver,
            order_number=order_number,
            **validated_data
        )
        
        # تحديث عدد الطلبات للسائق
        if driver:
            driver.current_orders_count = driver.orders.filter(status__in=['new', 'preparing', 'on_way']).count()
            driver.save()
        
        return order


class CustomerOrderCreateSerializer(serializers.Serializer):
    """إنشاء طلب من العميل (الرسالة الأولى = الفاتورة: الاسم، العنوان، البند 1، 2، 3، ...)"""
    address = serializers.CharField(required=True)
    items = serializers.ListField(child=serializers.CharField(), min_length=1)
    notes = serializers.CharField(required=False, allow_blank=True)
    phone_number = serializers.CharField(required=False, allow_blank=True)
    
    def create(self, validated_data):
        customer = self.context['customer']
        shop_owner = getattr(customer, 'shop_owner', None)
        if not shop_owner:
            raise serializers.ValidationError({'shop': 'العميل غير مرتبط بمحل. يرجى اختيار المحل أولاً.'})
        
        items_str = _items_to_db_value(validated_data['items'])
        order_number = _generate_short_order_number()
        
        order = Order.objects.create(
            shop_owner=shop_owner,
            customer=customer,
            order_number=order_number,
            address=validated_data['address'],
            items=items_str,
            notes=validated_data.get('notes') or '',
            total_amount=0,
            delivery_fee=0,
            status='new',
        )
        return order


class InvoiceSerializer(serializers.ModelSerializer):
    """Serializer للفاتورة"""
    customer = CustomerSerializer(read_only=True)
    order = OrderSerializer(read_only=True)
    
    class Meta:
        model = Invoice
        fields = ['id', 'invoice_number', 'customer', 'order', 'items', 'total_amount',
                  'delivery_fee', 'address', 'phone_number', 'is_sent', 'sent_at', 'created_at']
        read_only_fields = ['id', 'invoice_number', 'sent_at', 'created_at']


class  ProductSerializer(serializers.ModelSerializer):
    """Serializer للمنتج"""
    image_url = serializers.SerializerMethodField()
    category_name = serializers.SerializerMethodField()
    final_price = serializers.SerializerMethodField()
    has_offer = serializers.SerializerMethodField()
    
    class Meta:
        model = Product
        fields = [
            'id', 'category', 'category_name', 'name', 'description',
            'price', 'discount_price', 'final_price', 'has_offer',
            'image', 'image_url', 'display_order', 'is_available',
            'is_featured', 'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']
    
    def get_image_url(self, obj):
        if obj.image:
            request = self.context.get('request')
            if request:
                return request.build_absolute_uri(obj.image.url)
            return obj.image.url
        return None

    def get_category_name(self, obj):
        return obj.category.name if obj.category else None

    def get_final_price(self, obj):
        return obj.final_price

    def get_has_offer(self, obj):
        return bool(obj.discount_price is not None and obj.discount_price < obj.price)


class PublicProductSerializer(ProductSerializer):
    """Serializer for public product listing across shops."""
    shop_id = serializers.IntegerField(source='shop_owner.id', read_only=True)
    shop_name = serializers.CharField(source='shop_owner.shop_name', read_only=True)
    shop_number = serializers.CharField(source='shop_owner.shop_number', read_only=True)
    shop_category = serializers.SerializerMethodField()

    class Meta(ProductSerializer.Meta):
        fields = [
            'id', 'shop_id', 'shop_name', 'shop_number', 'shop_category',
            'category', 'category_name', 'name', 'description',
            'price', 'discount_price', 'final_price', 'has_offer',
            'image', 'image_url', 'is_available'
        ]

    def get_shop_category(self, obj):
        category = getattr(obj.shop_owner, 'shop_category', None)
        if not category:
            return None
        return {'id': category.id, 'name': category.name}


class PublicOfferProductSerializer(ProductSerializer):
    """Serializer لعروض المنتجات في واجهات العميل"""
    shop_id = serializers.IntegerField(source='shop_owner.id', read_only=True)
    shop_name = serializers.CharField(source='shop_owner.shop_name', read_only=True)
    shop_number = serializers.CharField(source='shop_owner.shop_number', read_only=True)
    offer_percentage = serializers.SerializerMethodField()

    class Meta(ProductSerializer.Meta):
        fields = [
            'id', 'shop_id', 'shop_name', 'shop_number',
            'category', 'category_name', 'name', 'description',
            'price', 'discount_price', 'final_price', 'has_offer',
            'offer_percentage', 'image', 'image_url', 'is_available'
        ]

    def get_offer_percentage(self, obj):
        if obj.discount_price is None or obj.price <= 0 or obj.discount_price >= obj.price:
            return 0
        return round(((obj.price - obj.discount_price) / obj.price) * 100, 2)


class OfferBaseSerializer(serializers.ModelSerializer):
    image_url = serializers.SerializerMethodField()
    status = serializers.ReadOnlyField()
    offer_percentage = serializers.DecimalField(
        source='discount_percentage',
        max_digits=5,
        decimal_places=2,
        read_only=True,
    )

    class Meta:
        model = Offer
        fields = [
            'id', 'title', 'description', 'image', 'image_url',
            'discount_percentage', 'offer_percentage', 'start_date',
            'end_date', 'status', 'is_active', 'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'status', 'created_at', 'updated_at']

    def get_image_url(self, obj):
        if obj.image:
            request = self.context.get('request')
            if request:
                return request.build_absolute_uri(obj.image.url)
            return obj.image.url
        return None


class PublicOfferSerializer(OfferBaseSerializer):
    shop_id = serializers.IntegerField(source='shop_owner.id', read_only=True)
    shop_name = serializers.CharField(source='shop_owner.shop_name', read_only=True)
    shop_logo_url = serializers.SerializerMethodField()
    image_url = serializers.SerializerMethodField()
    rating = serializers.SerializerMethodField()
    likes_count = serializers.IntegerField(read_only=True)
    is_liked = serializers.SerializerMethodField()
    expires_in = serializers.SerializerMethodField()

    class Meta(OfferBaseSerializer.Meta):
        fields = [
            'id', 'shop_id', 'shop_name', 'shop_logo_url',
            'title', 'description', 'image_url',
            'discount_percentage', 'rating', 'likes_count', 'is_liked',
            'expires_in'
        ]

    def _build_file_url(self, file_field):
        if not file_field:
            return None

        request = self.context.get('request')
        if request:
            return request.build_absolute_uri(file_field.url)
        return file_field.url

    def _get_shop_gallery_images(self, obj):
        return getattr(obj.shop_owner, 'published_gallery_images', []) or []

    def _get_shop_cover_image(self, obj):
        published_images = self._get_shop_gallery_images(obj)
        if not published_images:
            return None
        return published_images[0]

    def _get_shop_cover_image_url(self, obj):
        cover_image = self._get_shop_cover_image(obj)
        if not cover_image:
            return None
        return self._build_file_url(cover_image.image)

    def _get_shop_rating_stats(self, obj):
        rating_map = self.context.get('shop_rating_map', {})
        return rating_map.get(
            obj.shop_owner_id,
            {'average': 0.0, 'count': 0},
        )

    def _get_remaining_time(self, obj):
        end_of_offer = timezone.make_aware(
            datetime.combine(obj.end_date, time(23, 59, 59)),
            timezone.get_current_timezone(),
        )
        remaining_seconds = max(int((end_of_offer - timezone.localtime()).total_seconds()), 0)
        hours, remainder = divmod(remaining_seconds, 3600)
        minutes, seconds = divmod(remainder, 60)
        return f'{hours:02d}:{minutes:02d}:{seconds:02d}'

    def _get_display_image_url(self, obj):
        return (
            super().get_image_url(obj)
            or self._get_shop_cover_image_url(obj)
            or self._build_file_url(obj.shop_owner.profile_image)
        )

    def get_shop_logo_url(self, obj):
        return self._build_file_url(obj.shop_owner.profile_image)

    def get_image_url(self, obj):
        return self._get_display_image_url(obj)

    def get_rating(self, obj):
        return self._get_shop_rating_stats(obj)['average']

    def get_is_liked(self, obj):
        liked_offer_ids = self.context.get('liked_offer_ids', set())
        return obj.id in liked_offer_ids

    def get_expires_in(self, obj):
        return self._get_remaining_time(obj)


class OfferManagementSerializer(OfferBaseSerializer):
    shop_owner_id = serializers.IntegerField(source='shop_owner.id', read_only=True)
    shop_name = serializers.CharField(source='shop_owner.shop_name', read_only=True)
    likes_count = serializers.IntegerField(read_only=True)

    class Meta(OfferBaseSerializer.Meta):
        fields = [
            'id', 'shop_owner_id', 'shop_name', 'title', 'description',
            'image', 'image_url', 'discount_percentage', 'offer_percentage',
            'start_date', 'end_date', 'status', 'views_count', 'likes_count',
            'is_active', 'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'status', 'views_count', 'created_at', 'updated_at']


class OfferCreateUpdateSerializer(serializers.ModelSerializer):
    image = serializers.ImageField(required=False, allow_null=True)

    class Meta:
        model = Offer
        fields = [
            'title', 'description', 'image', 'discount_percentage',
            'start_date', 'end_date', 'is_active'
        ]

    def validate_title(self, value):
        request = self.context.get('request')
        title = str(value or '').strip()
        if not title:
            raise serializers.ValidationError(t(request, 'offer_title_is_required'))
        return title

    def validate_discount_percentage(self, value):
        request = self.context.get('request')
        if value is None or value <= 0:
            raise serializers.ValidationError(
                t(request, 'discount_percentage_must_be_greater_than_zero')
            )
        return value

    def validate(self, attrs):
        request = self.context.get('request')
        start_date = attrs.get('start_date')
        end_date = attrs.get('end_date')

        if self.instance:
            start_date = start_date or self.instance.start_date
            end_date = end_date or self.instance.end_date

        if start_date and end_date and end_date < start_date:
            raise serializers.ValidationError({
                'end_date': [t(request, 'offer_end_date_must_not_be_before_start_date')]
            })

        description = attrs.get('description')
        if description is not None:
            attrs['description'] = str(description).strip()

        return attrs


class ProductCreateSerializer(serializers.ModelSerializer):
    """Serializer لإنشاء/تحديث منتج"""
    
    class Meta:
        model = Product
        fields = [
            'category', 'name', 'description', 'price', 'discount_price',
            'image', 'display_order', 'is_available', 'is_featured'
        ]

    def validate_category(self, value):
        if value is None:
            return value
        shop_owner = self.context.get('shop_owner')
        if shop_owner and value.shop_owner_id != shop_owner.id:
            raise serializers.ValidationError('التصنيف لا يتبع هذا المحل.')
        return value


class InvoiceItemSerializer(serializers.Serializer):
    """صنف واحد في الفاتورة"""
    item_name = serializers.CharField()
    price = serializers.DecimalField(max_digits=10, decimal_places=2)
    quantity = serializers.IntegerField(min_value=1)


class InvoiceCreateSerializer(serializers.Serializer):
    """Serializer لإنشاء فاتورة - يقبل أصنافاً كقائمة (item_name, price, quantity) أو items كنص قديم"""
    customer_name = serializers.CharField(required=True)
    phone_number = serializers.CharField(required=True)
    address = serializers.CharField(required=True)
    items = serializers.ListField(
        child=InvoiceItemSerializer(),
        required=False,
        allow_empty=False
    )
    items_text = serializers.CharField(required=False, allow_blank=True)
    amount = serializers.DecimalField(max_digits=10, decimal_places=2, required=False)
    delivery = serializers.DecimalField(max_digits=10, decimal_places=2, default=0)
    
    def validate(self, attrs):
        items_list = attrs.get('items')
        items_text = attrs.get('items_text') or ''
        if items_list:
            subtotal = sum(float(i['price']) * i['quantity'] for i in items_list)
            delivery_val = float(attrs.get('delivery', 0))
            attrs['_items_json'] = items_list
            attrs['amount'] = subtotal + delivery_val
        elif items_text.strip() and attrs.get('amount') is not None:
            attrs['_items_text'] = items_text
        elif not items_list and (not items_text.strip() or attrs.get('amount') is None):
            raise serializers.ValidationError(
                {'items': 'أرسل أصناف الفاتورة كقائمة: [{"item_name": "...", "price": "...", "quantity": 1}, ...] أو items_text مع amount.'}
            )
        return attrs


# Employee Serializers
class EmployeeSerializer(serializers.ModelSerializer):
    """Serializer للموظف"""
    profile_image_url = serializers.SerializerMethodField()
    role_display = serializers.CharField(source='get_role_display', read_only=True)
    total_orders_count = serializers.SerializerMethodField()
    custody_amount = serializers.DecimalField(max_digits=12, decimal_places=2, read_only=True)
    
    class Meta:
        model = Employee
        fields = ['id', 'name', 'phone_number', 'role', 'role_display', 'profile_image', 'profile_image_url',
                  'total_orders_count', 'custody_amount', 'is_active', 'created_at', 'updated_at']
        read_only_fields = ['id', 'created_at', 'updated_at', 'total_orders_count']
    
    def get_profile_image_url(self, obj):
        """إرجاع رابط صورة الموظف الكامل"""
        if obj.profile_image:
            request = self.context.get('request')
            if request:
                return request.build_absolute_uri(obj.profile_image.url)
            return obj.profile_image.url
        return None
    
    def get_total_orders_count(self, obj):
        """عدد الطلبات التي تعامل معها الموظف"""
        return obj.total_orders_count


class EmployeeCreateSerializer(serializers.ModelSerializer):
    """Serializer لإنشاء موظف جديد"""
    password = serializers.CharField(write_only=True, required=True)
    
    class Meta:
        model = Employee
        fields = ['name', 'phone_number', 'password', 'role', 'profile_image']

    def validate_phone_number(self, value):
        """منع إنشاء موظف بنفس رقم الهاتف داخل نفس المحل."""
        shop_owner = self.context.get('shop_owner')
        if shop_owner and Employee.objects.filter(shop_owner=shop_owner, phone_number=value).exists():
            request = self.context.get('request')
            raise serializers.ValidationError(
                t(request, 'phone_number_is_already_used_for_this_shop')
            )
        return value
    
    def create(self, validated_data):
        """إنشاء موظف جديد"""
        shop_owner = self.context['shop_owner']
        password = validated_data.pop('password')
        employee = Employee.objects.create(shop_owner=shop_owner, **validated_data)
        employee.set_password(password)
        employee.save()
        return employee


class EmployeeUpdateSerializer(serializers.ModelSerializer):
    """Serializer لتحديث موظف"""
    password = serializers.CharField(write_only=True, required=False, allow_blank=True)
    
    class Meta:
        model = Employee
        fields = ['name', 'phone_number', 'password', 'role', 'profile_image', 'custody_amount', 'is_active']
    
    def update(self, instance, validated_data):
        """تحديث بيانات الموظف"""
        password = validated_data.pop('password', None)
        if password:
            instance.set_password(password)
        return super().update(instance, validated_data)


# Employee Login Serializers
class EmployeeTokenObtainPairSerializer(serializers.Serializer):
    """Custom Token Serializer للموظف"""
    phone_number = serializers.CharField(required=True)
    password = serializers.CharField(required=True, write_only=True)
    
    @classmethod
    def get_token(cls, employee):
        """
        إنشاء token مع employee_id
        """
        token = RefreshToken()
        token['employee_id'] = employee.id
        token['phone_number'] = employee.phone_number
        token['role'] = employee.role
        token['shop_owner_id'] = employee.shop_owner.id
        token['user_type'] = 'employee'
        return token
    
    def validate(self, attrs):
        """
        التحقق من بيانات تسجيل الدخول وإرجاع token
        """
        request = self.context.get('request')
        phone_number = attrs.get('phone_number')
        password = attrs.get('password')
        
        try:
            employee = Employee.objects.get(phone_number=phone_number)
        except Employee.DoesNotExist:
            raise serializers.ValidationError({
                'phone_number': t(request, 'phone_number_or_password_is_incorrect')
            })

        if not employee.is_active:
            raise serializers.ValidationError({
                'detail': t(request, 'employee_account_is_blocked')
            })
        
        if not employee.check_password(password):
            raise serializers.ValidationError({
                'password': t(request, 'phone_number_or_password_is_incorrect')
            })
        
        refresh = self.get_token(employee)
        
        return {
            'refresh': str(refresh),
            'access': str(refresh.access_token),
            'employee': {
                'id': employee.id,
                'name': employee.name,
                'phone_number': employee.phone_number,
                'role': employee.role,
                'role_display': employee.get_role_display(),
                'shop_owner_id': employee.shop_owner.id,
            }
        }


# Driver Login Serializers
class DriverTokenObtainPairSerializer(serializers.Serializer):
    """Custom Token Serializer للسائق"""
    phone_number = serializers.CharField(required=True)
    password = serializers.CharField(required=True, write_only=True)
    shop_number = serializers.CharField(required=False, allow_blank=True)

    @classmethod
    def get_token(cls, driver):
        """
        إنشاء token مع driver_id
        """
        token = RefreshToken()
        token['driver_id'] = driver.id
        token['phone_number'] = driver.phone_number
        # السائق قد يعمل في عدة محلات، لا نضع shop_owner_id واحد في التوكن
        # يمكن إرجاع قائمة المحلات في الاستجابة بدلاً من ذلك
        token['user_type'] = 'driver'
        return token

    @staticmethod
    def _phone_variants(phone_number):
        raw = str(phone_number or '').strip()
        normalized = normalize_phone(raw)
        variants = {raw, normalized}
        if normalized.startswith('+20'):
            variants.add(normalized[1:])
            variants.add(normalized[3:])
            variants.add('0' + normalized[3:])
        return [variant for variant in variants if variant]

    def validate(self, attrs):
        """
        التحقق من بيانات تسجيل الدخول وإرجاع token
        """
        request = self.context.get('request')
        phone_number = attrs.get('phone_number')
        password = attrs.get('password')

        queryset = Driver.objects.filter(
            phone_number__in=self._phone_variants(phone_number)
        ).order_by('-updated_at')
        if not queryset.exists():
            raise serializers.ValidationError({
                'phone_number': t(request, 'phone_number_or_password_is_incorrect')
            })

        driver = None
        for candidate in queryset:
            if candidate.password and candidate.check_password(password):
                driver = candidate
                break

        if not driver:
            raise serializers.ValidationError({
                'password': t(request, 'phone_number_or_password_is_incorrect')
            })

        if not driver.is_verified:
            raise serializers.ValidationError({
                'detail': t(request, 'account_is_not_verified_complete_otp_verification')
            })

        refresh = self.get_token(driver)

        return {
            'refresh': str(refresh),
            'access': str(refresh.access_token),
            'driver': DriverAppSerializer(driver, context=self.context).data,
        }

class DriverInvitationRespondSerializer(serializers.Serializer):
    """
    Serializer احترافي لمعالجة استجابة السائق لدعوة الانضمام (قبول/رفض).
    يتحقق من صحة البيانات، وجود السائق، ووجود دعوة معلقة من المتجر المحدد.
    """
    phone_number = serializers.CharField(required=True)
    shop_id = serializers.IntegerField(required=True, help_text="ID المتجر صاحب الدعوة")
    otp = serializers.CharField(required=True, write_only=True)
    action = serializers.ChoiceField(choices=['accept', 'reject'], required=True)

    def validate(self, attrs):
        phone_number = attrs.get('phone_number')
        shop_id = attrs.get('shop_id')
        
        # 1. التحقق من وجود السائق
        try:
            driver = Driver.objects.get(phone_number=phone_number)
        except Driver.DoesNotExist:
            raise serializers.ValidationError({
                'phone_number': 'رقم الهاتف غير صحيح أو السائق غير موجود.'
            })
        
        # 2. التحقق من وجود دعوة معلقة (Pending) لهذا السائق في هذا المتجر
        try:
            shop_driver = ShopDriver.objects.get(
                driver=driver, 
                shop_owner_id=shop_id
            )
        except ShopDriver.DoesNotExist:
            raise serializers.ValidationError({
                'shop_id': 'لا توجد علاقة أو دعوة بين هذا السائق وهذا المتجر.'
            })
            
        if shop_driver.status != 'pending':
            raise serializers.ValidationError({
                'status': f'لا يمكن الرد على الدعوة. الحالة الحالية: {shop_driver.get_status_display()}'
            })
            
        attrs['driver'] = driver
        attrs['shop_driver'] = shop_driver
        return attrs
        
    def save(self, **kwargs):
        shop_driver = self.validated_data['shop_driver']
        action = self.validated_data['action']
        
        if action == 'accept':
            shop_driver.status = 'active'
            shop_driver.save()
        elif action == 'reject':
            shop_driver.status = 'rejected'
            shop_driver.save()
            # أو يمكن حذف السجل نهائياً: shop_driver.delete()
            
        return shop_driver

# Customer Login Serializer
class CustomerTokenObtainPairSerializer(serializers.Serializer):
    """Custom Token Serializer للعميل"""
    phone_number = serializers.CharField(required=True)
    password = serializers.CharField(required=True, write_only=True)
    
    @classmethod
    def get_token(cls, customer):
        """إنشاء token مع customer_id"""
        token = RefreshToken()
        token['customer_id'] = customer.id
        token['phone_number'] = customer.phone_number
        token['user_type'] = 'customer'
        return token
    
    def validate(self, attrs):
        phone_number = attrs.get('phone_number')
        password = attrs.get('password')
        
        try:
            customer = Customer.objects.get(phone_number=phone_number)
        except Customer.DoesNotExist:
            raise serializers.ValidationError({
                'phone_number': 'رقم الهاتف غير مسجل'
            })
        
        if not customer.password or not customer.check_password(password):
            raise serializers.ValidationError({
                'password': 'كلمة المرور غير صحيحة'
            })
        
        refresh = self.get_token(customer)
        
        return {
            'refresh': str(refresh),
            'access': str(refresh.access_token),
            'customer': {
                'id': customer.id,
                'name': customer.name,
                'phone_number': customer.phone_number,
     
                'is_verified': customer.is_verified,
            }
        }


class CustomerRegisterSerializer(serializers.Serializer):
    """Serializer لتسجيل عميل جديد"""
    name = serializers.CharField(required=True)
    phone_number = serializers.CharField(required=True)
    password = serializers.CharField(required=True, write_only=True, min_length=6)
    
    def validate_phone_number(self, value):
        if Customer.objects.filter(phone_number=value).exists():
            raise serializers.ValidationError('رقم الهاتف مسجل بالفعل')
        return value
    
    def create(self, validated_data):
        password = validated_data.pop('password')
        customer = Customer.objects.create(**validated_data)
        customer.set_password(password)
        customer.save()
        return customer


# Category Serializers
class CategorySerializer(serializers.ModelSerializer):
    """Serializer للتصنيف"""
    image_url = serializers.SerializerMethodField()
    products_count = serializers.SerializerMethodField()
    
    class Meta:
        model = Category
        fields = ['id', 'name', 'name_en', 'icon', 'image', 'image_url', 
                  'display_order', 'is_active', 'products_count', 'created_at']
        read_only_fields = ['id', 'created_at']
    
    def get_image_url(self, obj):
        if obj.image:
            request = self.context.get('request')
            if request:
                return request.build_absolute_uri(obj.image.url)
            return obj.image.url
        return None
    
    def get_products_count(self, obj):
        return obj.products.filter(is_available=True).count()


# Order Rating Serializers
class OrderRatingSerializer(serializers.ModelSerializer):
    """Serializer لتقييم الطلب"""
    customer_name = serializers.CharField(source='customer.name', read_only=True)
    order_number = serializers.CharField(source='order.order_number', read_only=True)
    
    class Meta:
        model = OrderRating
        fields = ['id', 'order', 'order_number', 'customer', 'customer_name',
                  'shop_rating', 'driver_rating', 'food_rating', 'comment', 'created_at']
        read_only_fields = ['id', 'customer', 'created_at']
    
    def validate_shop_rating(self, value):
        if value < 1 or value > 5:
            raise serializers.ValidationError('التقييم يجب أن يكون بين 1 و 5')
        return value
    
    def validate_driver_rating(self, value):
        if value and (value < 1 or value > 5):
            raise serializers.ValidationError('التقييم يجب أن يكون بين 1 و 5')
        return value
    
    def validate_food_rating(self, value):
        if value and (value < 1 or value > 5):
            raise serializers.ValidationError('التقييم يجب أن يكون بين 1 و 5')
        return value


class OrderRatingCreateSerializer(serializers.Serializer):
    """Serializer لإنشاء تقييم"""
    order_id = serializers.IntegerField(required=False)
    shop_id = serializers.IntegerField(required=False)
    shop_rating = serializers.IntegerField(min_value=1, max_value=5, required=True)
    comment = serializers.CharField(required=False, allow_blank=True)

    def validate(self, attrs):
        if not attrs.get('order_id') and not attrs.get('shop_id'):
            raise serializers.ValidationError({
                'shop_id': ['shop_id or order_id is required.']
            })
        return attrs


class ShopRatingCreateSerializer(serializers.Serializer):
    """Serializer for rating a shop from the customer app."""
    shop_rating = serializers.IntegerField(min_value=1, max_value=5, required=True)
    comment = serializers.CharField(required=False, allow_blank=True)


# Payment Method Serializers
class PaymentMethodSerializer(serializers.ModelSerializer):
    """Serializer لطريقة الدفع"""
    card_type_display = serializers.CharField(source='get_card_type_display', read_only=True)
    
    class Meta:
        model = PaymentMethod
        fields = ['id', 'card_type', 'card_type_display', 'last_four_digits', 
                  'card_holder_name', 'expiry_month', 'expiry_year', 'is_default', 'created_at']
        read_only_fields = ['id', 'created_at']


class PaymentMethodCreateSerializer(serializers.Serializer):
    """Serializer لإضافة طريقة دفع"""
    card_type = serializers.ChoiceField(choices=PaymentMethod.TYPE_CHOICES, required=True)
    card_number = serializers.CharField(required=True, min_length=16, max_length=16)
    card_holder_name = serializers.CharField(required=True)
    expiry_month = serializers.CharField(required=True, min_length=2, max_length=2)
    expiry_year = serializers.CharField(required=True, min_length=4, max_length=4)
    cvv = serializers.CharField(required=True, min_length=3, max_length=4, write_only=True)
    is_default = serializers.BooleanField(default=False)
    
    def validate_card_number(self, value):
        if not value.isdigit():
            raise serializers.ValidationError('رقم البطاقة يجب أن يحتوي على أرقام فقط')
        return value


# Notification Serializers
class NotificationSerializer(serializers.ModelSerializer):
    """Serializer للإشعار"""
    notification_type_display = serializers.CharField(source='get_notification_type_display', read_only=True)
    
    class Meta:
        model = Notification
        fields = ['id', 'notification_type', 'notification_type_display', 
                  'title', 'message', 'data', 'is_read', 'created_at']
        read_only_fields = ['id', 'created_at']


# Cart Serializers
class CartItemSerializer(serializers.ModelSerializer):
    """Serializer لعنصر السلة"""
    product_name = serializers.CharField(source='product.name', read_only=True)
    product_image = serializers.SerializerMethodField()
    unit_price = serializers.DecimalField(max_digits=10, decimal_places=2, read_only=True)
    total_price = serializers.DecimalField(max_digits=10, decimal_places=2, read_only=True)
    
    class Meta:
        model = CartItem
        fields = ['id', 'product', 'product_name', 'product_image', 
                  'quantity', 'notes', 'unit_price', 'total_price']
        read_only_fields = ['id']
    
    def get_product_image(self, obj):
        if obj.product.image:
            request = self.context.get('request')
            if request:
                return request.build_absolute_uri(obj.product.image.url)
            return obj.product.image.url
        return None


class CartSerializer(serializers.ModelSerializer):
    """Serializer للسلة"""
    items = CartItemSerializer(many=True, read_only=True)
    shop_name = serializers.CharField(source='shop_owner.shop_name', read_only=True)
    total_items = serializers.IntegerField(read_only=True)
    subtotal = serializers.DecimalField(max_digits=10, decimal_places=2, read_only=True)
    
    class Meta:
        model = Cart
        fields = ['id', 'shop_owner', 'shop_name', 'items', 'total_items', 'subtotal', 'created_at', 'updated_at']
        read_only_fields = ['id', 'created_at', 'updated_at']


class AddToCartSerializer(serializers.Serializer):
    """Serializer لإضافة منتج للسلة"""
    product_id = serializers.IntegerField(required=True)
    quantity = serializers.IntegerField(min_value=1, default=1)
    notes = serializers.CharField(required=False, allow_blank=True)


class UpdateCartItemSerializer(serializers.Serializer):
    """Serializer لتحديث عنصر في السلة"""
    quantity = serializers.IntegerField(min_value=0, required=True)
    notes = serializers.CharField(required=False, allow_blank=True)


# Driver Location Serializer
class DriverLocationUpdateSerializer(serializers.Serializer):
    """Serializer لتحديث موقع السائق"""
    latitude = serializers.DecimalField(max_digits=10, decimal_places=7, required=True)
    longitude = serializers.DecimalField(max_digits=10, decimal_places=7, required=True)
