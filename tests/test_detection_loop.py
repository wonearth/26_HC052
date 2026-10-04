"""카메라 감지 루프(detection_loop)를 가짜 카메라 + 가짜 YOLO 출력으로 실제로 돌려본다.
화면(영상 스트림)이 나오려면 이 루프가 예외 없이 돌며 JPEG을 만들어야 한다."""
import os
import sys
import threading
import time
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

try:
    import cv2
    import numpy as np
    import scipy  # noqa: F401
    HAVE_LIBS = True
except Exception:
    HAVE_LIBS = False


def _install_hw_stubs():
    for name in ("picamera2", "onnxruntime", "gpiozero", "serial", "bluezero"):
        if name not in sys.modules:
            try:
                __import__(name)
            except Exception:
                sys.modules[name] = mock.MagicMock()


class StopLoop(BaseException):
    """시험이 끝났을 때 감지 루프를 확실히 멈추기 위한 신호. 루프는 Exception만 잡으므로 BaseException으로 빠져나간다."""


class FakeCamera:
    """640x480 RGB 프레임을 계속 돌려주다가, stop이 켜지면 루프를 끝낸다."""

    def __init__(self, stop):
        self.stop = stop

    def capture_array(self, name):
        if self.stop.is_set():
            raise StopLoop()
        time.sleep(0.005)
        return np.full((480, 640, 3), 90, dtype=np.uint8)


class FakeYolo:
    """사람 한 명(박스 높이 300px)이 화면 가운데 정면에 있다고 답한다. YOLOv8 출력 형식: (1, 84, N)."""

    def __init__(self, with_person=True):
        self.with_person = with_person

    def run(self, outputs, feed):
        preds = np.zeros((84, 2), dtype=np.float32)
        if self.with_person:
            preds[:4, 0] = (160.0, 160.0, 60.0, 150.0)   # 320x320 레터박스 좌표: cx, cy, w, h
            preds[4 + 0, 0] = 0.9                         # class 0 = 사람
        return [preds[np.newaxis, :, :]]


class StubArbiter:
    def __init__(self):
        self.published = []

    def publish_camera(self, target, zone_targets=None):
        self.published.append((target, list(zone_targets or [])))


@unittest.skipUnless(HAVE_LIBS, "numpy/cv2/scipy 필요")
class DetectionLoopTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        _install_hw_stubs()
        import app
        cls.app = app

    def run_loop(self, yolo, seconds=1.2, viewers=True):
        a = self.app
        a._latest_jpeg = None
        a._arbiter = StubArbiter()
        a._speed_getter = lambda: 15.0
        error, stop = {}, threading.Event()

        def target():
            try:
                a.detection_loop(FakeCamera(stop), yolo, "images", a.SimpleByteTracker())
            except StopLoop:
                pass                      # 시험이 끝나서 정상적으로 멈춘 것
            except BaseException as e:   # 감시기가 없으니 여기서 직접 잡아 시험에 보고
                error["e"] = e

        if viewers:
            a._inc_viewers()
        t = threading.Thread(target=target, daemon=True)
        t.start()
        time.sleep(seconds)
        alive_while_running = t.is_alive()
        jpeg = a._latest_jpeg
        # 스레드를 확실히 끝내고 나서 다음 시험으로 — 이전 시험의 루프가 계속 돌며 다음 시험에 끼어드는 것을 막음
        stop.set()
        t.join(timeout=3)
        if viewers:
            a._dec_viewers()
        self.assertFalse(t.is_alive(), "감지 루프가 멈추지 않음")
        return error, a._arbiter, jpeg, alive_while_running

    def test_loop_runs_without_exception_and_produces_a_video_frame(self):
        error, arbiter, jpeg, thread = self.run_loop(FakeYolo(with_person=True))
        self.assertNotIn("e", error, f"감지 루프가 예외로 죽음: {error.get('e')!r}")
        self.assertTrue(thread)   # 시험하는 동안 루프가 살아 있었음
        self.assertIsNotNone(jpeg, "영상 스트림용 JPEG이 만들어지지 않음 → 화면이 안 나옴")
        image = cv2.imdecode(np.frombuffer(jpeg, np.uint8), cv2.IMREAD_COLOR)
        self.assertEqual(image.shape[:2], (480, 640))

    def test_person_in_front_is_reported_to_the_arbiter_as_a_zone_target(self):
        error, arbiter, _, _ = self.run_loop(FakeYolo(with_person=True))
        self.assertNotIn("e", error, repr(error.get("e")))
        reported = [t for t, zone in arbiter.published if t is not None]
        self.assertTrue(reported, "카메라가 사람을 한 번도 보고하지 않음")
        t = reported[-1]
        self.assertEqual(t["class_name"], "사람")
        self.assertTrue(t["in_collision_zone"])
        self.assertAlmostEqual(t["distance"], 1.7 * 524.0 / 300.0, delta=0.3)
        self.assertTrue(any(zone for _, zone in arbiter.published))

    def test_empty_scene_publishes_none_and_loop_keeps_going(self):
        error, arbiter, jpeg, thread = self.run_loop(FakeYolo(with_person=False))
        self.assertNotIn("e", error, repr(error.get("e")))
        self.assertTrue(arbiter.published)
        self.assertTrue(all(t is None for t, _ in arbiter.published))
        self.assertIsNotNone(jpeg)

    def test_no_viewers_means_no_encoding_but_still_publishes(self):
        error, arbiter, jpeg, _ = self.run_loop(FakeYolo(with_person=True), viewers=False)
        self.assertNotIn("e", error, repr(error.get("e")))
        self.assertIsNone(jpeg)
        self.assertTrue(arbiter.published)


if __name__ == "__main__":
    unittest.main()
