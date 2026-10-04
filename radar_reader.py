"""
레이더 시리얼 읽기: 설정(.cfg)을 명령 포트로 보내고, 데이터 포트에서 프레임을 받아 파싱한다.

!! 실물 레이더로는 아직 검증하지 않았다 (브링업에서 확인).

코드를 고치지 않고 환경변수로 설정한다 (고쳐서 커밋하지 않아도 되고 git pull이 충돌하지 않음):
    RADAR_ENABLED=1 python3 app.py                   # 레이더 읽기 켜기 (기본은 꺼짐)
    RADAR_CLI_PORT=/dev/ttyACM0 RADAR_DATA_PORT=/dev/ttyACM1   # 포트를 직접 지정 (생략하면 자동 탐색)
    RADAR_CFG=/path/to/radar.cfg                     # 설정 파일 위치 (기본: 프로젝트 폴더의 radar.cfg)
RADAR_ENABLED가 꺼져 있는 동안 app.py는 이 스레드를 시작하지 않는다.
"""
import glob
import os
import threading
import time
from pathlib import Path

import radar_parser
import radar_sensor
import supervisor

# 레이더가 없는 환경에서 재시작만 반복하지 않도록 기본은 꺼짐. 켜려면 환경변수 RADAR_ENABLED=1
RADAR_ENABLED = os.environ.get("RADAR_ENABLED", "").strip().lower() in ("1", "true", "yes", "on")

CLI_PORT = "/dev/ttyACM0"    # 자동 탐색에 실패했을 때 쓰는 기본값
CLI_BAUD = 115200
DATA_PORT = "/dev/ttyACM1"
DATA_BAUD = 921600
CFG_PATH = Path(os.environ.get("RADAR_CFG") or Path(__file__).with_name("radar.cfg"))  # 없으면 이미 설정된 레이더로 보고 설정 전송을 건너뜀


def find_ports():
    """(명령 포트, 데이터 포트). 우선순위: 환경변수 → TI XDS110 자동 탐색 → 기본값(ttyACM0/1).
    AWR6843ISK는 USB로 꽂으면 XDS110 장치로 보이고, 명령(User UART)은 -if00, 데이터(Aux Data Port)는 -if03.
    ttyACM 번호는 부팅/연결 순서에 따라 바뀔 수 있어서 /dev/serial/by-id 이름으로 찾는 게 더 안전하다."""
    cli, data = os.environ.get("RADAR_CLI_PORT"), os.environ.get("RADAR_DATA_PORT")
    if not (cli and data):
        by_id_cli = sorted(glob.glob("/dev/serial/by-id/*XDS110*-if00"))
        by_id_data = sorted(glob.glob("/dev/serial/by-id/*XDS110*-if03"))
        if by_id_cli and by_id_data:
            cli, data = cli or by_id_cli[0], data or by_id_data[0]
    return cli or CLI_PORT, data or DATA_PORT

CFG_LINE_TIMEOUT_SEC = 1.5
NO_DATA_RESTART_SEC = 5.0  # 이 시간 동안 유효 프레임이 없으면 예외 → 감시 스레드가 포트를 다시 열고 설정부터 재시도

RADAR_STALE_SEC = 2.0         # 대시보드: 이 시간 넘게 프레임이 없으면 "신호 없음"으로 표시
MAX_DASHBOARD_POINTS = 100    # 대시보드로 보내는 점 개수 상한 (가까운 점 우선)

_stats_lock = threading.Lock()
# bytes_in: 데이터 포트로 들어온 바이트 수(0이면 레이더가 아무것도 안 보냄), cfg: 설정 파일 전송 결과(none/sent/missing)
_stats = {"frames_ok": 0, "frames_bad": 0, "last_frame_at": 0.0, "last_num_points": 0, "bytes_in": 0, "cfg": "none"}
_latest_points = []  # 가장 최근 프레임의 점 [(x, y, v)] — 대시보드의 레이더 화면용

on_frame = None  # 해석된 프레임이 올 때마다 호출될 함수(frame dict) — 전방 대상 추출이 여기에 연결됨


def get_stats():
    with _stats_lock:
        return dict(_stats)


def _bump(**changes):
    with _stats_lock:
        for key, value in changes.items():
            _stats[key] = _stats[key] + value if key.startswith(("frames_", "bytes_")) else value


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
        "ports": list(find_ports()) if RADAR_ENABLED else None,   # 어느 포트를 쓰는지 화면에서 확인
        "bytes_in": stats["bytes_in"],
        "cfg": stats["cfg"],
        "worker": supervisor.get_health().get("radar") if RADAR_ENABLED else None,   # 읽기 스레드의 상태와 마지막 오류
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
            _bump(bytes_in=len(chunk))
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

    cli_port, data_port = find_ports()
    print(f"🔌 레이더 포트: 명령={cli_port}, 데이터={data_port}")
    cli = serial.Serial(cli_port, CLI_BAUD, timeout=0.1)
    data = serial.Serial(data_port, DATA_BAUD, timeout=0.1)
    try:
        if CFG_PATH.exists():
            send_cfg(cli, load_cfg_lines(CFG_PATH))
            _bump(cfg="sent")
            print(f"✅ 레이더 설정 전송 완료 ({CFG_PATH.name})")
        else:
            _bump(cfg="missing")
            print(f"ℹ️  {CFG_PATH} 없음 — 이미 설정된 레이더로 보고 데이터만 읽습니다")
        read_frames(data, radar_parser.FrameExtractor(), handle_frame)
    finally:
        for port in (cli, data):
            try:
                port.close()
            except Exception:
                pass
