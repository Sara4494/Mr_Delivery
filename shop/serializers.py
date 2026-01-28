from rest_framework import serializers
from .models import ShopStatus, Customer, Driver, Order, ChatMessage, Invoice
from user.models import ShopOwner


class ShopStatusSerializer(serializers.ModelSerializer):
    """Serializer لحالة المتجر"""
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    
    class Meta:
        model = ShopStatus
        fields = ['id', 'status', 'status_display', 'updated_at']
        read_only_fields = ['id', 'updated_at']


class CustomerSerializer(serializers.ModelSerializer):
    """Serializer للعميل"""
    profile_image_url = serializers.SerializerMethodField()
    unread_messages_count = serializers.SerializerMethodField()
    last_message = serializers.SerializerMethodField()
    
    class Meta:
        model = Customer
        fields = ['id', 'name', 'phone_number', 'address', 'profile_image', 'profile_image_url',
                  'is_online', 'unread_messages_count', 'last_message', 'created_at', 'updated_at']
        read_only_fields = ['id', 'created_at', 'updated_at']
    
    def get_profile_image_url(self, obj):
        """إرجاع رابط صورة العميل الكامل"""
        if obj.profile_image:
            request = self.context.get('request')
            if request:
                return request.build_absolute_uri(obj.profile_image.url)
            return obj.profile_image.url
        return None
    
    def get_unread_messages_count(self, obj):
        """عدد الرسائل غير المقروءة للعميل"""
        return sum(order.unread_messages_count for order in obj.orders.all())
    
    def get_last_message(self, obj):
        """آخر رسالة من العميل"""
        last_order = obj.orders.order_by('-updated_at').first()
        if last_order:
            last_message = last_order.messages.order_by('-created_at').first()
            if last_message:
                return {
                    'content': last_message.content[:50] + '...' if len(last_message.content) > 50 else last_message.content,
                    'created_at': last_message.created_at
                }
        return None


class CustomerCreateSerializer(serializers.ModelSerializer):
    """Serializer لإنشاء عميل جديد"""
    
    class Meta:
        model = Customer
        fields = ['name', 'phone_number', 'address', 'profile_image']
    
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
    
    class Meta:
        model = Driver
        fields = ['id', 'name', 'phone_number', 'profile_image', 'profile_image_url',
                  'status', 'status_display', 'current_orders_count', 'created_at', 'updated_at']
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
    
    class Meta:
        model = Driver
        fields = ['name', 'phone_number', 'profile_image', 'status']
    
    def create(self, validated_data):
        """إنشاء سائق جديد"""
        shop_owner = self.context['shop_owner']
        return Driver.objects.create(shop_owner=shop_owner, **validated_data)


class ChatMessageSerializer(serializers.ModelSerializer):
    """Serializer لرسائل المحادثة"""
    sender_type_display = serializers.CharField(source='get_sender_type_display', read_only=True)
    message_type_display = serializers.CharField(source='get_message_type_display', read_only=True)
    audio_file_url = serializers.SerializerMethodField()
    image_file_url = serializers.SerializerMethodField()
    
    class Meta:
        model = ChatMessage
        fields = ['id', 'sender_type', 'sender_type_display', 'message_type', 'message_type_display',
                  'content', 'audio_file', 'audio_file_url', 'image_file', 'image_file_url',
                  'is_read', 'created_at']
        read_only_fields = ['id', 'created_at']
    
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


class OrderSerializer(serializers.ModelSerializer):
    """Serializer للطلب"""
    customer = CustomerSerializer(read_only=True)
    driver = DriverSerializer(read_only=True)
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    last_message = serializers.SerializerMethodField()
    
    class Meta:
        model = Order
        fields = ['id', 'order_number', 'customer', 'driver', 'status', 'status_display',
                  'items', 'total_amount', 'delivery_fee', 'address', 'notes',
                  'unread_messages_count', 'last_message', 'created_at', 'updated_at']
        read_only_fields = ['id', 'order_number', 'created_at', 'updated_at']
    
    def get_last_message(self, obj):
        """آخر رسالة في الطلب"""
        last_message = obj.messages.order_by('-created_at').first()
        if last_message:
            serializer = ChatMessageSerializer(last_message, context=self.context)
            return serializer.data
        return None


class OrderCreateSerializer(serializers.Serializer):
    """Serializer لإنشاء طلب جديد"""
    customer_id = serializers.IntegerField(required=True)
    driver_id = serializers.IntegerField(required=False, allow_null=True)
    items = serializers.CharField(required=True)
    total_amount = serializers.DecimalField(max_digits=10, decimal_places=2, required=True)
    delivery_fee = serializers.DecimalField(max_digits=10, decimal_places=2, default=0)
    address = serializers.CharField(required=True)
    notes = serializers.CharField(required=False, allow_blank=True)
    
    def validate_customer_id(self, value):
        """التحقق من وجود العميل"""
        shop_owner = self.context['shop_owner']
        try:
            Customer.objects.get(id=value, shop_owner=shop_owner)
        except Customer.DoesNotExist:
            raise serializers.ValidationError('العميل غير موجود')
        return value
    
    def validate_driver_id(self, value):
        """التحقق من وجود السائق"""
        if value is None:
            return value
        shop_owner = self.context['shop_owner']
        try:
            Driver.objects.get(id=value, shop_owner=shop_owner)
        except Driver.DoesNotExist:
            raise serializers.ValidationError('السائق غير موجود')
        return value
    
    def create(self, validated_data):
        """إنشاء طلب جديد"""
        shop_owner = self.context['shop_owner']
        customer_id = validated_data.pop('customer_id')
        driver_id = validated_data.pop('driver_id', None)
        
        customer = Customer.objects.get(id=customer_id, shop_owner=shop_owner)
        
        driver = None
        if driver_id:
            driver = Driver.objects.get(id=driver_id, shop_owner=shop_owner)
        
        # إنشاء رقم طلب تلقائي
        import random
        order_number = f"{shop_owner.shop_number}{random.randint(1000, 9999)}"
        while Order.objects.filter(order_number=order_number).exists():
            order_number = f"{shop_owner.shop_number}{random.randint(1000, 9999)}"
        
        order = Order.objects.create(
            shop_owner=shop_owner,
            customer=customer,
            driver=driver,
            order_number=order_number,
            **validated_data
        )
        
        # تحديث عدد الطلبات للسائق
        if driver:
            driver.current_orders_count = driver.orders.filter(status__in=['new', 'preparing', 'on_way']).count()
            driver.save()
        
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


class InvoiceCreateSerializer(serializers.Serializer):
    """Serializer لإنشاء فاتورة سريعة"""
    customer_name = serializers.CharField(required=True)
    phone_number = serializers.CharField(required=True)
    address = serializers.CharField(required=True)
    items = serializers.CharField(required=True)
    amount = serializers.DecimalField(max_digits=10, decimal_places=2, required=True)
    delivery = serializers.DecimalField(max_digits=10, decimal_places=2, default=0)
