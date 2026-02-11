from rest_framework import serializers
from .models import (
    ShopStatus, Customer, CustomerAddress, Driver, Order, ChatMessage, 
    Invoice, Employee, Product, Category, OrderRating, PaymentMethod, 
    Notification, Cart, CartItem
)
from user.models import ShopOwner
from rest_framework_simplejwt.tokens import RefreshToken


class ShopStatusSerializer(serializers.ModelSerializer):
    """Serializer لحالة المتجر"""
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    
    class Meta:
        model = ShopStatus
        fields = ['id', 'status', 'status_display', 'updated_at']
        read_only_fields = ['id', 'updated_at']


class CustomerAddressSerializer(serializers.ModelSerializer):
    """Serializer لعنوان العميل"""
    address_type_display = serializers.CharField(source='get_address_type_display', read_only=True)
    
    class Meta:
        model = CustomerAddress
        fields = ['id', 'title', 'address_type', 'address_type_display', 'full_address', 
                  'latitude', 'longitude', 'building_number', 'floor', 'apartment', 
                  'notes', 'is_default', 'created_at']
        read_only_fields = ['id', 'created_at']


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
    
    class Meta:
        model = Driver
        fields = ['id', 'name', 'phone_number', 'profile_image', 'profile_image_url',
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
        fields = ['name', 'phone_number', 'password', 'profile_image', 'status']
    
    def create(self, validated_data):
        """إنشاء سائق جديد"""
        shop_owner = self.context['shop_owner']
        password = validated_data.pop('password', None)
        driver = Driver.objects.create(shop_owner=shop_owner, **validated_data)
        if password:
            driver.set_password(password)
            driver.save()
        return driver


class ChatMessageSerializer(serializers.ModelSerializer):
    """Serializer لرسائل المحادثة"""
    sender_type_display = serializers.CharField(source='get_sender_type_display', read_only=True)
    chat_type_display = serializers.CharField(source='get_chat_type_display', read_only=True)
    message_type_display = serializers.CharField(source='get_message_type_display', read_only=True)
    sender_name = serializers.CharField(read_only=True)
    sender_id = serializers.SerializerMethodField()
    audio_file_url = serializers.SerializerMethodField()
    image_file_url = serializers.SerializerMethodField()
    
    class Meta:
        model = ChatMessage
        fields = ['id', 'chat_type', 'chat_type_display', 'sender_type', 'sender_type_display',
                  'sender_name', 'sender_id', 'message_type', 'message_type_display',
                  'content', 'audio_file', 'audio_file_url', 'image_file', 'image_file_url',
                  'latitude', 'longitude', 'is_read', 'created_at']
        read_only_fields = ['id', 'created_at']
    
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


class OrderSerializer(serializers.ModelSerializer):
    """Serializer للطلب"""
    customer = CustomerSerializer(read_only=True)
    employee = serializers.SerializerMethodField()
    driver = DriverSerializer(read_only=True)
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    last_message = serializers.SerializerMethodField()
    
    class Meta:
        model = Order
        fields = ['id', 'order_number', 'customer', 'employee', 'driver', 'status', 'status_display',
                  'items', 'total_amount', 'delivery_fee', 'address', 'notes',
                  'unread_messages_count', 'last_message', 'created_at', 'updated_at']
        read_only_fields = ['id', 'order_number', 'created_at', 'updated_at']
    
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


class OrderCreateSerializer(serializers.Serializer):
    """Serializer لإنشاء طلب جديد"""
    customer_id = serializers.IntegerField(required=True)
    employee_id = serializers.IntegerField(required=False, allow_null=True)
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
            Driver.objects.get(id=value, shop_owner=shop_owner)
        except Driver.DoesNotExist:
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
            driver = Driver.objects.get(id=driver_id, shop_owner=shop_owner)
        
        # إنشاء رقم طلب تلقائي
        import random
        order_number = f"{shop_owner.shop_number}{random.randint(1000, 9999)}"
        while Order.objects.filter(order_number=order_number).exists():
            order_number = f"{shop_owner.shop_number}{random.randint(1000, 9999)}"
        
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


class InvoiceSerializer(serializers.ModelSerializer):
    """Serializer للفاتورة"""
    customer = CustomerSerializer(read_only=True)
    order = OrderSerializer(read_only=True)
    
    class Meta:
        model = Invoice
        fields = ['id', 'invoice_number', 'customer', 'order', 'items', 'total_amount',
                  'delivery_fee', 'address', 'phone_number', 'is_sent', 'sent_at', 'created_at']
        read_only_fields = ['id', 'invoice_number', 'sent_at', 'created_at']


class ProductSerializer(serializers.ModelSerializer):
    """Serializer للمنتج"""
    image_url = serializers.SerializerMethodField()
    
    class Meta:
        model = Product
        fields = ['id', 'name', 'description', 'price', 'image', 'image_url', 'display_order', 'is_available', 'created_at', 'updated_at']
        read_only_fields = ['id', 'created_at', 'updated_at']
    
    def get_image_url(self, obj):
        if obj.image:
            request = self.context.get('request')
            if request:
                return request.build_absolute_uri(obj.image.url)
            return obj.image.url
        return None


class ProductCreateSerializer(serializers.ModelSerializer):
    """Serializer لإنشاء/تحديث منتج"""
    
    class Meta:
        model = Product
        fields = ['name', 'description', 'price', 'image', 'display_order', 'is_available']


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
        phone_number = attrs.get('phone_number')
        password = attrs.get('password')
        
        try:
            employee = Employee.objects.get(phone_number=phone_number, is_active=True)
        except Employee.DoesNotExist:
            raise serializers.ValidationError({
                'phone_number': 'رقم الهاتف غير صحيح أو الحساب غير نشط'
            })
        
        if not employee.check_password(password):
            raise serializers.ValidationError({
                'password': 'كلمة المرور غير صحيحة'
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
    
    @classmethod
    def get_token(cls, driver):
        """
        إنشاء token مع driver_id
        """
        token = RefreshToken()
        token['driver_id'] = driver.id
        token['phone_number'] = driver.phone_number
        token['shop_owner_id'] = driver.shop_owner.id
        token['user_type'] = 'driver'
        return token
    
    def validate(self, attrs):
        """
        التحقق من بيانات تسجيل الدخول وإرجاع token
        """
        phone_number = attrs.get('phone_number')
        password = attrs.get('password')
        
        try:
            driver = Driver.objects.get(phone_number=phone_number)
        except Driver.DoesNotExist:
            raise serializers.ValidationError({
                'phone_number': 'رقم الهاتف غير صحيح'
            })
        
        if not driver.password or not driver.check_password(password):
            raise serializers.ValidationError({
                'password': 'كلمة المرور غير صحيحة أو غير معينة'
            })
        
        refresh = self.get_token(driver)
        
        return {
            'refresh': str(refresh),
            'access': str(refresh.access_token),
            'driver': {
                'id': driver.id,
                'name': driver.name,
                'phone_number': driver.phone_number,
                'status': driver.status,
                'status_display': driver.get_status_display(),
                'shop_owner_id': driver.shop_owner.id,
            }
        }


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
    order_id = serializers.IntegerField(required=True)
    shop_rating = serializers.IntegerField(min_value=1, max_value=5, required=True)
    driver_rating = serializers.IntegerField(min_value=1, max_value=5, required=False)
    food_rating = serializers.IntegerField(min_value=1, max_value=5, required=False)
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
