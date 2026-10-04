import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import radar_parser as rp
import radar_reader as rr
from radar_frames import build_frame


class FakeCli:
    def __init__(self, reply=b"Done\r\nmmwDemo:/>"):
        self.reply, self.sent, self._pending = reply, [], b""

    def write(self, data):
        self.sent.append(data.decode())
        self._pending = self.reply

    def read(self, n):
        out, self._pending = self._pending, b""
        return out


class FakeData:
    def __init__(self, chunks):
        self.chunks = list(chunks)

    def read(self, n):
        return self.chunks.pop(0) if self.chunks else b""


class CfgTests(unittest.TestCase):
    def test_load_cfg_skips_comments_and_blanks(self):
        with tempfile.NamedTemporaryFile("w", suffix=".cfg", delete=False, encoding="utf-8") as f:
            f.write("% 주석\nsensorStop\n\nflushCfg\n  profileCfg 0 60 7 \n% 끝\nsensorStart\n")
        try:
            self.assertEqual(rr.load_cfg_lines(f.name), ["sensorStop", "flushCfg", "profileCfg 0 60 7", "sensorStart"])
        finally:
            os.unlink(f.name)

    def test_send_cfg_sends_every_line(self):
        cli = FakeCli()
        rr.send_cfg(cli, ["sensorStop", "flushCfg"], log=lambda *_: None)
        self.assertEqual(cli.sent, ["sensorStop\n", "flushCfg\n"])

    def test_send_cfg_error_reply_raises(self):
        with self.assertRaises(RuntimeError):
            rr.send_cfg(FakeCli(reply=b"Error: bad arg\r\n"), ["badCmd"], log=lambda *_: None)

    def test_send_cfg_no_reply_raises(self):
        with self.assertRaises(RuntimeError):
            rr.send_cfg(FakeCli(reply=b""), ["sensorStop"], timeout=0.05, log=lambda *_: None)


class ReadFramesTests(unittest.TestCase):
    def setUp(self):
        rr._stats.update({"frames_ok": 0, "frames_bad": 0, "last_frame_at": 0.0, "last_num_points": 0})
        rr.on_frame = None
        rr._latest_points[:] = []

    def test_frames_reach_handler_in_order_and_garbage_is_counted(self):
        stream = (build_frame([(0, 5, 0, -1)], frame_number=1) + b"\x01\x02\x03"
                  + build_frame([], frame_number=2)
                  + build_frame([(0, 5, 0, -1)], frame_number=3, declared_total=999))  # 마지막은 깨진 프레임
        data = FakeData([stream[i:i + 50] for i in range(0, len(stream), 50)])
        got = []
        done = {"n": 0}

        def should_stop():
            done["n"] += 1
            return done["n"] > 40

        rr.read_frames(data, rp.FrameExtractor(), lambda parsed: got.append(parsed["frame_number"]), should_stop)
        self.assertEqual(got, [1, 2])

    def test_plausibly_corrupted_length_does_not_swallow_following_good_frames(self):
        good = build_frame([(0, 5, 0, -1)], frame_number=1)
        bad = build_frame([(0, 5, 0, -1)], frame_number=2, declared_total=len(good) + 96)  # 실제보다 길다고 적힘
        tail = b"".join(build_frame([(0, 5, 0, -1)], frame_number=n) for n in (3, 4, 5))
        data = FakeData([good + bad + tail])
        got, calls = [], {"n": 0}

        def should_stop():
            calls["n"] += 1
            return calls["n"] > 5

        rr.read_frames(data, rp.FrameExtractor(), lambda parsed: got.append(parsed["frame_number"]), should_stop)
        self.assertEqual(got, [1, 3, 4, 5])      # 2번만 잃고 3~5번은 살아남음

    def test_no_valid_frames_raises_timeout_so_supervisor_can_restart(self):
        t = {"now": 0.0}

        def clock():
            t["now"] += 1.0
            return t["now"]

        with self.assertRaises(TimeoutError):
            rr.read_frames(FakeData([]), rp.FrameExtractor(), lambda p: None, no_data_timeout=5.0, clock=clock)

    def test_handle_frame_updates_stats_and_calls_hook(self):
        seen = []
        rr.on_frame = seen.append
        points = [{"x": 0.1 * i, "y": 5.0 + i, "z": 0.0, "v": -1.0, "range_m": 5.0 + i} for i in range(3)]
        rr.handle_frame({"points": points, "frame_number": 9})
        stats = rr.get_stats()
        self.assertEqual((stats["frames_ok"], stats["last_num_points"]), (1, 3))
        self.assertGreater(stats["last_frame_at"], 0)
        self.assertEqual(len(seen), 1)


if __name__ == "__main__":
    unittest.main()
