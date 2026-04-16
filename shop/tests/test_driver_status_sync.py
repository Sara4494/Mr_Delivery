from types import SimpleNamespace

from unittest.mock import patch
from datetime import datetime, timezone

from django.test import SimpleTestCase

from shop.driver_chat_service import _map_order_status_to_driver_chat_status
from shop.driver_realtime import (
    build_driver_order_payload,
    driver_can_receive_new_orders,
    get_driver_order_unavailable_reason,
    is_assigned_order,
    is_assigned_order_for_driver,
    is_available_order,
    is_available_order_for_driver,
    normalize_driver_status,
    sync_unavailable_order_for_driver,
    sync_driver_order_state,
    upsert_available_order_for_all,
)


class DriverStatusSyncTests(SimpleTestCase):
    def test_targeted_pending_acceptance_is_only_available_for_matching_driver(self):
        driver = SimpleNamespace(id=7)
        other_driver = SimpleNamespace(id=9)
        order = SimpleNamespace(status='confirmed', driver_id=7, driver_accepted_at=None)

        self.assertTrue(is_available_order(order))
        self.assertTrue(is_available_order_for_driver(driver, order))
        self.assertFalse(is_available_order_for_driver(other_driver, order))

    def test_preparing_maps_to_awaiting_driver_acceptance_in_chat(self):
        order = SimpleNamespace(status='preparing')
        self.assertEqual(
            _map_order_status_to_driver_chat_status(order),
            'awaiting_driver_acceptance',
        )

    def test_on_way_maps_to_driver_on_way_in_chat(self):
        order = SimpleNamespace(status='on_way')
        self.assertEqual(
            _map_order_status_to_driver_chat_status(order),
            'driver_on_way',
        )

    def test_shop_assigned_order_waits_for_driver_acceptance_in_realtime(self):
        order = SimpleNamespace(status='preparing', driver_id=7, driver_accepted_at=None)
        self.assertEqual(normalize_driver_status(order), 'pending_acceptance')
        self.assertTrue(is_available_order(order))
        self.assertFalse(is_assigned_order(order))

    def test_driver_accepted_on_way_order_is_in_delivery_in_realtime(self):
        driver = SimpleNamespace(id=7)
        other_driver = SimpleNamespace(id=9)
        order = SimpleNamespace(status='on_way', driver_id=7, driver_accepted_at='2026-04-14T19:05:00Z')
        self.assertEqual(normalize_driver_status(order), 'in_delivery')
        self.assertFalse(is_available_order(order))
        self.assertTrue(is_assigned_order(order))
        self.assertTrue(is_assigned_order_for_driver(driver, order))
        self.assertFalse(is_assigned_order_for_driver(other_driver, order))

    def test_payload_exposes_assignment_fields_without_treating_assignment_as_acceptance(self):
        order = SimpleNamespace(
            id=123,
            order_number='A123',
            status='confirmed',
            driver_id=7,
            driver_accepted_at=None,
            driver_assigned_at=datetime(2026, 4, 14, 18, 55, tzinfo=timezone.utc),
            created_at=datetime(2026, 4, 14, 18, 50, tzinfo=timezone.utc),
            updated_at=datetime(2026, 4, 14, 18, 55, tzinfo=timezone.utc),
            items=[],
            total_amount=150,
            delivery_fee=20,
            payment_method='cash',
            customer=None,
            shop_owner=None,
        )

        payload = build_driver_order_payload(order)

        self.assertEqual(payload['driver_status'], 'pending_acceptance')
        self.assertEqual(payload['assigned_driver_id'], 7)
        self.assertIsNone(payload['accepted_at'])
        self.assertFalse(payload['chat']['can_open'])
        self.assertFalse(payload['transfer']['can_transfer'])

    @patch('shop.driver_realtime.emit_available_order_upsert')
    @patch('shop.driver_realtime.get_shop_receiving_driver_ids')
    def test_available_upsert_targets_only_assigned_driver_before_accept(
        self,
        get_shop_receiving_driver_ids_mock,
        emit_available_order_upsert_mock,
    ):
        order = SimpleNamespace(
            id=123,
            order_number='A123',
            status='confirmed',
            driver_id=7,
            driver_accepted_at=None,
            driver_assigned_at=None,
            created_at=datetime(2026, 4, 14, 18, 50, tzinfo=timezone.utc),
            updated_at=datetime(2026, 4, 14, 18, 55, tzinfo=timezone.utc),
            items=[],
            total_amount=150,
            delivery_fee=20,
            payment_method='cash',
            customer=None,
            shop_owner=None,
            shop_owner_id=55,
        )

        upsert_available_order_for_all(order)

        get_shop_receiving_driver_ids_mock.assert_not_called()
        emit_available_order_upsert_mock.assert_called_once()
        self.assertEqual(emit_available_order_upsert_mock.call_args.args[0], 7)

    @patch('shop.driver_realtime.upsert_available_order_for_all')
    @patch('shop.driver_realtime.remove_available_order_for_all')
    @patch('shop.driver_realtime.get_shop_active_driver_ids', return_value=[7, 9, 11])
    @patch('shop.driver_realtime.emit_available_order_remove')
    @patch('shop.driver_realtime.emit_assigned_order_remove')
    def test_transfer_before_accept_removes_from_old_available_and_upserts_for_new_available(
        self,
        emit_assigned_order_remove_mock,
        emit_available_order_remove_mock,
        get_shop_active_driver_ids_mock,
        remove_available_order_for_all_mock,
        upsert_available_order_for_all_mock,
    ):
        order = SimpleNamespace(id=123, status='confirmed', driver_id=9, driver_accepted_at=None, shop_owner_id=55)

        sync_driver_order_state(
            order,
            previous_status='confirmed',
            previous_driver_id=7,
            previous_driver_accepted_at=None,
        )

        emit_assigned_order_remove_mock.assert_not_called()
        emit_available_order_remove_mock.assert_called_once_with(7, 123, 'removed_from_driver')
        get_shop_active_driver_ids_mock.assert_called_once_with(55)
        remove_available_order_for_all_mock.assert_called_once_with(order, 'reserved_for_other_driver', driver_ids=[11])
        upsert_available_order_for_all_mock.assert_called_once()

    @patch('shop.driver_realtime.upsert_available_order_for_all')
    @patch('shop.driver_realtime.remove_available_order_for_all')
    @patch('shop.driver_realtime.get_shop_active_driver_ids', return_value=[7, 9, 11])
    @patch('shop.driver_realtime.emit_available_order_remove')
    @patch('shop.driver_realtime.emit_assigned_order_remove')
    def test_transfer_after_accept_removes_from_old_assigned_and_upserts_for_new_available(
        self,
        emit_assigned_order_remove_mock,
        emit_available_order_remove_mock,
        get_shop_active_driver_ids_mock,
        remove_available_order_for_all_mock,
        upsert_available_order_for_all_mock,
    ):
        order = SimpleNamespace(id=123, status='confirmed', driver_id=9, driver_accepted_at=None, shop_owner_id=55)

        sync_driver_order_state(
            order,
            previous_status='confirmed',
            previous_driver_id=7,
            previous_driver_accepted_at=datetime(2026, 4, 14, 19, 5, tzinfo=timezone.utc),
        )

        emit_available_order_remove_mock.assert_not_called()
        emit_assigned_order_remove_mock.assert_called_once_with(7, 123, 'removed_from_driver')
        get_shop_active_driver_ids_mock.assert_called_once_with(55)
        remove_available_order_for_all_mock.assert_called_once_with(order, 'reserved_for_other_driver', driver_ids=[7, 11])
        upsert_available_order_for_all_mock.assert_called_once()

    def test_unavailable_reason_is_cancelled_for_cancelled_order(self):
        driver = SimpleNamespace(id=7)
        order = SimpleNamespace(status='cancelled', driver_id=7, driver_accepted_at=None)
        self.assertEqual(get_driver_order_unavailable_reason(driver, order), 'cancelled')

    def test_unavailable_reason_is_accepted_by_other_driver_when_other_driver_already_accepted(self):
        driver = SimpleNamespace(id=7)
        order = SimpleNamespace(status='confirmed', driver_id=9, driver_accepted_at=datetime(2026, 4, 14, 19, 5, tzinfo=timezone.utc))
        self.assertEqual(get_driver_order_unavailable_reason(driver, order), 'accepted_by_other_driver')

    def test_unavailable_reason_is_transferred_to_other_driver_when_target_not_accepted_yet(self):
        driver = SimpleNamespace(id=7)
        order = SimpleNamespace(status='confirmed', driver_id=9, driver_accepted_at=None)
        self.assertEqual(get_driver_order_unavailable_reason(driver, order), 'transferred_to_other_driver')

    @patch('shop.driver_realtime.emit_available_order_remove')
    @patch('shop.driver_realtime.emit_assigned_order_remove')
    def test_sync_unavailable_order_for_driver_removes_from_both_lists(self, emit_assigned_order_remove_mock, emit_available_order_remove_mock):
        driver = SimpleNamespace(id=7)
        order = SimpleNamespace(status='confirmed', driver_id=9, driver_accepted_at=None)

        reason = sync_unavailable_order_for_driver(driver, 123, order=order)

        self.assertEqual(reason, 'transferred_to_other_driver')
        emit_available_order_remove_mock.assert_called_once_with(7, 123, 'transferred_to_other_driver')
        emit_assigned_order_remove_mock.assert_called_once_with(7, 123, 'transferred_to_other_driver')

    def test_unassigned_new_order_stays_waiting_reply_in_chat(self):
        order = SimpleNamespace(status='new')
        self.assertEqual(_map_order_status_to_driver_chat_status(order), 'waiting_reply')

    def test_available_driver_without_active_orders_can_receive_new_orders(self):
        driver = SimpleNamespace(status='available', active_orders_count=0)
        self.assertTrue(driver_can_receive_new_orders(driver))

    def test_busy_driver_cannot_receive_new_orders(self):
        driver = SimpleNamespace(status='busy', active_orders_count=0)
        self.assertFalse(driver_can_receive_new_orders(driver))

    def test_available_driver_with_active_orders_cannot_receive_new_orders(self):
        driver = SimpleNamespace(status='available', active_orders_count=2)
        self.assertFalse(driver_can_receive_new_orders(driver))
