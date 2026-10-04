"""대시보드 레이더 화면용 데이터(상태별 snapshot, /api/radar_state)가 맞게 나오는지 확인."""
import math
import os
import sys
import time
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import radar_reader as rr
import radar_sensor


def pt(x, y, v=-3.0):
    return {"x": x, "y": y, "z": 0.0, "v": v, "range_m": math.hypot(x, y), "azimuth_deg": 0.0, "snr_db": None}


class SnapshotTests(unittest.TestCase):
    def setUp(self):
        rr._stats.update({"frames_ok": 0, "frames_bad": 0, "last_frame_at": 0.0, "last_num_points": 0})
        rr._latest_points[:] = []
        rr.on_frame = None
        radar_sensor.clear_target()
        self._enabled = rr.RADAR_ENABLED

    def tearDown(self):
        rr.RADAR_ENABLED = self._enabled
        radar_sensor.clear_target()

    def test_disabled_radar_reports_off_even_if_old_frames_exist(self):
        rr.RADAR_ENABLED = False
        rr.handle_frame({"points": [pt(0, 5)], "frame_number": 1})
        snap = rr.get_dashboard_snapshot()
        self.assertEqual((snap["state"], snap["enabled"], snap["points"], snap["target"]), ("off", False, [], None))

    def test_enabled_but_no_frames_yet_is_no_signal(self):
        rr.RADAR_ENABLED = True
        snap = rr.get_dashboard_snapshot()
        self.assertEqual((snap["state"], snap["age_sec"], snap["points"]), ("no_signal", None, []))

    def test_recent_frame_is_ok_with_points_and_target(self):
        rr.RADAR_ENABLED = True
        rr.handle_frame({"points": [pt(0.2, 8.0), pt(3.0, 6.0)], "frame_number": 1})
        radar_sensor.update_target(8.0, 3.0, 0.2)
        snap = rr.get_dashboard_snapshot()
        self.assertEqual(snap["state"], "ok")
        self.assertEqual(snap["num_points"], 2)
        self.assertEqual(len(snap["points"]), 2)
        self.assertEqual(snap["points"][0][:2], [3.0, 6.0])               # 가까운 점이 먼저
        self.assertAlmostEqual(snap["target"]["distance_m"], 8.0)
        self.assertAlmostEqual(snap["target"]["ttc_sec"], 8.0 / 3.0)

    def test_old_frames_become_no_signal_and_hide_stale_points_and_target(self):
        rr.RADAR_ENABLED = True
        rr.handle_frame({"points": [pt(0, 5)], "frame_number": 1})
        radar_sensor.update_target(5.0, 3.0, 0.0)
        later = time.monotonic() + rr.RADAR_STALE_SEC + 1.0
        snap = rr.get_dashboard_snapshot(now=later)
        self.assertEqual((snap["state"], snap["points"], snap["target"], snap["num_points"]), ("no_signal", [], None, 0))
        self.assertGreater(snap["age_sec"], rr.RADAR_STALE_SEC)
        self.assertEqual(snap["frames_ok"], 1)                           # "몇 프레임 받고 끊겼는지"는 남김

    def test_points_are_capped_nearest_first(self):
        rr.RADAR_ENABLED = True
        many = [pt(0.0, 1.0 + i * 0.2) for i in range(rr.MAX_DASHBOARD_POINTS + 50)][::-1]   # 먼 점부터 들어옴
        rr.handle_frame({"points": many, "frame_number": 1})
        snap = rr.get_dashboard_snapshot()
        self.assertEqual(len(snap["points"]), rr.MAX_DASHBOARD_POINTS)
        self.assertEqual(snap["points"][0][1], 1.0)
        self.assertEqual(snap["num_points"], len(many))                  # 실제 점 개수는 그대로 보고


class DiagnosticsTests(unittest.TestCase):
    """"신호 없음"일 때 왜 그런지(바이트가 아예 안 옴 / 와도 해석 안 됨 / 설정 파일 없음 / 스레드 오류) 구분할 재료."""

    def setUp(self):
        rr._stats.update({"frames_ok": 0, "frames_bad": 0, "last_frame_at": 0.0, "last_num_points": 0, "bytes_in": 0, "cfg": "none"})
        rr._latest_points[:] = []
        self._enabled = rr.RADAR_ENABLED
        rr.RADAR_ENABLED = True

    def tearDown(self):
        rr.RADAR_ENABLED = self._enabled

    def test_bytes_are_counted_even_when_nothing_parses(self):
        from test_radar_reader import FakeData
        import radar_parser
        ticks = {"n": 0}

        def clock():
            ticks["n"] += 1.0
            return ticks["n"]

        with self.assertRaises(TimeoutError):
            rr.read_frames(FakeData([b"\x55" * 100, b"\x66" * 50]), radar_parser.FrameExtractor(),
                           lambda parsed: None, no_data_timeout=6.0, clock=clock)
        snap = rr.get_dashboard_snapshot()
        self.assertEqual((snap["bytes_in"], snap["frames_ok"]), (150, 0))     # 데이터는 오는데 해석이 안 되는 경우

    def test_snapshot_carries_cfg_result_and_worker_error(self):
        rr._stats["cfg"] = "missing"
        health = {"radar": {"state": "restarting", "restarts": 3, "last_error": "SerialException: could not open port"}}
        with mock.patch("supervisor.get_health", return_value=health):
            snap = rr.get_dashboard_snapshot()
        self.assertEqual((snap["cfg"], snap["bytes_in"]), ("missing", 0))
        self.assertIn("could not open port", snap["worker"]["last_error"])
        self.assertEqual(snap["worker"]["restarts"], 3)

    def test_worker_info_is_hidden_when_radar_is_disabled(self):
        rr.RADAR_ENABLED = False
        self.assertIsNone(rr.get_dashboard_snapshot()["worker"])


def _import_app():
    for name in ("picamera2", "onnxruntime", "gpiozero", "serial", "bluezero"):
        if name not in sys.modules:
            try:
                __import__(name)
            except Exception:
                sys.modules[name] = mock.MagicMock()
    import app
    return app


class RadarApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = _import_app()
        cls.client = cls.app.app.test_client()

    def setUp(self):
        rr._stats.update({"frames_ok": 0, "frames_bad": 0, "last_frame_at": 0.0, "last_num_points": 0})
        rr._latest_points[:] = []
        radar_sensor.clear_target()
        self._enabled = rr.RADAR_ENABLED
        self.app._speed_getter = lambda: 15.0

    def tearDown(self):
        rr.RADAR_ENABLED = self._enabled
        radar_sensor.clear_target()

    def test_api_when_radar_is_off(self):
        rr.RADAR_ENABLED = False
        data = self.client.get("/api/radar_state").get_json()
        self.assertEqual(data["state"], "off")
        self.assertIsNone(data["target"])
        self.assertEqual(data["max_range_m"], 25.0)
        self.assertEqual(data["corridor_half_width_m"], 1.0)

    def test_api_target_gets_its_own_risk_level(self):
        rr.RADAR_ENABLED = True
        rr.handle_frame({"points": [pt(0.1, 4.0)], "frame_number": 1})
        radar_sensor.update_target(4.0, 4.0, 0.1)       # 4m, 초속 4m로 접근 → TTC 1.0초
        data = self.client.get("/api/radar_state").get_json()
        self.assertEqual(data["state"], "ok")
        self.assertEqual(data["target"]["risk"], "danger")
        self.assertAlmostEqual(data["target"]["ttc_sec"], 1.0)
        radar_sensor.update_target(30.0, 1.0, 0.0)      # 멀고 천천히 → 안전
        self.assertEqual(self.client.get("/api/radar_state").get_json()["target"]["risk"], "safe")

    def test_dashboard_page_has_the_radar_panel_and_polls_the_radar_api(self):
        page = self.client.get("/").get_data(as_text=True)
        for element_id in ("radar-canvas", "radar-pill", "radar-card", "r-dist", "r-speed", "r-ttc", "r-meta"):
            self.assertIn(f'id="{element_id}"', page)
        self.assertIn("/api/radar_state", page)
        self.assertIn("/api/dashboard_state", page)


if __name__ == "__main__":
    unittest.main()
