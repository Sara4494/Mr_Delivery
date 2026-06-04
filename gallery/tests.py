from datetime import datetime
from unittest.mock import patch

from django.test import TestCase
from django.utils import timezone

from gallery.views import broadcast_shop_portfolio_snapshot
from user.models import AdminApprovalRequest, ShopCategory, ShopOwner


class _FakeChannelLayer:
    def __init__(self):
        self.calls = []

    async def group_send(self, group_name, message):
        self.calls.append((group_name, message))


class ShopPortfolioBroadcastTests(TestCase):
    def setUp(self):
        super().setUp()
        self.category = ShopCategory.objects.create(name='Gallery')
        self.shop_owner = ShopOwner.objects.create(
            owner_name='Shop Owner',
            shop_name='Portfolio Shop',
            shop_number='PORTFOLIO-001',
            phone_number='01000000001',
            password='secret123',
            shop_category=self.category,
        )
        self.approval_request = AdminApprovalRequest.objects.create(
            shop_owner=self.shop_owner,
            request_type='shop_edit',
            status='pending',
            payload={
                'owner_name': 'Shop Owner',
                'shop_name': 'Portfolio Shop',
                'phone_number': '01000000001',
                'description': 'Updated description',
            },
            reviewed_at=timezone.now(),
        )

    def _assert_no_datetimes(self, value):
        if isinstance(value, datetime):
            self.fail(f'Found raw datetime in broadcast payload: {value!r}')
        if isinstance(value, dict):
            for nested_value in value.values():
                self._assert_no_datetimes(nested_value)
        elif isinstance(value, (list, tuple)):
            for nested_value in value:
                self._assert_no_datetimes(nested_value)

    def test_broadcast_shop_portfolio_snapshot_serializes_datetimes(self):
        channel_layer = _FakeChannelLayer()

        with patch('gallery.views.get_channel_layer', return_value=channel_layer):
            broadcast_shop_portfolio_snapshot(self.shop_owner, viewer_user=self.shop_owner)

        self.assertEqual(len(channel_layer.calls), 1)
        group_name, message = channel_layer.calls[0]
        self.assertEqual(group_name, f'shop_orders_{self.shop_owner.id}')
        self.assertEqual(message['type'], 'shop_portfolio_snapshot')
        self._assert_no_datetimes(message['data'])

        latest_edit_request = message['data']['profile']['latest_edit_request']
        self.assertIsInstance(latest_edit_request['created_at'], str)
        self.assertIsInstance(latest_edit_request['reviewed_at'], str)
