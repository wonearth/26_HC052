"""레이더 설정(켜기/포트/설정 파일)을 코드를 고치지 않고 환경변수로 바꿀 수 있는지, 포트 자동 탐색이 맞는지 확인."""
import os
import subprocess
import sys
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import radar_reader as rr

BY_ID_CLI = "/dev/serial/by-id/usb-Texas_Instruments_XDS110__03.00.00.18__Embedded_Debug_Probe_R0010010-if00"
BY_ID_DATA = "/dev/serial/by-id/usb-Texas_Instruments_XDS110__03.00.00.18__Embedded_Debug_Probe_R0010010-if03"


def run_in_fresh_process(env_value):
    """모듈 로드 시점에 읽는 값이라 새 프로세스에서 확인한다."""
    env = {k: v for k, v in os.environ.items() if not k.startswith("RADAR_")}
    if env_value is not None:
        env["RADAR_ENABLED"] = env_value
    out = subprocess.run([sys.executable, "-c", "import radar_reader as r; print(r.RADAR_ENABLED)"],
                         cwd=ROOT, env=env, capture_output=True, text=True, timeout=20)
    return out.stdout.strip()


class EnableFlagTests(unittest.TestCase):
    def test_default_is_off(self):
        self.assertEqual(run_in_fresh_process(None), "False")

    def test_env_turns_it_on(self):
        for value in ("1", "true", "YES", "on"):
            self.assertEqual(run_in_fresh_process(value), "True", value)

    def test_other_values_stay_off(self):
        for value in ("0", "", "no", "false"):
            self.assertEqual(run_in_fresh_process(value), "False", repr(value))


class FindPortsTests(unittest.TestCase):
    def setUp(self):
        self.env = mock.patch.dict(os.environ, {}, clear=False)
        self.env.start()
        for key in ("RADAR_CLI_PORT", "RADAR_DATA_PORT"):
            os.environ.pop(key, None)

    def tearDown(self):
        self.env.stop()

    @staticmethod
    def fake_glob(mapping):
        return lambda pattern: mapping.get(pattern, [])

    def test_falls_back_to_ttyacm_when_nothing_found(self):
        with mock.patch("glob.glob", self.fake_glob({})):
            self.assertEqual(rr.find_ports(), (rr.CLI_PORT, rr.DATA_PORT))

    def test_ti_xds110_is_found_by_id_even_if_ttyacm_numbers_changed(self):
        mapping = {"/dev/serial/by-id/*XDS110*-if00": [BY_ID_CLI], "/dev/serial/by-id/*XDS110*-if03": [BY_ID_DATA]}
        with mock.patch("glob.glob", self.fake_glob(mapping)):
            self.assertEqual(rr.find_ports(), (BY_ID_CLI, BY_ID_DATA))

    def test_env_overrides_everything(self):
        os.environ["RADAR_CLI_PORT"], os.environ["RADAR_DATA_PORT"] = "/dev/ttyACM2", "/dev/ttyACM3"
        mapping = {"/dev/serial/by-id/*XDS110*-if00": [BY_ID_CLI], "/dev/serial/by-id/*XDS110*-if03": [BY_ID_DATA]}
        with mock.patch("glob.glob", self.fake_glob(mapping)):
            self.assertEqual(rr.find_ports(), ("/dev/ttyACM2", "/dev/ttyACM3"))

    def test_only_one_port_given_still_uses_discovery_for_the_other(self):
        os.environ["RADAR_CLI_PORT"] = "/dev/ttyACM5"
        mapping = {"/dev/serial/by-id/*XDS110*-if00": [BY_ID_CLI], "/dev/serial/by-id/*XDS110*-if03": [BY_ID_DATA]}
        with mock.patch("glob.glob", self.fake_glob(mapping)):
            self.assertEqual(rr.find_ports(), ("/dev/ttyACM5", BY_ID_DATA))

    def test_snapshot_reports_ports_only_when_enabled(self):
        old = rr.RADAR_ENABLED
        try:
            rr.RADAR_ENABLED = False
            self.assertIsNone(rr.get_dashboard_snapshot()["ports"])
            rr.RADAR_ENABLED = True
            with mock.patch("glob.glob", self.fake_glob({})):
                self.assertEqual(rr.get_dashboard_snapshot()["ports"], [rr.CLI_PORT, rr.DATA_PORT])
        finally:
            rr.RADAR_ENABLED = old


if __name__ == "__main__":
    unittest.main()
