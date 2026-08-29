"""
파이에 UART로 연결된 GPS 모듈(NEO-6M 등, NMEA 출력)을 읽는 모듈.

실제 모듈/배선이 다르면 GPS_PORT, GPS_BAUDRATE를 맞게 바꿔야 한다.
- UART(GPIO 14/15)로 연결한 경우 보통 /dev/serial0
- USB GPS 동글이면 보통 /dev/ttyUSB0
라즈베리파이OS에서 UART를 쓰려면 raspi-config에서 시리얼 포트를 활성화하고,
시리얼 콘솔(로그인 셸)은 꺼둬야 한다 (둘이 같은 포트를 두고 충돌함).
"""
import threading
import time
from datetime import datetime, timezone

try:
    import serial
    import pynmea2
    _GPS_LIBS_AVAILABLE = True
except ImportError:
    _GPS_LIBS_AVAILABLE = False

GPS_PORT = "/dev/serial0"
GPS_BAUDRATE = 9600

_lock = threading.Lock()
_position = {"lat": None, "lng": None, "speed_kmh": 0.0, "fix": False, "updated_at": None}


def get_current_position():
    with _lock:
        return dict(_position)


def _set_position(lat, lng, speed_kmh):
    with _lock:
        _position["lat"] = lat
        _position["lng"] = lng
        _position["speed_kmh"] = speed_kmh
        _position["fix"] = True
        _position["updated_at"] = datetime.now(timezone.utc).isoformat()


def mark_no_fix():
    with _lock:
        _position["fix"] = False


def gps_reader_loop():
    """백그라운드 스레드에서 계속 실행 — GPS 픽스를 읽어 공유 상태를 갱신."""
    if not _GPS_LIBS_AVAILABLE:
        print("⚠️  pyserial/pynmea2 미설치 — GPS 리더를 시작할 수 없습니다 (pip3 install pyserial pynmea2)")
        return

    while True:
        try:
            ser = serial.Serial(GPS_PORT, GPS_BAUDRATE, timeout=1)
            print(f"✅ GPS 포트 연결됨: {GPS_PORT} @ {GPS_BAUDRATE}bps")
            break
        except Exception as e:
            print(f"❌ GPS 포트 열기 실패({e}), 5초 후 재시도")
            time.sleep(5)

    no_fix_count = 0
    while True:
        try:
            raw = ser.readline().decode("ascii", errors="ignore").strip()
            if not raw.startswith("$GPRMC") and not raw.startswith("$GNRMC"):
                continue
            msg = pynmea2.parse(raw)
            if msg.status == "A" and msg.latitude and msg.longitude:  # A = 유효한 fix
                speed_kmh = float(msg.spd_over_grnd or 0) * 1.852  # knot -> km/h
                _set_position(float(msg.latitude), float(msg.longitude), speed_kmh)
                no_fix_count = 0
            else:
                no_fix_count += 1
                if no_fix_count >= 5:
                    mark_no_fix()
        except Exception:
            continue
