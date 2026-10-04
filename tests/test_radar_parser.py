import math
import os
import random
import struct
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import radar_parser as rp
from radar_frames import build_frame

PERSON = (0.5, 8.0, 0.0, -4.0)       # 전방 8m, 오른쪽 0.5m, 다가오는 중
CAR_SIDE = (3.0, 6.0, 0.0, -0.1)


class ParseFrameTests(unittest.TestCase):
    def test_roundtrip_values_and_derived_fields(self):
        parsed = rp.parse_frame(build_frame([PERSON, CAR_SIDE], frame_number=42))
        self.assertEqual(parsed["frame_number"], 42)
        self.assertEqual(len(parsed["points"]), 2)
        p = parsed["points"][0]
        self.assertAlmostEqual(p["x"], 0.5, places=5)
        self.assertAlmostEqual(p["y"], 8.0, places=5)
        self.assertAlmostEqual(p["v"], -4.0, places=5)
        self.assertAlmostEqual(p["range_m"], math.sqrt(0.25 + 64), places=4)
        self.assertAlmostEqual(p["azimuth_deg"], math.degrees(math.atan2(0.5, 8.0)), places=3)

    def test_side_info_gives_snr(self):
        parsed = rp.parse_frame(build_frame([PERSON, CAR_SIDE]))
        self.assertAlmostEqual(parsed["points"][0]["snr_db"], 15.0)
        self.assertAlmostEqual(parsed["points"][1]["snr_db"], 16.0)

    def test_without_side_info_snr_is_none(self):
        parsed = rp.parse_frame(build_frame([PERSON], side_info=False))
        self.assertIsNone(parsed["points"][0]["snr_db"])

    def test_empty_frame(self):
        parsed = rp.parse_frame(build_frame([]))
        self.assertEqual(parsed["points"], [])

    def test_tlv_length_convention_is_auto_detected(self):
        a = rp.parse_frame(build_frame([PERSON], length_includes_header=False))
        b = rp.parse_frame(build_frame([PERSON], length_includes_header=True))
        self.assertFalse(a["tlv_length_includes_header"])
        self.assertTrue(b["tlv_length_includes_header"])
        self.assertEqual(len(b["points"]), 1)

    def test_unknown_tlv_is_skipped(self):
        frame = build_frame([PERSON], extra_tlvs=[(99, b"\x01" * 12)])
        self.assertEqual(len(rp.parse_frame(frame)["points"]), 1)

    def test_non_finite_points_are_dropped(self):
        frame = build_frame([PERSON, (float("nan"), 5.0, 0.0, 0.0), (1.0, float("inf"), 0.0, 0.0)], side_info=False)
        self.assertEqual(len(rp.parse_frame(frame)["points"]), 1)

    def test_wrong_declared_length_is_rejected(self):
        good = build_frame([PERSON])
        bad = build_frame([PERSON], declared_total=len(good) + 32)
        self.assertIsNone(rp.parse_frame(bad))

    def test_truncated_or_garbage_is_rejected(self):
        good = build_frame([PERSON, CAR_SIDE])
        self.assertIsNone(rp.parse_frame(good[:-40]))
        self.assertIsNone(rp.parse_frame(b"\x00" * 100))
        self.assertIsNone(rp.parse_frame(b""))

    def test_fuzz_never_raises(self):
        rng = random.Random(1234)
        good = bytearray(build_frame([PERSON, CAR_SIDE]))
        for _ in range(3000):
            data = bytearray(good)
            for _ in range(rng.randint(1, 8)):
                data[rng.randrange(8, len(data))] = rng.randrange(256)
            rp.parse_frame(bytes(data))                              # 예외만 안 나면 됨
            rp.parse_frame(rp.MAGIC + bytes(rng.randrange(256) for _ in range(rng.randint(0, 200))))


class FrameExtractorTests(unittest.TestCase):
    def test_garbage_before_frame_is_skipped(self):
        ex = rp.FrameExtractor()
        frames = ex.feed(b"\xde\xad\xbe\xef" * 10 + build_frame([PERSON], frame_number=7))
        self.assertEqual(len(frames), 1)
        self.assertEqual(rp.parse_frame(frames[0])["frame_number"], 7)
        self.assertGreaterEqual(ex.dropped_bytes, 40)

    def test_byte_by_byte_feed_gives_same_frames(self):
        stream = build_frame([PERSON], frame_number=1) + build_frame([CAR_SIDE], frame_number=2)
        ex = rp.FrameExtractor()
        got = []
        for b in stream:
            got.extend(ex.feed(bytes([b])))
        self.assertEqual([rp.parse_frame(f)["frame_number"] for f in got], [1, 2])

    def test_random_chunking(self):
        rng = random.Random(7)
        frames_in = [build_frame([PERSON] * (i % 4), frame_number=i) for i in range(1, 30)]
        stream = b"".join(frames_in)
        ex, got, i = rp.FrameExtractor(), [], 0
        while i < len(stream):
            step = rng.randint(1, 300)
            got.extend(ex.feed(stream[i:i + step]))
            i += step
        self.assertEqual([rp.parse_frame(f)["frame_number"] for f in got], list(range(1, 30)))

    def test_fake_magic_with_absurd_length_is_skipped(self):
        fake = rp.MAGIC + struct.pack("<8I", 0, 0xFFFFFFF0, 0, 0, 0, 0, 0, 0)
        ex = rp.FrameExtractor()
        frames = ex.feed(fake + build_frame([PERSON], frame_number=5))
        self.assertEqual([rp.parse_frame(f)["frame_number"] for f in frames], [5])
        self.assertEqual(ex.bad_length_frames, 1)

    def test_partial_frame_waits_for_rest(self):
        frame = build_frame([PERSON, CAR_SIDE])
        ex = rp.FrameExtractor()
        self.assertEqual(ex.feed(frame[:60]), [])
        self.assertEqual(len(ex.feed(frame[60:])), 1)

    def test_magic_split_across_chunks(self):
        frame = build_frame([PERSON])
        ex = rp.FrameExtractor()
        self.assertEqual(ex.feed(b"\x00\x00" + frame[:4]), [])
        self.assertEqual(len(ex.feed(frame[4:])), 1)

    def test_buffer_does_not_grow_unbounded_on_noise(self):
        ex = rp.FrameExtractor()
        for _ in range(200):
            ex.feed(b"\x55" * 1000)
        self.assertLess(len(ex._buf), 64)


if __name__ == "__main__":
    unittest.main()
