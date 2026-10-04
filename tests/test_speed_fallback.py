import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import ble_peripheral as bp


class SpeedFallbackTests(unittest.TestCase):
    def test_never_received_is_zero(self):
        self.assertEqual(bp.resolve_speed_kmh(0.0, 0.0, 100.0, True), 0.0)

    def test_fresh_value_used(self):
        self.assertEqual(bp.resolve_speed_kmh(22.0, 98.0, 100.0, True), 22.0)

    def test_ble_drop_during_ride_holds_last_speed(self):
        self.assertEqual(bp.resolve_speed_kmh(22.0, 100.0, 130.0, True), 22.0)

    def test_long_outage_during_ride_falls_back_to_default_not_zero(self):
        self.assertEqual(bp.resolve_speed_kmh(22.0, 100.0, 200.0, True), bp.SPEED_DEFAULT_KMH)

    def test_not_riding_goes_to_zero_after_fresh_window(self):
        self.assertEqual(bp.resolve_speed_kmh(22.0, 100.0, 110.0, False), 0.0)


if __name__ == "__main__":
    unittest.main()
