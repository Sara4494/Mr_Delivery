from types import SimpleNamespace

from django.test import TestCase
from django.utils import timezone

from shop.chat_ring_service import (
    _normalize_chat_ring_status,
    _ring_payload_for_status,
    _ring_status_display,
)


class ChatRingServiceTests(TestCase):
    def _make_ring(self, status='timeout'):
        now = timezone.now()
        return SimpleNamespace(
            public_id='ring_70',
            chat_id='order_40_driver_customer',
            order_id=40,
            chat_type='driver_customer',
            sender_id=7,
            receiver_id=9,
            sender_type='driver',
            receiver_type='customer',
            status=status,
            metadata={'sender_name': 'Driver One', 'sender_avatar': ''},
            updated_at=now,
            answered_at=now if status == 'answered' else None,
            dismissed_at=now if status == 'dismissed' else None,
            timed_out_at=now if status == 'timeout' else None,
            cancelled_at=now if status == 'cancelled' else None,
        )

    def test_normalizes_public_status_aliases(self):
        self.assertEqual(_normalize_chat_ring_status('accepted'), ('answered', 'accepted'))
        self.assertEqual(_normalize_chat_ring_status('rejected'), ('dismissed', 'rejected'))
        self.assertEqual(_normalize_chat_ring_status('missed'), ('timeout', 'missed'))
        self.assertEqual(_normalize_chat_ring_status('ended'), ('cancelled', 'ended'))

    def test_ring_status_payload_uses_public_status_and_terminal_flags(self):
        ring = self._make_ring('timeout')

        payload = _ring_payload_for_status(ring, 'timeout', lang='ar')

        self.assertEqual(payload['type'], 'chat_ring_timeout')
        self.assertEqual(payload['ring_id'], 'ring_70')
        self.assertEqual(payload['chat_id'], 'order_40_driver_customer')
        self.assertEqual(payload['status'], 'timeout')
        self.assertEqual(payload['status_display'], 'انتهت المهلة')
        self.assertTrue(payload['is_terminal'])
        self.assertFalse(payload['is_active'])
        self.assertTrue(payload['should_close'])
        self.assertEqual(payload['closed_reason'], 'timeout')
        self.assertEqual(payload['ui_action'], 'close_chat')

    def test_ring_status_payload_maps_answered_to_accepted(self):
        ring = self._make_ring('answered')

        payload = _ring_payload_for_status(ring, 'accepted', lang='ar')

        self.assertEqual(payload['type'], 'chat_ring_accepted')
        self.assertEqual(payload['status'], 'accepted')
        self.assertEqual(payload['status_display'], 'تم القبول')
        self.assertTrue(payload['should_close'])
        self.assertEqual(payload['closed_reason'], 'accepted')
        self.assertEqual(_ring_status_display('accepted', lang='en'), 'Accepted')
