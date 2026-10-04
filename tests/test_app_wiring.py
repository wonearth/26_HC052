"""app.py의 실제 함수들을 중재자에 연결해서 스모크 테스트한다.
Mac에는 picamera2/gpiozero 등이 없으므로 하드웨어 모듈만 가짜로 대체한다 (app.py 로직은 그대로)."""
import os
import sys
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


def _install_stubs():
    for name in ("picamera2", "onnxruntime", "gpiozero", "serial", "cv2", "flask",
                 "scipy", "scipy.optimize", "numpy", "bluezero"):
        if name not in sys.modules:
            try:
                __import__(name)
            except Exception:
                sys.modules[name] = mock.MagicMock()


class FakeBuzzer:
    def __init__(self):
        self.calls = []

    def beep(self, **kw):
        self.calls.append(("beep", kw.get("on_time"), kw.get("off_time"), kw.get("n")))

    def off(self):
        self.calls.append(("off",))


class FakeLed:
    def __init__(self):
        self.state = False

    def on(self):
        self.state = True

    def off(self):
        self.state = False


class AppWiringTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        _install_stubs()
        import app
        cls.app = app

    def setUp(self):
        a = self.app
        a.buzzer, a.led = FakeBuzzer(), FakeLed()
        a._buzzer_pattern, a._led_active, a._impact_alarm_until = None, False, 0.0
        self.recorded, self.sampled = [], []
        a._event_recorder = lambda *args: self.recorded.append(args)
        a._risk_sampler = lambda r: self.sampled.append(r)
        a._speed_getter = lambda: 15.0
        import radar_sensor
        radar_sensor.clear_target()
        self.radar = radar_sensor
        self.imu = {}
        a.imu_sensor.get_imu_state = lambda: self.imu
        a.ultrasonic_sensor.get_worst_side = lambda: ("SAFE", "좌측", None)
        self.arb = a.risk_arbiter.RiskArbiter(
            speed_getter=a._get_speed,
            stopping_distance_fn=a.calculate_stopping_distance,
            risk_fn=a.get_final_risk,
            ultrasonic_fn=lambda: a.ultrasonic_sensor.get_worst_side(),
            radar_fn=a.radar_sensor.get_forward_target,
            imu_fn=lambda: a.imu_sensor.get_imu_state(),
            on_state=a.update_live_state,
            on_camera_offline=a.mark_camera_offline,
            on_buzzer=a.set_buzzer,
            on_led=a.set_led,
            on_impact_alarm=a.sound_impact_alarm,
            on_sample=a._sample_risk,
            on_event=a._record_event,
            log=lambda m: self.fail(f"중재자가 오류를 삼킴(시그니처 불일치 가능): {m}"),
        )

    def test_radar_danger_reaches_buzzer_led_state_and_record(self):
        self.radar.update_target(4.0, 4.0, 0.2)
        self.arb._created_at -= 100
        r = self.arb.tick()
        a = self.app
        self.assertEqual(r["risk"], "DANGER")
        self.assertIn(("beep", 0.08, 0.08, None), a.buzzer.calls)   # 위험 = 빠른 패턴
        self.assertTrue(a.led.state)
        live = a.get_live_state()
        self.assertEqual(live["risk"], "danger")
        self.assertIn("레이더 감지", live["message"])
        self.assertEqual(self.recorded[-1][2], "레이더_전방")
        self.assertEqual(self.sampled[-1], "danger")

    def test_camera_offline_sets_live_notice_without_buzzer(self):
        self.arb._created_at -= 100
        self.arb.tick()
        a = self.app
        live = a.get_live_state()
        self.assertEqual(live["title"], "카메라 연결 끊김")
        self.assertFalse(a.led.state)
        self.assertFalse(any(c[0] == "beep" for c in a.buzzer.calls))

    def test_imu_impact_sounds_one_second_alarm(self):
        self.imu = {"impact": True}
        self.arb.tick()
        self.assertIn(("beep", 1.0, 0.1, 1), self.app.buzzer.calls)

    def test_camera_target_flows_through_same_outputs(self):
        self.arb.publish_camera({"risk": "WARNING", "track_id": 3, "class_name": "사람",
                                 "distance": 6.0, "ttc": 2.0, "in_collision_zone": True})
        self.arb.tick()
        self.assertIn(("beep", 0.15, 0.6, None), self.app.buzzer.calls)  # 경고 = 느린 패턴
        self.assertEqual(self.recorded[-1][0:3], ("warning", 3, "사람"))


    def test_overlay_labels_are_ascii_and_cover_every_detected_class(self):
        # 영상 위 라벨은 OpenCV 4.x 기본 글꼴로 그려지므로 ASCII여야 한다 (한글이면 ???로 깨짐)
        a = self.app
        self.assertEqual(set(a.OVERLAY_LABELS), set(a.CLASS_INFO))
        for label in a.OVERLAY_LABELS.values():
            self.assertTrue(label.isascii(), label)

    def test_dashboard_shows_code_version_and_detected_target(self):
        a = self.app
        self.assertTrue(isinstance(a.APP_VERSION, str) and a.APP_VERSION)   # git 해시 또는 "unknown"
        for element_id in ("v-msg", "v-ver"):
            self.assertIn(f'id="{element_id}"', a.DASHBOARD_HTML)
        self.assertIn("data.message", a.DASHBOARD_HTML)
        self.assertIn("data.version", a.DASHBOARD_HTML)

    def test_describe_target_marks_radar_confirmation(self):
        a = self.app
        self.assertIn("레이더 확인", a.describe_target("사람", 6.0, 3.0, True, "camera+radar"))
        self.assertNotIn("레이더 확인", a.describe_target("사람", 6.0, 3.0, True))

    def test_fused_target_reaches_live_state_with_radar_confirmation(self):
        a = self.app
        self.radar.update_target(6.0, 2.0, 0.0)                    # 레이더: 6m, 초속 2m로 접근 → TTC 3.0초
        self.arb.publish_camera({"risk": "DANGER", "track_id": 4, "class_name": "사람",
                                 "distance": 5.0, "ttc": None, "in_collision_zone": True})
        self.arb.tick()
        live = a.get_live_state()
        self.assertEqual(live["risk"], "warning")
        self.assertIn("사람", live["message"])
        self.assertIn("레이더 확인", live["message"])
        self.assertIn(("beep", 0.15, 0.6, None), a.buzzer.calls)    # 경고 = 느린 패턴
        self.assertEqual(self.recorded[-1][:3], ("warning", 4, "사람"))

if __name__ == "__main__":
    unittest.main()
