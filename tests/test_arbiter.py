import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import risk_arbiter
from risk_arbiter import RiskArbiter


class Rig:
    """가짜 센서 + 출력 기록. 각 센서는 속성으로 값을 바꾸거나 예외를 내게 할 수 있다."""

    def __init__(self):
        self.ultrasonic = ("SAFE", "좌측", None)
        self.radar = None
        self.imu = {}
        self.broken = set()
        self.out = {"state": [], "offline": 0, "buzzer": [], "led": [], "alarm": 0, "sample": [], "event": []}
        self.logs = []
        self.arb = RiskArbiter(
            speed_getter=lambda: 15.0,
            stopping_distance_fn=lambda s: 5.4,
            risk_fn=self.risk_fn,
            ultrasonic_fn=lambda: self._src("ultrasonic", self.ultrasonic),
            radar_fn=lambda: self._src("radar", self.radar),
            imu_fn=lambda: self._src("imu", self.imu),
            on_state=lambda t: self._out("state", self.out["state"].append, t),
            on_camera_offline=lambda: self._bump("offline"),
            on_buzzer=lambda r: self._out("buzzer", self.out["buzzer"].append, r),
            on_led=lambda b: self._out("led", self.out["led"].append, b),
            on_impact_alarm=lambda: self._bump("alarm"),
            on_sample=lambda r: self.out["sample"].append(r),
            on_event=lambda *a: self.out["event"].append(a),
            log=self.logs.append,
        )

    @staticmethod
    def risk_fn(distance, ttc, in_zone, stopping):
        if not in_zone:
            return "SAFE"
        if distance <= 5.0 or (ttc is not None and ttc <= 1.5):
            return "DANGER"
        if ttc is not None and ttc <= 3.0:
            return "WARNING"
        return "SAFE"

    def _src(self, name, value):
        if name in self.broken:
            raise RuntimeError(f"{name} 고장")
        return value

    def _out(self, name, fn, value):
        if name in self.broken:
            raise RuntimeError(f"출력 {name} 고장")
        fn(value)

    def _bump(self, key):
        self.out[key] += 1


def cam(risk="WARNING"):
    return {"risk": risk, "track_id": 1, "class_name": "사람", "distance": 6.0, "ttc": 2.0, "in_collision_zone": True}


class ArbiterTests(unittest.TestCase):
    def setUp(self):
        self.rig = Rig()

    def test_camera_alone(self):
        self.rig.arb.publish_camera(cam("WARNING"))
        r = self.rig.arb.tick()
        self.assertEqual(r["risk"], "WARNING")
        self.assertEqual(self.rig.out["buzzer"][-1], "WARNING")
        self.assertEqual(self.rig.out["led"][-1], False)
        self.assertEqual(self.rig.out["event"][-1][0], "warning")

    def test_camera_dead_radar_alone_still_alerts(self):
        # 카메라 값이 한 번도 안 오고(스레드 사망) 레이더만 살아있는 상황
        self.rig.arb._created_at -= 100  # 부팅 유예 지난 뒤
        self.rig.radar = {"distance_m": 4.0, "ttc_sec": 1.0, "in_path": True}
        r = self.rig.arb.tick()
        self.assertEqual(r["risk"], "DANGER")
        self.assertEqual(r["target"]["class_name"], "레이더_전방")
        self.assertEqual(self.rig.out["buzzer"][-1], "DANGER")
        self.assertEqual(self.rig.out["led"][-1], True)
        self.assertTrue(self.rig.out["event"])

    def test_camera_hang_goes_stale_and_does_not_freeze_outputs(self):
        self.rig.arb.publish_camera(cam("DANGER"))
        self.assertEqual(self.rig.arb.tick()["risk"], "DANGER")
        # 카메라가 멈춤: 더 이상 publish 안 함, 시간 경과
        self.rig.arb._camera_at -= risk_arbiter.CAMERA_STALE_SEC + 1
        r = self.rig.arb.tick()
        self.assertEqual(r["risk"], "SAFE")             # 오래된 DANGER가 굳지 않음
        self.assertEqual(self.rig.out["buzzer"][-1], "SAFE")
        self.assertTrue(r["camera_offline"])
        self.assertEqual(self.rig.out["offline"], 1)    # "카메라 끊김" 안내는 나감

    def test_camera_offline_notice_not_shown_during_startup_grace(self):
        r = self.rig.arb.tick()
        self.assertFalse(r["camera_offline"])
        self.assertEqual(self.rig.out["offline"], 0)

    def test_offline_notice_does_not_hide_other_sensor_risk(self):
        self.rig.arb._created_at -= 100
        self.rig.ultrasonic = ("DANGER", "우측", 50.0)
        r = self.rig.arb.tick()
        self.assertEqual(r["risk"], "DANGER")
        self.assertEqual(self.rig.out["offline"], 0)    # 실제 위험이 있으면 안내보다 위험을 보냄

    def test_each_sensor_exception_is_isolated(self):
        self.rig.arb.publish_camera(cam("CAUTION"))
        for name in ("ultrasonic", "radar", "imu"):
            self.rig.broken.add(name)
        r = self.rig.arb.tick()                          # 예외 없이 끝나야 함
        self.assertEqual(r["risk"], "CAUTION")
        self.assertEqual(self.rig.out["buzzer"][-1], "CAUTION")
        self.assertTrue(any("초음파" in m for m in self.rig.logs))

    def test_output_failure_does_not_block_other_outputs(self):
        self.rig.broken.add("buzzer")
        self.rig.arb.publish_camera(cam("DANGER"))
        self.rig.arb.tick()
        self.assertEqual(self.rig.out["led"][-1], True)  # 부저가 고장나도 LED는 나감
        self.assertTrue(self.rig.out["event"])

    def test_imu_impact_alarm_fires_once_and_forces_danger(self):
        self.rig.arb.publish_camera(None)
        self.rig.imu = {"impact": True}
        for _ in range(5):
            r = self.rig.arb.tick()
        self.assertEqual(r["risk"], "DANGER")
        self.assertEqual(r["target"]["class_name"], "IMU_충돌")
        self.assertEqual(self.rig.out["alarm"], 1)
        self.rig.imu = {"impact": False}
        self.rig.arb.tick()
        self.rig.imu = {"impact": True}
        self.rig.arb.tick()
        self.assertEqual(self.rig.out["alarm"], 2)

    def test_imu_rollover_forces_danger_over_everything(self):
        self.rig.arb.publish_camera(cam("CAUTION"))
        self.rig.imu = {"rollover": True}
        r = self.rig.arb.tick()
        self.assertEqual(r["target"]["class_name"], "IMU_전복")

    def test_priority_matches_old_behavior_camera_then_ultrasonic_then_radar(self):
        self.rig.arb.publish_camera(cam("WARNING"))
        self.rig.ultrasonic = ("CAUTION", "좌측", 120.0)   # 더 낮음 → 카메라 유지
        self.assertEqual(self.rig.arb.tick()["target"]["class_name"], "사람")
        self.rig.ultrasonic = ("DANGER", "좌측", 60.0)     # 더 높음 → 초음파로 교체
        self.assertEqual(self.rig.arb.tick()["target"]["class_name"], "초음파_좌측")

    def test_log_is_rate_limited(self):
        self.rig.broken.add("radar")
        for _ in range(50):
            self.rig.arb.tick()
        self.assertLessEqual(sum("레이더" in m for m in self.rig.logs), 1)

    def test_run_loop_survives_total_tick_failure(self):
        import threading
        import time
        self.rig.arb.tick = lambda: (_ for _ in ()).throw(RuntimeError("tick 자체 실패"))
        saved = risk_arbiter.TICK_SEC
        risk_arbiter.TICK_SEC = 0.001
        try:
            t = threading.Thread(target=self.rig.arb.run, daemon=True)
            t.start()
            time.sleep(0.1)
            self.assertTrue(t.is_alive())  # tick이 계속 실패해도 루프는 살아있음
        finally:
            risk_arbiter.TICK_SEC = saved


if __name__ == "__main__":
    unittest.main()
