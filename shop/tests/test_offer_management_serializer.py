from datetime import timedelta

from django.test import TestCase
from django.utils import timezone

from shop.models import Offer
from shop.serializers import OfferManagementSerializer
from user.models import AdminApprovalRequest, ShopCategory, ShopOwner


class OfferManagementSerializerTests(TestCase):
    def setUp(self):
        super().setUp()
        self.category = ShopCategory.objects.create(name='Offers')
        self.shop = ShopOwner.objects.create(
            owner_name='صاحب المحل',
            shop_name='محل العروض',
            shop_number='SHOP-OFFER-001',
            phone_number='01010010001',
            password='secret123',
            shop_category=self.category,
        )

    def _create_offer(self, *, is_active=True):
        today = timezone.localdate()
        return Offer.objects.create(
            shop_owner=self.shop,
            title='عرض تجريبي',
            description='وصف العرض',
            discount_percentage='15.00',
            start_date=today,
            end_date=today + timedelta(days=5),
            is_active=is_active,
        )

    def test_returns_published_status_for_approved_offer_request(self):
        offer = self._create_offer(is_active=True)
        AdminApprovalRequest.objects.create(
            shop_owner=self.shop,
            request_type='offer',
            status='approved',
            offer=offer,
            payload={},
        )

        data = OfferManagementSerializer(offer).data

        self.assertEqual(data['review_status'], 'published')
        self.assertEqual(data['review_status_display'], 'اتنشرت')
        self.assertIsNone(data['rejection_reason'])

    def test_returns_pending_review_status_for_pending_offer_request(self):
        offer = self._create_offer(is_active=False)
        AdminApprovalRequest.objects.create(
            shop_owner=self.shop,
            request_type='offer',
            status='pending',
            offer=offer,
            payload={},
        )

        data = OfferManagementSerializer(offer).data

        self.assertEqual(data['review_status'], 'pending_review')
        self.assertEqual(data['review_status_display'], 'قيد المراجعة')
        self.assertIsNone(data['rejection_reason'])

    def test_returns_rejected_status_and_rejection_reason(self):
        offer = self._create_offer(is_active=False)
        AdminApprovalRequest.objects.create(
            shop_owner=self.shop,
            request_type='offer',
            status='rejected',
            offer=offer,
            rejection_reason='الصورة غير مطابقة',
            payload={},
        )

        data = OfferManagementSerializer(offer).data

        self.assertEqual(data['review_status'], 'rejected')
        self.assertEqual(data['review_status_display'], 'مرفوضة')
        self.assertEqual(data['rejection_reason'], 'الصورة غير مطابقة')
