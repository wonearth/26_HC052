import os
import sys
import threading
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import supervisor


def wait_until(cond, timeout=3.0):
    end = time.time() + timeout
    while time.time() < end:
        if cond():
            return True
        time.sleep(0.01)
    return False


class SupervisorTests(unittest.TestCase):
    def test_restarts_after_exception(self):
        count = {"n": 0}

        def flaky():
            count["n"] += 1
            if count["n"] < 3:
                raise RuntimeError("죽음")
            time.sleep(10)

        supervisor.run_supervised("t-flaky", flaky, min_backoff=0.01, max_backoff=0.02, log=lambda *_: None)
        self.assertTrue(wait_until(lambda: count["n"] >= 3))
        health = supervisor.get_health()["t-flaky"]
        self.assertGreaterEqual(health["restarts"], 2)

    def test_restarts_when_target_returns(self):
        count = {"n": 0}

        def returns():
            count["n"] += 1  # IMU처럼 연결 실패 시 그냥 return 하는 경우

        supervisor.run_supervised("t-ret", returns, min_backoff=0.01, max_backoff=0.02, log=lambda *_: None)
        self.assertTrue(wait_until(lambda: count["n"] >= 3))

    def test_crash_loop_switches_to_slow_retry_but_keeps_trying(self):
        count = {"n": 0}

        def always_crash():
            count["n"] += 1
            raise RuntimeError("계속 죽음")

        supervisor.run_supervised(
            "t-loop", always_crash, min_backoff=0.005, max_backoff=0.005,
            crash_limit=3, slow_retry=0.2, log=lambda *_: None,
        )
        self.assertTrue(wait_until(lambda: supervisor.get_health().get("t-loop", {}).get("state") == "failed"))
        n_at_failed = count["n"]
        self.assertTrue(wait_until(lambda: count["n"] > n_at_failed, timeout=2.0))  # 완전히 멈추지 않음

    def test_other_threads_unaffected_by_a_crashing_one(self):
        alive = {"n": 0}
        stop = threading.Event()

        def healthy():
            while not stop.is_set():
                alive["n"] += 1
                time.sleep(0.005)

        def crashing():
            raise RuntimeError("x")

        supervisor.run_supervised("t-ok", healthy, log=lambda *_: None)
        supervisor.run_supervised("t-bad", crashing, min_backoff=0.01, max_backoff=0.01, log=lambda *_: None)
        time.sleep(0.2)
        before = alive["n"]
        time.sleep(0.2)
        stop.set()
        self.assertGreater(alive["n"], before)
        self.assertEqual(supervisor.get_health()["t-ok"]["restarts"], 0)


if __name__ == "__main__":
    unittest.main()
