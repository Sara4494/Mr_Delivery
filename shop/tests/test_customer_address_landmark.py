from django.test import TestCase
from rest_framework.test import APIClient

from shop.models import Customer, CustomerAddress, Order
from shop.realtime.driver import build_driver_order_payload
from user.models import ShopCategory, ShopOwner


class CustomerAddressLandmarkApiTests(TestCase):
    def setUp(self):
        super().setUp()
        self.client = APIClient()
        self.category = ShopCategory.objects.create(name='Groceries')
        self.shop = ShopOwner.objects.create(
            owner_name='Shop Owner',
            shop_name='Landmark Store',
            shop_number='SHOP-LANDMARK-001',
            phone_number='01010040001',
            password='secret123',
            shop_category=self.category,
        )
        self.customer = Customer.objects.create(
            shop_owner=self.shop,
            name='Landmark Customer',
            phone_number='01010040002',
            email='landmark.customer@example.com',
            password='secret123',
            is_verified=True,
        )
        self.client.force_authenticate(user=self.customer)

    def _address_payload(self, **overrides):
        payload = {
            'city': 'الفيوم',
            'area': 'السواقي',
            'street_name': 'شارع السنترال',
            'landmark': 'بجوار محطة الوقود',
            'building_number': '1',
            'floor': '2',
            'is_default': False,
        }
        payload.update(overrides)
        return payload

    def test_create_address_returns_landmark_and_get_list_keeps_it(self):
        create_response = self.client.post(
            '/api/customer/addresses/',
            self._address_payload(),
            format='json',
        )

        self.assertEqual(create_response.status_code, 201)
        self.assertEqual(create_response.data['data']['landmark'], 'بجوار محطة الوقود')

        address_id = create_response.data['data']['id']
        detail_response = self.client.get(f'/api/customer/addresses/{address_id}/')

        self.assertEqual(detail_response.status_code, 200)
        self.assertEqual(detail_response.data['data']['landmark'], 'بجوار محطة الوقود')

        list_response = self.client.get('/api/customer/addresses/')

        self.assertEqual(list_response.status_code, 200)
        self.assertEqual(list_response.data['data'][0]['landmark'], 'بجوار محطة الوقود')

    def test_update_address_allows_changing_and_clearing_landmark(self):
        address = CustomerAddress.objects.create(
            customer=self.customer,
            title='الفيوم',
            address_type='home',
            full_address='الفيوم، السواقي، شارع السنترال، بجوار محطة الوقود، مبنى 1، طابق 2',
            city='الفيوم',
            area='السواقي',
            street_name='شارع السنترال',
            landmark='بجوار محطة الوقود',
            building_number='1',
            floor='2',
            is_default=False,
        )

        update_response = self.client.put(
            f'/api/customer/addresses/{address.id}/',
            {'landmark': 'خلف المدرسة'},
            format='json',
        )
        self.assertEqual(update_response.status_code, 200)
        self.assertEqual(update_response.data['data']['landmark'], 'خلف المدرسة')

        clear_response = self.client.put(
            f'/api/customer/addresses/{address.id}/',
            {'landmark': ''},
            format='json',
        )
        self.assertEqual(clear_response.status_code, 200)
        self.assertIsNone(clear_response.data['data']['landmark'])

        address.refresh_from_db()
        self.assertIsNone(address.landmark)
        self.assertNotIn('خلف المدرسة', address.full_address)

    def test_default_address_in_profile_includes_landmark_and_persists_after_new_login(self):
        address = CustomerAddress.objects.create(
            customer=self.customer,
            title='الفيوم',
            address_type='home',
            full_address='الفيوم، السواقي، شارع السنترال، بجوار محطة الوقود، مبنى 1، طابق 2',
            city='الفيوم',
            area='السواقي',
            street_name='شارع السنترال',
            landmark='بجوار محطة الوقود',
            building_number='1',
            floor='2',
            is_default=True,
        )

        profile_response = self.client.get('/api/customer/profile/')
        self.assertEqual(profile_response.status_code, 200)
        self.assertEqual(profile_response.data['data']['default_address']['landmark'], 'بجوار محطة الوقود')

        second_client = APIClient()
        second_client.force_authenticate(user=self.customer)
        second_list_response = second_client.get('/api/customer/addresses/')

        self.assertEqual(second_list_response.status_code, 200)
        self.assertEqual(second_list_response.data['data'][0]['landmark'], 'بجوار محطة الوقود')

        address.refresh_from_db()
        self.assertEqual(address.landmark, 'بجوار محطة الوقود')

    def test_driver_order_payload_uses_landmark_in_address_text(self):
        address = CustomerAddress.objects.create(
            customer=self.customer,
            title='الفيوم',
            address_type='home',
            full_address='الفيوم، السواقي، شارع السنترال، بجوار محطة الوقود، مبنى 1، طابق 2',
            city='الفيوم',
            area='السواقي',
            street_name='شارع السنترال',
            landmark='بجوار محطة الوقود',
            building_number='1',
            floor='2',
            is_default=True,
        )
        order = Order.objects.create(
            shop_owner=self.shop,
            customer=self.customer,
            order_number='OD-LANDMARK-1',
            status='preparing',
            items='["meal"]',
            total_amount='80.00',
            delivery_fee='10.00',
            address='',
            notes='',
            delivery_address=address,
        )

        payload = build_driver_order_payload(order)

        self.assertEqual(
            payload['delivery_address']['text'],
            'الفيوم، السواقي، شارع السنترال، بجوار محطة الوقود، مبنى 1، طابق 2',
        )
        self.assertEqual(payload['delivery_address']['landmark'], 'بجوار محطة الوقود')
