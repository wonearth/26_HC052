import serial
import time
import math
import threading

# =========================
# IMU 설정
# =========================

# 현재 연결 상태
# EBIMU      : /dev/ttyUSB0
# Radar CLI  : /dev/ttyUSB1
# Radar DATA : /dev/ttyUSB2
PORT = "/dev/ttyUSB0"
BAUD_RATE = 115200

COLLISION_G_THRESHOLD = 3.0

ROLLOVER_ANGLE_THRESHOLD = 75.0
ROLLOVER_TIME_THRESHOLD = 1.5

TILT_RESET_GRACE_SEC = 0.3

CONNECTED_TIMEOUT_SEC = 2.0
EVENT_LATCH_SEC = 2.5


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

_last_data_at = 0.0
_impact_until = 0.0
_rollover_until = 0.0


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
    """
    connected:
        최근 CONNECTED_TIMEOUT_SEC 안에
        실제 유효 데이터를 받았는지 확인

    impact / rollover:
        최근 이벤트 발생 후 EVENT_LATCH_SEC 동안 유지
    """

    with _state_lock:

        now = time.monotonic()

        state = dict(_imu_state)

        state["connected"] = (
            (now - _last_data_at)
            <= CONNECTED_TIMEOUT_SEC
        )

        state["impact"] = now < _impact_until
        state["rollover"] = now < _rollover_until

        return state


def get_imu_status_label():
    """
    대시보드 표시용 상태
    """

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

    global _last_data_at
    global _impact_until
    global _rollover_until

    rollover_start_time = 0.0
    is_rolling_over = False
    last_tilted_at = 0.0

    # -------------------------
    # IMU 포트 연결
    # -------------------------
    try:

        ser = serial.Serial(
            PORT,
            BAUD_RATE,
            timeout=0.1
        )

        print(
            f"✅ IMU 포트 연결 완료: "
            f"{PORT} ({BAUD_RATE} baud)"
        )

    except Exception as e:

        print(
            f"❌ IMU 연결 실패 "
            f"({PORT}): {e}"
        )

        return

    # -------------------------
    # IMU 데이터 수신
    # -------------------------
    try:

        while True:

            if ser.in_waiting <= 0:

                time.sleep(0.01)
                continue

            raw_line = ser.readline()

            sensor_values = parse_sensor_data(
                raw_line
            )

            if sensor_values is None:
                continue

            (
                roll,
                pitch,
                acc_x,
                acc_y,
                acc_z
            ) = sensor_values

            # =========================
            # 1. 충돌 감지
            # =========================
            acc_magnitude = math.sqrt(
                acc_x**2
                + acc_y**2
                + acc_z**2
            )

            impact = (
                acc_magnitude
                >= COLLISION_G_THRESHOLD
            )

            if impact:

                print(
                    f"[경고] 충돌 감지! "
                    f"충격량: "
                    f"{acc_magnitude:.2f}g"
                )

            # =========================
            # 2. 전복 감지
            # =========================
            rollover = False

            tilted = (
                abs(roll)
                >= ROLLOVER_ANGLE_THRESHOLD
                or
                abs(pitch)
                >= ROLLOVER_ANGLE_THRESHOLD
            )

            now = time.time()

            if tilted:

                if not is_rolling_over:

                    is_rolling_over = True
                    rollover_start_time = now

                last_tilted_at = now

                duration = (
                    now - rollover_start_time
                )

                if (
                    duration
                    >= ROLLOVER_TIME_THRESHOLD
                ):

                    rollover = True

                    print(
                        f"[위험] 차량 전복! "
                        f"Roll={roll:.1f}°, "
                        f"Pitch={pitch:.1f}°"
                    )

            else:

                if (
                    is_rolling_over
                    and
                    (
                        now - last_tilted_at
                        >= TILT_RESET_GRACE_SEC
                    )
                ):

                    is_rolling_over = False
                    rollover_start_time = 0.0

            # =========================
            # 상태 저장
            # =========================
            with _state_lock:

                mono_now = time.monotonic()

                _last_data_at = mono_now

                _imu_state["roll"] = roll
                _imu_state["pitch"] = pitch

                _imu_state["ax"] = acc_x
                _imu_state["ay"] = acc_y
                _imu_state["az"] = acc_z

                _imu_state[
                    "acc_magnitude"
                ] = acc_magnitude

                if impact:

                    _impact_until = (
                        mono_now
                        + EVENT_LATCH_SEC
                    )

                if rollover:

                    _rollover_until = (
                        mono_now
                        + EVENT_LATCH_SEC
                    )

    except Exception as e:

        print(
            f"❌ IMU 읽기 오류 "
            f"({PORT}): {e}"
        )

    finally:

        try:
            ser.close()
        except Exception:
            pass