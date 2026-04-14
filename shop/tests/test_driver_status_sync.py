from types import SimpleNamespace

from django.test import SimpleTestCase

from shop.driver_chat_service import _map_order_status_to_driver_chat_status
from shop.driver_realtime import driver_can_receive_new_orders, normalize_driver_status


class DriverStatusSyncTests(SimpleTestCase):
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

    def test_assigned_preparing_order_stays_assigned_in_driver_realtime(self):
        order = SimpleNamespace(status='preparing', driver_id=7)
        self.assertEqual(normalize_driver_status(order), 'assigned')

    def test_assigned_on_way_order_is_in_delivery_in_driver_realtime(self):
        order = SimpleNamespace(status='on_way', driver_id=7)
        self.assertEqual(normalize_driver_status(order), 'in_delivery')

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
