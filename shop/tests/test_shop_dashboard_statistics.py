from datetime import timedelta

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIRequestFactory, force_authenticate

from shop.models import Customer, Driver, Invoice, Order, ShopDriver
from shop.views import shop_dashboard_statistics_view
from user.models import ShopCategory, ShopOwner


class ShopDashboardStatisticsViewTests(TestCase):
    def setUp(self):
        super().setUp()
        self.factory = APIRequestFactory()
        self.category = ShopCategory.objects.create(name='Reports')
        self.shop = ShopOwner.objects.create(
            owner_name='صاحب التقرير',
            shop_name='متجر التقرير',
            shop_number='SHOP-RPT-001',
            phone_number='01020010001',
            password='secret123',
            shop_category=self.category,
        )
        self.customer = Customer.objects.create(
            shop_owner=self.shop,
            name='عميل التقرير',
            phone_number='01020010002',
            password='secret123',
        )
        self.driver = Driver.objects.create(
            name='سائق التقرير',
            phone_number='01020010003',
            password='secret123',
            status='busy',
        )
        ShopDriver.objects.create(shop_owner=self.shop, driver=self.driver, status='active')

    def _create_order(self, *, status, total_amount, payment_method='cash', delivered_at=None, updated_at=None, created_at=None, driver=None):
        order = Order.objects.create(
            shop_owner=self.shop,
            customer=self.customer,
            driver=driver,
            order_number=f'ORD-{Order.objects.count() + 1:06d}',
            status=status,
            items='["Item"]',
            total_amount=total_amount,
            delivery_fee='10.00',
            address='عنوان',
            payment_method=payment_method,
            is_paid=payment_method != 'cash',
            driver_assigned_at=timezone.now() if driver else None,
            driver_accepted_at=timezone.now() if driver else None,
            delivered_at=delivered_at,
        )
        updates = {}
        if created_at is not None:
            updates['created_at'] = created_at
        if updated_at is not None:
            updates['updated_at'] = updated_at
        if updates:
            Order.objects.filter(pk=order.pk).update(**updates)
        return Order.objects.get(pk=order.pk)

    def _create_invoice(self, *, order, is_sent, sent_at=None):
        invoice = Invoice.objects.create(
            shop_owner=self.shop,
            customer=self.customer,
            order=order,
            invoice_number=f'INV-{Invoice.objects.count() + 1:06d}',
            items='[]',
            total_amount=order.total_amount,
            delivery_fee=order.delivery_fee,
            address=order.address,
            phone_number=self.customer.phone_number,
            is_sent=is_sent,
            sent_at=sent_at,
        )
        if sent_at is not None:
            Invoice.objects.filter(pk=invoice.pk).update(sent_at=sent_at)
        return Invoice.objects.get(pk=invoice.pk)

    def _call_view(self, period=None):
        url = '/api/shop/dashboard/statistics/'
        if period:
            url = f'{url}?period={period}'
        request = self.factory.get(url)
        force_authenticate(request, user=self.shop)
        return shop_dashboard_statistics_view(request)

    def test_current_cash_with_drivers_excludes_electronic_orders(self):
        now = timezone.now()
        self._create_order(status='preparing', total_amount='100.00', payment_method='cash', driver=self.driver, created_at=now)
        self._create_order(status='on_way', total_amount='200.00', payment_method='card', driver=self.driver, created_at=now)
        self._create_order(status='delivered', total_amount='590.00', payment_method='cash', driver=self.driver, delivered_at=now, created_at=now)
        self._create_order(status='cancelled', total_amount='50.00', payment_method='cash', created_at=now, updated_at=now)

        response = self._call_view()

        self.assertEqual(response.status_code, 200)
        cash = response.data['data']['cash']
        self.assertEqual(cash['withDrivers'], 100)
        self.assertEqual(cash['inTreasury'], 590)
        self.assertEqual(cash['totalAvailable'], 690)
        self.assertEqual(cash['currency'], 'SAR')

    def test_report_counts_delivered_and_cancelled_orders_only(self):
        now = timezone.now()
        self._create_order(status='delivered', total_amount='120.00', payment_method='cash', driver=self.driver, delivered_at=now, created_at=now)
        self._create_order(status='delivered', total_amount='130.00', payment_method='cash', driver=self.driver, delivered_at=now, created_at=now)
        self._create_order(status='cancelled', total_amount='40.00', payment_method='cash', created_at=now, updated_at=now)
        self._create_order(status='new', total_amount='10.00', payment_method='cash', created_at=now)

        response = self._call_view()

        self.assertEqual(response.status_code, 200)
        data = response.data['data']
        self.assertEqual(data['totalOrders'], 3)
        self.assertEqual(data['deliveredOrdersCount'], 2)
        self.assertEqual(data['cancelledOrdersCount'], 1)
        self.assertEqual(data['deliveryStatus']['successRate'], 66.67)
        self.assertEqual(data['successRate'], 66.67)

    def test_approved_invoices_count_only_includes_sent_and_approved(self):
        now = timezone.now()
        approved_order = self._create_order(status='confirmed', total_amount='100.00', payment_method='cash', driver=self.driver, created_at=now)
        pending_order = self._create_order(status='pending_customer_confirm', total_amount='110.00', payment_method='cash', created_at=now)
        rejected_order = self._create_order(status='cancelled', total_amount='120.00', payment_method='cash', created_at=now, updated_at=now)
        self._create_invoice(order=approved_order, is_sent=True, sent_at=now)
        self._create_invoice(order=pending_order, is_sent=True, sent_at=now)
        self._create_invoice(order=rejected_order, is_sent=True, sent_at=now)
        self._create_invoice(order=approved_order, is_sent=False, sent_at=None)

        response = self._call_view()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['data']['approvedInvoicesCount'], 1)
        self.assertEqual(response.data['data']['invoices_count'], 1)

    def test_period_filter_uses_final_state_dates_and_keeps_cash_current(self):
        now = timezone.now()
        yesterday = now - timedelta(days=1)
        self._create_order(status='delivered', total_amount='100.00', payment_method='cash', driver=self.driver, delivered_at=yesterday, created_at=yesterday)
        cancelled_today = self._create_order(status='cancelled', total_amount='50.00', payment_method='cash', created_at=now, updated_at=now)
        self._create_order(status='preparing', total_amount='75.00', payment_method='cash', driver=self.driver, created_at=now)
        self._create_invoice(order=cancelled_today, is_sent=True, sent_at=now)
        self._create_invoice(order=cancelled_today, is_sent=True, sent_at=yesterday)

        response = self._call_view(period='daily')

        self.assertEqual(response.status_code, 200)
        data = response.data['data']
        self.assertEqual(data['totalOrders'], 1)
        self.assertEqual(data['deliveredOrdersCount'], 0)
        self.assertEqual(data['cancelledOrdersCount'], 1)
        self.assertEqual(data['approvedInvoicesCount'], 0)
        self.assertEqual(data['cash']['inTreasury'], 100)
        self.assertEqual(data['cash']['withDrivers'], 75)

    def test_empty_report_returns_zero_success_rate(self):
        response = self._call_view()

        self.assertEqual(response.status_code, 200)
        data = response.data['data']
        self.assertEqual(data['totalOrders'], 0)
        self.assertEqual(data['successRate'], 0.0)
        self.assertEqual(data['deliveryStatus']['successRate'], 0.0)
