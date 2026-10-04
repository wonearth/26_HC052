"""
레이더 시리얼 읽기: 설정(.cfg)을 명령 포트로 보내고, 데이터 포트에서 프레임을 받아 파싱한다.

!! 실물 레이더로는 아직 검증하지 않았다 (1번 브링업에서 확인). 포트 이름/보레이트는 TI 보드의
!! 일반적인 값(명령 115200, 데이터 921600, /dev/ttyACM0·1)이고, 다르면 아래 상수만 고치면 된다.
RADAR_ENABLED가 False인 동안 app.py는 이 스레드를 시작하지 않는다.
"""
import threading
import time
from pathlib import Path

import radar_parser
import radar_sensor

RADAR_ENABLED = False  # 레이더 연결/설정 확인 전까지 꺼둠. 확인되면 True로 바꾸면 app.py가 스레드를 시작함

CLI_PORT = "/dev/ttyACM0"
CLI_BAUD = 115200
DATA_PORT = "/dev/ttyACM1"
DATA_BAUD = 921600
CFG_PATH = Path(__file__).with_name("radar.cfg")  # 없으면 이미 설정된 레이더로 보고 설정 전송을 건너뜀

CFG_LINE_TIMEOUT_SEC = 1.5
NO_DATA_RESTART_SEC = 5.0  # 이 시간 동안 유효 프레임이 없으면 예외 → 감시 스레드가 포트를 다시 열고 설정부터 재시도

RADAR_STALE_SEC = 2.0         # 대시보드: 이 시간 넘게 프레임이 없으면 "신호 없음"으로 표시
MAX_DASHBOARD_POINTS = 100    # 대시보드로 보내는 점 개수 상한 (가까운 점 우선)

_stats_lock = threading.Lock()
_stats = {"frames_ok": 0, "frames_bad": 0, "last_frame_at": 0.0, "last_num_points": 0}
_latest_points = []  # 가장 최근 프레임의 점 [(x, y, v)] — 대시보드의 레이더 화면용

on_frame = None  # 해석된 프레임이 올 때마다 호출될 함수(frame dict) — 전방 대상 추출이 여기에 연결됨


def get_stats():
    with _stats_lock:
        return dict(_stats)


def _bump(**changes):
    with _stats_lock:
        for key, value in changes.items():
            _stats[key] = _stats[key] + value if key.startswith("frames_") else value


def load_cfg_lines(path):
    lines = []
    for raw in Path(path).read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if line and not line.startswith("%"):  # TI cfg의 주석은 %로 시작
            lines.append(line)
    return lines


def send_cfg(cli, lines, timeout=CFG_LINE_TIMEOUT_SEC, log=print):
    """명령을 한 줄씩 보내고 매번 "Done"을 기다린다. "Error"거나 응답이 없으면 예외."""
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
        text = reply.decode("ascii", errors="replace")
        if "Error" in text or "Done" not in text:
            raise RuntimeError(f"레이더 설정 실패: '{line}' → {text.strip()!r}")
        log(f"  cfg ok: {line}")


def get_dashboard_snapshot(now=None):
    """웹 대시보드용 레이더 상태: 연결 상태, 최근 점들, 인정된 전방 대상.
    state: "off"(비활성화) / "ok"(수신 중) / "no_signal"(켜져 있는데 프레임이 안 옴)"""
    now = time.monotonic() if now is None else now
    with _stats_lock:
        stats = dict(_stats)
        points = list(_latest_points)
    last = stats["last_frame_at"]
    age = (now - last) if last > 0 else None
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
        "age_sec": None if age is None else round(age, 2),
        "frames_ok": stats["frames_ok"],
        "frames_bad": stats["frames_bad"],
        "num_points": stats["last_num_points"] if live else 0,
        "points": points if live else [],          # 오래된 점은 보여주지 않음
        "target": radar_sensor.get_forward_target() if live else None,
    }


def handle_frame(parsed):
    nearest = sorted(parsed["points"], key=lambda p: p["range_m"])[:MAX_DASHBOARD_POINTS]
    with _stats_lock:
        _latest_points[:] = [[round(p["x"], 2), round(p["y"], 2), round(p["v"], 2)] for p in nearest]
    _bump(frames_ok=1, last_frame_at=time.monotonic(), last_num_points=len(parsed["points"]))
    if on_frame is not None:
        on_frame(parsed)


def read_frames(data, extractor, handle, should_stop=lambda: False,
                no_data_timeout=NO_DATA_RESTART_SEC, clock=time.monotonic):
    """데이터 포트에서 읽어 프레임마다 handle을 호출. 유효 프레임이 오래 없으면 TimeoutError."""
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
                extractor.resync(raw)  # 길이가 깨진 프레임이면 그 안에 든 정상 프레임을 순서대로 다시 찾음
            else:
                handle(parsed)
                last_valid = now
        if now - last_valid > no_data_timeout:
            raise TimeoutError(f"레이더 프레임이 {no_data_timeout:.0f}초 넘게 안 옴")


def radar_reader_loop():
    """감시 스레드(supervisor)가 실행하는 본체. 예외로 끝나면 포트를 다시 열고 처음부터 재시도된다."""
    import serial  # Mac 등 pyserial이 없는 환경에서도 이 모듈을 import할 수 있게 지연 import

    cli = serial.Serial(CLI_PORT, CLI_BAUD, timeout=0.1)
    data = serial.Serial(DATA_PORT, DATA_BAUD, timeout=0.1)
    try:
        if CFG_PATH.exists():
            send_cfg(cli, load_cfg_lines(CFG_PATH))
            print(f"✅ 레이더 설정 전송 완료 ({CFG_PATH.name})")
        else:
            print(f"ℹ️  {CFG_PATH.name} 없음 — 이미 설정된 레이더로 보고 데이터만 읽습니다")
        read_frames(data, radar_parser.FrameExtractor(), handle_frame)
    finally:
        for port in (cli, data):
            try:
                port.close()
            except Exception:
                pass
