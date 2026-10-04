"""
레이더 시리얼 읽기: 설정(.cfg)을 명령 포트로 보내고,
데이터 포트에서 프레임을 받아 파싱한다.

Raspberry Pi + TI AWR6843ISK에서 직접 확인한 포트:
- /dev/ttyUSB0 -> CLI  (115200)
- /dev/ttyUSB1 -> DATA (921600)

확인 방법:
- /dev/ttyUSB0에 115200 baud로 'version' 명령 전송
- xWR68xx / mmWave SDK 03.06.02.00 응답 확인
"""

import threading
import time
from pathlib import Path

import radar_parser
import radar_sensor


# ============================================================
# Radar configuration
# ============================================================

RADAR_ENABLED = True

# 명령(CLI) 포트
# 직접 version 명령 응답을 확인한 포트
CLI_PORT = "/dev/ttyUSB0"
CLI_BAUD = 115200

# 레이더 데이터 출력 포트
DATA_PORT = "/dev/ttyUSB1"
DATA_BAUD = 921600

CFG_PATH = Path(__file__).with_name("radar.cfg")

CFG_LINE_TIMEOUT_SEC = 1.5
NO_DATA_RESTART_SEC = 5.0

RADAR_STALE_SEC = 2.0
MAX_DASHBOARD_POINTS = 100


_stats_lock = threading.Lock()

_stats = {
    "frames_ok": 0,
    "frames_bad": 0,
    "last_frame_at": 0.0,
    "last_num_points": 0,
}

_latest_points = []

on_frame = None


def get_stats():
    with _stats_lock:
        return dict(_stats)


def _bump(**changes):
    with _stats_lock:
        for key, value in changes.items():
            _stats[key] = (
                _stats[key] + value
                if key.startswith("frames_")
                else value
            )


def load_cfg_lines(path):
    lines = []

    for raw in Path(path).read_text(
        encoding="utf-8"
    ).splitlines():

        line = raw.strip()

        if line and not line.startswith("%"):
            lines.append(line)

    return lines


def send_cfg(
    cli,
    lines,
    timeout=CFG_LINE_TIMEOUT_SEC,
    log=print,
):
    """
    레이더 설정 명령을 한 줄씩 전송하고
    각 명령의 Done 응답을 확인한다.
    """

    for line in lines:

        cli.write((line + "\n").encode("ascii"))

        deadline = time.monotonic() + timeout
        reply = b""

        while time.monotonic() < deadline:

            chunk = cli.read(256)

            if chunk:
                reply += chunk

            if b"Done" in reply or b"Error" in reply:
                break

            if not chunk:
                time.sleep(0.01)

        text = reply.decode(
            "ascii",
            errors="replace",
        )

        if "Error" in text or "Done" not in text:

            raise RuntimeError(
                f"레이더 설정 실패: "
                f"'{line}' → {text.strip()!r}"
            )

        log(f"  cfg ok: {line}")


def get_dashboard_snapshot(now=None):
    """
    웹 대시보드용 레이더 상태.

    state:
        off       = 레이더 비활성화
        ok        = 정상 프레임 수신 중
        no_signal = 활성화됐지만 프레임 없음
    """

    now = (
        time.monotonic()
        if now is None
        else now
    )

    with _stats_lock:

        stats = dict(_stats)
        points = list(_latest_points)

    last = stats["last_frame_at"]

    age = (
        now - last
        if last > 0
        else None
    )

    if not RADAR_ENABLED:
        state = "off"

    elif age is None or age > RADAR_STALE_SEC:
        state = "no_signal"

    else:
        state = "ok"

    live = state == "ok"

    return {
        "enabled": RADAR_ENABLED,
        "state": state,
        "age_sec": (
            None
            if age is None
            else round(age, 2)
        ),
        "frames_ok": stats["frames_ok"],
        "frames_bad": stats["frames_bad"],
        "num_points": (
            stats["last_num_points"]
            if live
            else 0
        ),
        "points": (
            points
            if live
            else []
        ),
        "target": (
            radar_sensor.get_forward_target()
            if live
            else None
        ),
    }


def handle_frame(parsed):

    nearest = sorted(
        parsed["points"],
        key=lambda p: p["range_m"],
    )[:MAX_DASHBOARD_POINTS]

    with _stats_lock:

        _latest_points[:] = [
            [
                round(p["x"], 2),
                round(p["y"], 2),
                round(p["v"], 2),
            ]
            for p in nearest
        ]

    _bump(
        frames_ok=1,
        last_frame_at=time.monotonic(),
        last_num_points=len(parsed["points"]),
    )

    if on_frame is not None:
        on_frame(parsed)


def read_frames(
    data,
    extractor,
    handle,
    should_stop=lambda: False,
    no_data_timeout=NO_DATA_RESTART_SEC,
    clock=time.monotonic,
):
    """
    데이터 포트에서 레이더 프레임을 읽는다.
    """

    last_valid = clock()

    while not should_stop():

        chunk = data.read(4096)

        now = clock()

        if chunk:
            extractor.add(chunk)

        for raw in extractor.iter_frames():

            parsed = radar_parser.parse_frame(raw)

            if parsed is None:

                _bump(frames_bad=1)
                extractor.resync(raw)

            else:

                handle(parsed)
                last_valid = now

        if now - last_valid > no_data_timeout:

            raise TimeoutError(
                f"레이더 프레임이 "
                f"{no_data_timeout:.0f}초 넘게 안 옴"
            )


def radar_reader_loop():
    """
    레이더 시리얼 읽기 스레드.

    supervisor가 실행하며,
    오류 발생 시 supervisor가 다시 시작한다.
    """

    import serial

    print(
        f"📡 레이더 포트 연결 시도: "
        f"CLI={CLI_PORT}, DATA={DATA_PORT}"
    )

    cli = serial.Serial(
        CLI_PORT,
        CLI_BAUD,
        timeout=0.1,
    )

    data = serial.Serial(
        DATA_PORT,
        DATA_BAUD,
        timeout=0.1,
    )

    print("✅ 레이더 시리얼 포트 연결 완료")

    try:

        if CFG_PATH.exists():

            print(
                f"📡 레이더 설정 전송 시작 "
                f"({CFG_PATH.name})"
            )

            send_cfg(
                cli,
                load_cfg_lines(CFG_PATH),
            )

            print(
                f"✅ 레이더 설정 전송 완료 "
                f"({CFG_PATH.name})"
            )

        else:

            print(
                f"ℹ️ {CFG_PATH.name} 없음 — "
                "이미 설정된 레이더로 보고 "
                "데이터만 읽습니다"
            )

        print("📡 레이더 데이터 수신 시작")

        read_frames(
            data,
            radar_parser.FrameExtractor(),
            handle_frame,
        )

    finally:

        for port in (cli, data):

            try:
                port.close()

            except Exception:
                pass