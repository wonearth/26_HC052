import math
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import radar_parser
import radar_reader
import radar_sensor
import radar_tracker as rt
from radar_frames import build_frame


def pt(x, y, v, snr=None):
    return {"x": x, "y": y, "z": 0.0, "v": v, "range_m": math.hypot(x, y), "azimuth_deg": 0.0, "snr_db": snr}


def run(ex, frames):
    return [ex.process(f) for f in frames]


class ExtractorTests(unittest.TestCase):
    def setUp(self):
        self.ex = rt.ForwardTargetExtractor()

    def test_person_approaching_in_corridor_is_confirmed_after_n_frames(self):
        # 8m 앞에서 4m/s로 다가오는 사람 (다가오면 속도가 음수라고 가정)
        out = run(self.ex, [[pt(0.3, 8.0 - 0.4 * i, -4.0)] for i in range(6)])
        self.assertEqual([o is not None for o in out], [False, False, True, True, True, True])
        last = out[-1]
        self.assertAlmostEqual(last["closing_speed_mps"], 4.0, places=3)
        self.assertLess(last["distance_m"], 8.0)
        self.assertAlmostEqual(last["lateral_m"], 0.3, places=2)

    def test_parked_car_beside_the_path_is_never_a_target(self):
        out = run(self.ex, [[pt(3.0, 6.0, -4.0)] for _ in range(10)])
        self.assertTrue(all(o is None for o in out))

    def test_single_frame_ghost_is_ignored(self):
        frames = [[], [], [pt(-0.4, 15.0, -3.0)], [], [], []]
        self.assertTrue(all(o is None for o in run(self.ex, frames)))

    def test_nearest_object_in_corridor_wins(self):
        frames = [[pt(0.0, 18.0, -6.0), pt(0.2, 7.0, -4.0)] for _ in range(4)]
        out = run(self.ex, frames)[-1]
        self.assertAlmostEqual(out["distance_m"], math.hypot(0.2, 7.0), places=3)

    def test_cluster_points_are_combined_by_median(self):
        frame = [pt(0.1, 8.0, -4.0), pt(0.2, 8.3, -4.2), pt(0.0, 8.1, -3.8), pt(0.1, 20.0, -9.0)]
        out = run(self.ex, [frame] * 4)[-1]
        self.assertAlmostEqual(out["distance_m"], 8.1, delta=0.05)
        self.assertAlmostEqual(out["closing_speed_mps"], 4.0, places=3)

    def test_noisy_measurements_are_smoothed(self):
        ranges = [8.0, 7.6, 9.3, 7.2, 6.8, 6.4, 6.1]   # 중간에 튀는 값(9.3)
        out = run(self.ex, [[pt(0.0, r, -4.0)] for r in ranges])[-1]
        self.assertLess(abs(out["distance_m"] - 6.8), 0.8)  # 튄 값 영향이 작음

    def test_range_gate(self):
        for y in (0.2, 30.0):
            ex = rt.ForwardTargetExtractor()
            self.assertTrue(all(o is None for o in run(ex, [[pt(0.0, y, -4.0)]] * 6)))

    def test_points_behind_the_radar_are_ignored(self):
        self.assertTrue(all(o is None for o in run(self.ex, [[pt(0.0, -5.0, -4.0)]] * 6)))

    def test_receding_target_is_not_a_collision_target(self):
        self.assertTrue(all(o is None for o in run(self.ex, [[pt(0.0, 6.0, +3.0)]] * 6)))  # 앞서 멀어지는 차

    def test_stationary_target_ahead_in_path_is_kept_with_ego_closing_speed(self):
        # 정면에 서 있는 물체: 내가 4m/s로 다가가니 상대속도 -4 → 접근 중으로 잡혀야 함 (정면을 막은 정지 차량)
        out = run(self.ex, [[pt(0.1, 10.0 - 0.4 * i, -4.0)] for i in range(5)])[-1]
        self.assertAlmostEqual(out["closing_speed_mps"], 4.0, places=3)

    def test_confirmed_target_survives_one_missed_frame_but_not_two(self):
        seq = [[pt(0, 8, -4)]] * 4 + [[]] + [[pt(0, 7, -4)]] + [[]] * 2
        out = run(self.ex, seq)
        self.assertIsNotNone(out[4])      # 한 프레임 놓쳐도 유지
        self.assertIsNotNone(out[5])
        self.assertIsNone(out[7])         # 연속 두 프레임 놓치면 해제

    def test_big_range_jump_restarts_confirmation(self):
        seq = [[pt(0, 8, -4)]] * 4 + [[pt(0, 20, -4)]] + [[pt(0, 20, -4)]]
        out = run(self.ex, seq)
        self.assertIsNotNone(out[3])
        self.assertIsNone(out[4])         # 갑자기 다른 거리로 튀면 다시 3프레임 지속돼야 인정
        self.assertIsNone(out[5])

    def test_weak_points_filtered_when_snr_threshold_set(self):
        old = rt.MIN_SNR_DB
        rt.MIN_SNR_DB = 12.0
        try:
            ex = rt.ForwardTargetExtractor()
            self.assertTrue(all(o is None for o in run(ex, [[pt(0, 8, -4, snr=5.0)]] * 6)))
            ex2 = rt.ForwardTargetExtractor()
            self.assertIsNotNone(run(ex2, [[pt(0, 8, -4, snr=20.0)]] * 4)[-1])
        finally:
            rt.MIN_SNR_DB = old

    def test_velocity_sign_constant_flips_direction(self):
        old = rt.VELOCITY_APPROACH_SIGN
        rt.VELOCITY_APPROACH_SIGN = +1.0   # 실물에서 다가올 때 속도가 양수로 나오는 경우
        try:
            ex = rt.ForwardTargetExtractor()
            out = run(ex, [[pt(0, 8 - 0.4 * i, +4.0)] for i in range(5)])[-1]
            self.assertAlmostEqual(out["closing_speed_mps"], 4.0, places=3)
        finally:
            rt.VELOCITY_APPROACH_SIGN = old


class EndToEndTests(unittest.TestCase):
    """합성 프레임 바이트 → 파서 → 읽기 핸들러 → 추출 → radar_sensor.get_forward_target() 까지 한 줄로."""

    def setUp(self):
        radar_sensor.clear_target()
        rt._extractor = rt.ForwardTargetExtractor()
        rr_stats = radar_reader._stats
        rr_stats.update({"frames_ok": 0, "frames_bad": 0, "last_frame_at": 0.0, "last_num_points": 0})
        radar_reader.on_frame = rt.handle_frame

    def tearDown(self):
        radar_reader.on_frame = None
        radar_sensor.clear_target()

    def feed_frames(self, frames_points):
        ex = radar_parser.FrameExtractor()
        for n, points in enumerate(frames_points):
            for raw in ex.feed(build_frame(points, frame_number=n)):
                radar_reader.handle_frame(radar_parser.parse_frame(raw))

    def test_approaching_person_becomes_target_with_ttc(self):
        self.feed_frames([[(0.3, 8.0 - 0.4 * i, 0.0, -4.0)] for i in range(6)])
        target = radar_sensor.get_forward_target()
        self.assertIsNotNone(target)
        self.assertTrue(target["in_path"])
        self.assertAlmostEqual(target["closing_speed_mps"], 4.0, places=2)
        self.assertAlmostEqual(target["ttc_sec"], target["distance_m"] / 4.0, places=2)

    def test_target_is_cleared_when_object_disappears(self):
        self.feed_frames([[(0.3, 8.0 - 0.4 * i, 0.0, -4.0)] for i in range(5)])
        self.assertIsNotNone(radar_sensor.get_forward_target())
        self.feed_frames([[], [], []])
        self.assertIsNone(radar_sensor.get_forward_target())

    def test_parked_car_beside_path_never_reaches_arbiter(self):
        self.feed_frames([[(3.0, 6.0, 0.0, -0.1)]] * 8)
        self.assertIsNone(radar_sensor.get_forward_target())


if __name__ == "__main__":
    unittest.main()
