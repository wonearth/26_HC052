import serial
import time
import math
import threading

# =========================
# IMU 설정
# =========================
PORT = "/dev/ttyUSB0"
BAUD_RATE = 115200

COLLISION_G_THRESHOLD = 3.0
ROLLOVER_ANGLE_THRESHOLD = 60.0
ROLLOVER_TIME_THRESHOLD = 1.0

CONNECTED_TIMEOUT_SEC = 2.0  # 이 시간 안에 유효한 라인을 못 받으면 "미연결"로 판단
EVENT_LATCH_SEC = 2.5        # 충돌/전복이 감지된 순간부터 이만큼은 화면에 계속 보이도록 유지
                              # (실제 이벤트는 샘플 한 줄에서만 잠깐 참이라, latch 없인
                              # 1초 폴링 주기의 대시보드에서 놓치고 지나갈 수 있음)


# =========================
# 현재 IMU 상태
# =========================
_state_lock = threading.Lock()

_imu_state = {
    "roll": None,
    "pitch": None,

    "ax": None,
    "ay": None,
    "az": None,

    "acc_magnitude": None,
}

_last_data_at = 0.0    # time.monotonic() 기준 마지막으로 유효한 라인을 받은 시각
_impact_until = 0.0    # 이 시각까지는 충돌 상태를 유지 (latch)
_rollover_until = 0.0  # 이 시각까지는 전복 상태를 유지 (latch)


# =========================
# 센서 데이터 파싱
# =========================
def parse_sensor_data(line):
    """
    EBIMU 출력:
    *Roll,Pitch,Yaw,AccX,AccY,AccZ
    """

    try:
        line = line.decode("utf-8").strip()

        if not line.startswith("*"):
            return None

        data = line[1:].split(",")

        if len(data) < 6:
            return None

        roll = float(data[0])
        pitch = float(data[1])

        # data[2] = Yaw
        acc_x = float(data[3])
        acc_y = float(data[4])
        acc_z = float(data[5])

        return roll, pitch, acc_x, acc_y, acc_z

    except (UnicodeDecodeError, ValueError, IndexError):
        return None


# =========================
# 현재 IMU 상태 반환
# =========================
def get_imu_state():
    """connected/impact/rollover는 저장된 값을 그대로 읽는 게 아니라 조회 시점 기준으로
    다시 계산한다 — "포트가 열렸었는지"가 아니라 "최근에 실제로 유효한 데이터를 받았는지",
    "그 순간이었는지"가 아니라 "최근 EVENT_LATCH_SEC 안에 감지된 적 있는지"를 반영하기 위함."""
    with _state_lock:
        now = time.monotonic()
        state = dict(_imu_state)
        state["connected"] = (now - _last_data_at) <= CONNECTED_TIMEOUT_SEC
        state["impact"] = now < _impact_until
        state["rollover"] = now < _rollover_until
        return state


def get_imu_status_label():
    """대시보드 등 UI 표시용 — 미연결 > 충돌 감지 > 전복 감지 > 정상 순으로 판단."""
    state = get_imu_state()
    if not state["connected"]:
        return "미연결"
    if state["impact"]:
        return "충돌 감지"
    if state["rollover"]:
        return "전복 감지"
    return "정상"


# =========================
# IMU 백그라운드 루프
# =========================
def imu_reader_loop():
    global _last_data_at, _impact_until, _rollover_until

    rollover_start_time = 0.0
    is_rolling_over = False

    try:
        ser = serial.Serial(
            PORT,
            BAUD_RATE,
            timeout=0.1
        )

        print(f"✅ IMU 포트 연결 완료: {PORT} ({BAUD_RATE} baud) — 유효 데이터 수신은 별도 확인 필요")

    except Exception as e:

        print(f"❌ IMU 연결 실패: {e}")
        return

    try:

        while True:

            if ser.in_waiting <= 0:
                time.sleep(0.01)
                continue

            raw_line = ser.readline()
            sensor_values = parse_sensor_data(raw_line)

            if sensor_values is None:
                continue

            roll, pitch, acc_x, acc_y, acc_z = sensor_values

            # =========================
            # 1. 충돌 감지
            # =========================
            acc_magnitude = math.sqrt(
                acc_x**2 +
                acc_y**2 +
                acc_z**2
            )

            impact = acc_magnitude >= COLLISION_G_THRESHOLD

            if impact:
                print(
                    f"[경고] 충돌 감지! "
                    f"충격량: {acc_magnitude:.2f}g"
                )

            # =========================
            # 2. 전복 감지
            # =========================
            rollover = False

            tilted = (
                abs(roll) >= ROLLOVER_ANGLE_THRESHOLD
                or
                abs(pitch) >= ROLLOVER_ANGLE_THRESHOLD
            )

            if tilted:

                if not is_rolling_over:

                    is_rolling_over = True
                    rollover_start_time = time.time()

                else:

                    duration = (
                        time.time()
                        - rollover_start_time
                    )

                    if duration >= ROLLOVER_TIME_THRESHOLD:

                        rollover = True

                        print(
                            f"[위험] 차량 전복! "
                            f"Roll={roll:.1f}°, "
                            f"Pitch={pitch:.1f}°"
                        )

            else:

                is_rolling_over = False
                rollover_start_time = 0.0

            # =========================
            # 상태 저장
            # =========================
            with _state_lock:

                _last_data_at = time.monotonic()

                _imu_state["roll"] = roll
                _imu_state["pitch"] = pitch

                _imu_state["ax"] = acc_x
                _imu_state["ay"] = acc_y
                _imu_state["az"] = acc_z

                _imu_state["acc_magnitude"] = acc_magnitude

                if impact:
                    _impact_until = time.monotonic() + EVENT_LATCH_SEC
                if rollover:
                    _rollover_until = time.monotonic() + EVENT_LATCH_SEC

    except Exception as e:

        print(f"❌ IMU 읽기 오류: {e}")

    finally:

        ser.close()
