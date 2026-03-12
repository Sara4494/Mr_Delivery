from datetime import timedelta

from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

from shop.models import Customer, Employee, Offer
from user.models import ShopCategory, ShopOwner


class OfferAPITests(APITestCase):
    def setUp(self):
        self.shop_category = ShopCategory.objects.create(name='Restaurant')
        self.shop_owner = ShopOwner.objects.create(
            owner_name='Owner One',
            shop_name='Shop One',
            shop_number='1001',
            shop_category=self.shop_category,
            phone_number='01000000001',
            password='secret123',
        )
        self.customer = Customer.objects.create(
            name='Customer One',
            phone_number='01000000002',
            password='secret123',
        )
        self.employee = Employee.objects.create(
            shop_owner=self.shop_owner,
            name='Employee One',
            phone_number='01000000003',
            password='secret123',
            role='manager',
        )
        self.public_offers_url = reverse('shop:public_offers')
        self.shop_offers_url = reverse('shop:offer_list')

    def _create_offer(self, **kwargs):
        today = timezone.localdate()
        payload = {
            'shop_owner': self.shop_owner,
            'title': 'Offer title',
            'description': 'Offer description',
            'discount_percentage': '20.00',
            'start_date': today - timedelta(days=1),
            'end_date': today + timedelta(days=2),
            'is_active': True,
        }
        payload.update(kwargs)
        return Offer.objects.create(**payload)

    def test_shop_owner_can_create_offer_and_receive_scheduled_status(self):
        self.client.force_authenticate(user=self.shop_owner)
        today = timezone.localdate()

        response = self.client.post(
            self.shop_offers_url,
            {
                'title': 'Spring offer',
                'description': 'Scheduled campaign',
                'discount_percentage': '15.50',
                'start_date': str(today + timedelta(days=2)),
                'end_date': str(today + timedelta(days=5)),
                'is_active': True,
            },
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data['data']['status'], 'scheduled')
        self.assertEqual(Offer.objects.count(), 1)

    def test_offer_creation_rejects_end_date_before_start_date(self):
        self.client.force_authenticate(user=self.shop_owner)
        today = timezone.localdate()

        response = self.client.post(
            self.shop_offers_url,
            {
                'title': 'Broken offer',
                'discount_percentage': '10.00',
                'start_date': str(today + timedelta(days=3)),
                'end_date': str(today + timedelta(days=1)),
            },
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('end_date', response.data['errors'])

    def test_public_offers_returns_only_active_paginated_offers_without_views_count(self):
        today = timezone.localdate()
        active_offer = self._create_offer(title='Active')
        self._create_offer(
            title='Scheduled',
            start_date=today + timedelta(days=1),
            end_date=today + timedelta(days=3),
        )
        self._create_offer(
            title='Expired',
            start_date=today - timedelta(days=5),
            end_date=today - timedelta(days=1),
        )

        self.client.force_authenticate(user=self.customer)
        response = self.client.get(self.public_offers_url, {'page_size': 10})

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['data']['count'], 1)
        self.assertEqual(response.data['data']['results'][0]['id'], active_offer.id)
        self.assertNotIn('views_count', response.data['data']['results'][0])

    def test_public_offers_increments_views_for_each_page_only(self):
        offer_one = self._create_offer(title='Offer 1')
        offer_two = self._create_offer(title='Offer 2')
        offer_three = self._create_offer(title='Offer 3')

        self.client.force_authenticate(user=self.customer)

        page_one_response = self.client.get(self.public_offers_url, {'page': 1, 'page_size': 2})
        self.assertEqual(page_one_response.status_code, status.HTTP_200_OK)
        page_one_ids = {item['id'] for item in page_one_response.data['data']['results']}

        offer_one.refresh_from_db()
        offer_two.refresh_from_db()
        offer_three.refresh_from_db()

        expected_after_page_one = {
            offer_one.id: 1 if offer_one.id in page_one_ids else 0,
            offer_two.id: 1 if offer_two.id in page_one_ids else 0,
            offer_three.id: 1 if offer_three.id in page_one_ids else 0,
        }
        self.assertEqual(offer_one.views_count, expected_after_page_one[offer_one.id])
        self.assertEqual(offer_two.views_count, expected_after_page_one[offer_two.id])
        self.assertEqual(offer_three.views_count, expected_after_page_one[offer_three.id])

        page_two_response = self.client.get(self.public_offers_url, {'page': 2, 'page_size': 2})
        self.assertEqual(page_two_response.status_code, status.HTTP_200_OK)
        page_two_ids = {item['id'] for item in page_two_response.data['data']['results']}

        offer_one.refresh_from_db()
        offer_two.refresh_from_db()
        offer_three.refresh_from_db()

        expected_after_page_two = {
            offer_one.id: expected_after_page_one[offer_one.id] + (1 if offer_one.id in page_two_ids else 0),
            offer_two.id: expected_after_page_one[offer_two.id] + (1 if offer_two.id in page_two_ids else 0),
            offer_three.id: expected_after_page_one[offer_three.id] + (1 if offer_three.id in page_two_ids else 0),
        }
        self.assertEqual(offer_one.views_count, expected_after_page_two[offer_one.id])
        self.assertEqual(offer_two.views_count, expected_after_page_two[offer_two.id])
        self.assertEqual(offer_three.views_count, expected_after_page_two[offer_three.id])

    def test_reopening_same_public_page_increments_views_again(self):
        offer_one = self._create_offer(title='Offer 1')
        offer_two = self._create_offer(title='Offer 2')

        self.client.force_authenticate(user=self.customer)
        self.client.get(self.public_offers_url, {'page': 1, 'page_size': 2})
        self.client.get(self.public_offers_url, {'page': 1, 'page_size': 2})

        offer_one.refresh_from_db()
        offer_two.refresh_from_db()
        self.assertEqual(offer_one.views_count, 2)
        self.assertEqual(offer_two.views_count, 2)

    def test_employee_can_view_offer_list_with_views_count_and_status(self):
        offer = self._create_offer(title='Employee visible', views_count=9)

        self.client.force_authenticate(user=self.employee)
        response = self.client.get(self.shop_offers_url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['data']['results'][0]['id'], offer.id)
        self.assertIn('views_count', response.data['data']['results'][0])
        self.assertIn('status', response.data['data']['results'][0])

    def test_employee_cannot_create_update_or_delete_offer(self):
        offer = self._create_offer(title='Locked offer')
        detail_url = reverse('shop:offer_detail', kwargs={'offer_id': offer.id})

        self.client.force_authenticate(user=self.employee)

        create_response = self.client.post(
            self.shop_offers_url,
            {
                'title': 'Blocked create',
                'discount_percentage': '10.00',
                'start_date': str(timezone.localdate()),
                'end_date': str(timezone.localdate() + timedelta(days=1)),
            },
            format='json',
        )
        update_response = self.client.put(
            detail_url,
            {'title': 'Updated by employee'},
            format='json',
        )
        delete_response = self.client.delete(detail_url)

        self.assertEqual(create_response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(update_response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(delete_response.status_code, status.HTTP_403_FORBIDDEN)

    def test_offer_cleanup_deletes_only_items_older_than_seven_days_after_expiry(self):
        today = timezone.localdate()
        old_offer = self._create_offer(
            title='Old expired',
            start_date=today - timedelta(days=12),
            end_date=today - timedelta(days=8),
        )
        recent_offer = self._create_offer(
            title='Recent expired',
            start_date=today - timedelta(days=5),
            end_date=today - timedelta(days=3),
        )

        self.client.force_authenticate(user=self.shop_owner)
        response = self.client.get(self.shop_offers_url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertFalse(Offer.objects.filter(id=old_offer.id).exists())
        self.assertTrue(Offer.objects.filter(id=recent_offer.id).exists())

    def test_shop_offer_list_supports_sort_by_most_viewed(self):
        first = self._create_offer(title='Least viewed', views_count=1)
        second = self._create_offer(title='Most viewed', views_count=11)
        third = self._create_offer(title='Middle viewed', views_count=5)

        self.client.force_authenticate(user=self.shop_owner)
        response = self.client.get(self.shop_offers_url, {'sort_by': 'most_viewed', 'page_size': 10})

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        returned_ids = [item['id'] for item in response.data['data']['results']]
        self.assertEqual(returned_ids, [second.id, third.id, first.id])

    def test_shop_offer_list_supports_expired_status_filter_within_grace_window(self):
        today = timezone.localdate()
        recent_expired = self._create_offer(
            title='Recent expired',
            start_date=today - timedelta(days=4),
            end_date=today - timedelta(days=2),
        )
        self._create_offer(
            title='Old expired',
            start_date=today - timedelta(days=15),
            end_date=today - timedelta(days=8),
        )
        self._create_offer(title='Active now')
        self._create_offer(
            title='Scheduled later',
            start_date=today + timedelta(days=1),
            end_date=today + timedelta(days=4),
        )

        self.client.force_authenticate(user=self.shop_owner)
        response = self.client.get(self.shop_offers_url, {'status': 'expired', 'page_size': 10})

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        returned_ids = [item['id'] for item in response.data['data']['results']]
        self.assertEqual(returned_ids, [recent_expired.id])
