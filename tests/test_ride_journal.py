import os
import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import ble_peripheral as bp


class JournalTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.path = Path(self.dir.name) / "active_ride.jsonl"

    def tearDown(self):
        self.dir.cleanup()

    def ride_with_events(self):
        s = bp.RideSession(self.path)
        s.start()
        s.record_event("warning", 1, "사람", 6.0, 2.0)
        s.record_event("danger", None, "레이더_전방", 3.0, 1.0)
        for _ in range(5):
            s.record_risk_sample("danger")
            time.sleep(0.02)
        return s

    def test_restart_mid_ride_keeps_events_and_ride_continues(self):
        s = self.ride_with_events()
        uuid = s._client_ride_uuid
        del s  # 프로그램이 죽었다고 가정 (메모리 소실)

        s2 = bp.RideSession(self.path)
        self.assertTrue(s2.restore())
        self.assertTrue(s2.is_active())
        pkg = s2.stop_and_package()
        self.assertEqual(pkg["client_ride_uuid"], uuid)
        self.assertEqual([e["object_class"] for e in pkg["events"]], ["사람", "레이더_전방"])

    def test_restore_after_stop_allows_retry_without_duplicating_stop(self):
        s = self.ride_with_events()
        first = s.stop_and_package()
        s.stop_and_package()  # 재시도 STOP
        stops = [l for l in self.path.read_text(encoding="utf-8").splitlines() if '"stop"' in l]
        self.assertEqual(len(stops), 1)

        s2 = bp.RideSession(self.path)
        self.assertTrue(s2.restore())
        self.assertFalse(s2.is_active())
        again = s2.stop_and_package()
        self.assertEqual(again["client_ride_uuid"], first["client_ride_uuid"])
        self.assertEqual(len(again["events"]), 2)

    def test_truncated_last_line_is_ignored(self):
        self.ride_with_events()
        with open(self.path, "a", encoding="utf-8") as f:
            f.write('{"type": "event", "occurred_at": "20')  # 쓰는 도중 전원이 꺼진 줄
        s2 = bp.RideSession(self.path)
        self.assertTrue(s2.restore())
        self.assertEqual(len(s2.stop_and_package()["events"]), 2)

    def test_stale_journal_is_not_restored(self):
        self.ride_with_events()
        old = time.time() - bp.JOURNAL_MAX_AGE_SEC - 10
        os.utime(self.path, (old, old))
        self.assertFalse(bp.RideSession(self.path).restore())

    def test_new_ride_overwrites_old_journal(self):
        self.ride_with_events()
        s = bp.RideSession(self.path)
        s.start()
        s2 = bp.RideSession(self.path)
        self.assertTrue(s2.restore())
        self.assertEqual(s2.stop_and_package()["events"], [])

    def test_no_journal_means_nothing_to_restore(self):
        self.assertFalse(bp.RideSession(self.path).restore())

    def test_journal_write_failure_never_breaks_recording(self):
        bad = Path(self.dir.name) / "no_such_dir" / "j.jsonl"
        s = bp.RideSession(bad)
        s.start()
        s.record_event("danger", None, "IMU_충돌", 0.0, None)
        self.assertEqual(len(s.stop_and_package()["events"]), 1)

    def test_risk_seconds_survive_restart_via_snapshot(self):
        s = bp.RideSession(self.path)
        s.start()
        s._last_snapshot_at -= bp.SNAPSHOT_INTERVAL_SEC + 1
        s.record_risk_sample("danger")
        time.sleep(0.2)
        s._last_snapshot_at -= bp.SNAPSHOT_INTERVAL_SEC + 1
        s.record_risk_sample("danger")  # 이 호출이 약 0.2초 누적 + 스냅샷 저장
        saved = dict(s._risk_seconds)
        s2 = bp.RideSession(self.path)
        s2.restore()
        self.assertAlmostEqual(s2._risk_seconds["위험"], saved["위험"], places=2)


if __name__ == "__main__":
    unittest.main()
