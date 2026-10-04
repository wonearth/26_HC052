"""
레이더 시리얼 읽기: 설정(.cfg)을 명령 포트로 보내고,
데이터 포트에서 프레임을 받아 파싱한다.

현재 Raspberry Pi 연결:
- /dev/ttyUSB0 -> IMU
- /dev/ttyUSB1 -> Radar CLI  (CP2105 Enhanced, 115200)
- /dev/ttyUSB2 -> Radar DATA (CP2105 Standard, 921600)

변경 사항:
- 정상 프레임이 몇 초간 없다는 이유만으로 reader를 종료하지 않음
- 실제 SerialException 등 시리얼 오류가 발생했을 때만
  radar_reader_loop가 종료되어 supervisor가 재시작하도록 함
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

# 레이더 명령(CLI) 포트
# CP2105 Enhanced Com Port
CLI_PORT = "/dev/ttyUSB1"
CLI_BAUD = 115200

# 레이더 데이터 출력 포트
# CP2105 Standard Com Port
DATA_PORT = "/dev/ttyUSB2"
DATA_BAUD = 921600

CFG_PATH = Path(__file__).with_name("radar.cfg")

# cfg 명령 한 줄에 대한 응답 대기 시간
CFG_LINE_TIMEOUT_SEC = 1.5

# 마지막 정상 프레임 이후 이 시간이 지나면
# 대시보드에서는 일시적으로 no_signal 표시
# 단, reader 스레드를 종료하지는 않음
RADAR_STALE_SEC = 5.0

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
        no_signal = 최근 정상 프레임이 없음

    no_signal이 되어도 radar reader 자체는 종료하지 않는다.
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
):
    """
    데이터 포트에서 레이더 프레임을 계속 읽는다.

    정상 프레임이 일정 시간 없더라도
    TimeoutError를 발생시키지 않는다.

    실제 USB/시리얼 연결에 문제가 발생하면
    data.read()에서 SerialException 등이 발생하고
    상위 supervisor가 reader를 재시작한다.
    """

    while not should_stop():

        # 실제 장치가 끊기면 여기서
        # SerialException이 발생하여 상위로 전달됨
        chunk = data.read(4096)

        if not chunk:
            continue

        extractor.add(chunk)

        for raw in extractor.iter_frames():

            parsed = radar_parser.parse_frame(raw)

            if parsed is None:

                _bump(frames_bad=1)
                extractor.resync(raw)

            else:

                handle(parsed)


def radar_reader_loop():
    """
    레이더 시리얼 읽기 스레드.

    supervisor가 실행하며,
    실제 시리얼 오류가 발생하여 함수가 종료되면
    supervisor가 다시 시작한다.
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