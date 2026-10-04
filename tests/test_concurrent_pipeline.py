"""카메라 스레드 + 레이더 읽기 스레드 + 중재 스레드를 실제 속도로 동시에 돌려서 서로 방해 없이 합쳐지는지 본다.
(가짜 센서 값 사용 — Mac 시험 전용. 파이의 CPU 부하/실제 지연은 파이에서 확인해야 함)"""
import os
import sys
import threading
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import radar_parser
import radar_reader
import radar_sensor
import radar_tracker
from radar_frames import build_frame
from risk_arbiter import RiskArbiter
from test_arbiter import Rig


class PacedRadarPort:
    """레이더가 20Hz로 프레임을 보내는 것처럼, read() 때마다 50ms 간격으로 프레임 하나를 돌려준다."""

    def __init__(self, stop):
        self.n, self.stop = 0, stop

    def read(self, size):
        time.sleep(0.05)
        self.n += 1
        y = max(1.0, 12.0 - 0.2 * self.n)                 # 초속 4m로 다가오는 대상 (20Hz → 프레임당 0.2m)
        return build_frame([(0.1, y, 0.0, -4.0)], frame_number=self.n)


class ConcurrentPipelineTests(unittest.TestCase):
    def test_camera_and_radar_run_at_the_same_time_and_get_fused(self):
        stop = threading.Event()
        radar_sensor.clear_target()
        radar_tracker._extractor = radar_tracker.ForwardTargetExtractor()
        radar_reader._stats.update({"frames_ok": 0, "frames_bad": 0, "last_frame_at": 0.0, "last_num_points": 0})
        radar_reader.on_frame = radar_tracker.handle_frame

        outputs, logs, counts = [], [], {"camera": 0, "ticks": 0}
        rig = Rig()
        arbiter = RiskArbiter(
            speed_getter=lambda: 15.0, stopping_distance_fn=lambda s: 5.4, risk_fn=Rig.risk_fn,
            ultrasonic_fn=lambda: ("SAFE", "좌측", None), radar_fn=radar_sensor.get_forward_target,
            imu_fn=lambda: {}, on_state=outputs.append, on_camera_offline=lambda: None,
            on_buzzer=lambda r: None, on_led=lambda b: None, on_impact_alarm=lambda: None,
            on_sample=lambda r: None, on_event=lambda *a: None, log=logs.append,
        )
        arbiter._created_at -= 100

        def camera_thread():       # 약 15fps, 박스 기반 거리는 실제보다 0.8m 가깝게(오차) 나옴
            n = 0
            while not stop.is_set():
                n += 1
                time.sleep(1 / 15)
                radar = radar_sensor.get_forward_target()
                dist = (radar["distance_m"] - 0.8) if radar else max(1.0, 12.0 - 0.27 * n)
                target = {"risk": "DANGER", "track_id": 1, "class_name": "사람", "distance": dist,
                          "ttc": None, "in_collision_zone": True}
                arbiter.publish_camera(target, [target])
                counts["camera"] += 1

        def radar_thread():
            port = PacedRadarPort(stop)
            radar_reader.read_frames(port, radar_parser.FrameExtractor(), radar_reader.handle_frame,
                                     should_stop=stop.is_set)

        def arbiter_thread():
            while not stop.is_set():
                arbiter.tick()
                counts["ticks"] += 1
                time.sleep(0.05)

        threads = [threading.Thread(target=f, daemon=True) for f in (camera_thread, radar_thread, arbiter_thread)]
        for t in threads:
            t.start()
        time.sleep(1.8)
        stop.set()
        for t in threads:
            t.join(timeout=2)
        radar_reader.on_frame = None
        radar_sensor.clear_target()

        stats = radar_reader.get_stats()
        sources = {o.get("source") for o in outputs if o}
        self.assertEqual(logs, [])                              # 어느 쪽에서도 오류 없음
        self.assertGreater(counts["camera"], 15)                # 카메라가 계속 값을 올림
        self.assertGreater(stats["frames_ok"], 20)              # 레이더도 동시에 계속 프레임 처리
        self.assertGreater(counts["ticks"], 25)                 # 중재자도 계속 판단
        self.assertIn("camera+radar", sources)                  # 둘이 합쳐진 판단이 실제로 나옴
        fused = [o for o in outputs if o and o.get("source") == "camera+radar"]
        self.assertTrue(all(o["class_name"] == "사람" for o in fused))      # 이름은 카메라
        self.assertTrue(all(o["distance"] > 1.0 for o in fused))           # 거리는 레이더 값


if __name__ == "__main__":
    unittest.main()
