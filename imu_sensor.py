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


# =========================
# 현재 IMU 상태
# =========================
_state_lock = threading.Lock()

_imu_state = {
    "connected": False,

    "roll": None,
    "pitch": None,

    "ax": None,
    "ay": None,
    "az": None,

    "acc_magnitude": None,

    "impact": False,
    "rollover": False,
}


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
    with _state_lock:
        return dict(_imu_state)


# =========================
# IMU 백그라운드 루프
# =========================
def imu_reader_loop():

    rollover_start_time = 0.0
    is_rolling_over = False

    try:
        ser = serial.Serial(
            PORT,
            BAUD_RATE,
            timeout=0.1
        )

        print(f"✅ IMU 연결 완료: {PORT} ({BAUD_RATE} baud)")

        with _state_lock:
            _imu_state["connected"] = True

    except Exception as e:

        print(f"❌ IMU 연결 실패: {e}")

        with _state_lock:
            _imu_state["connected"] = False

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

                _imu_state["connected"] = True

                _imu_state["roll"] = roll
                _imu_state["pitch"] = pitch

                _imu_state["ax"] = acc_x
                _imu_state["ay"] = acc_y
                _imu_state["az"] = acc_z

                _imu_state["acc_magnitude"] = acc_magnitude

                _imu_state["impact"] = impact
                _imu_state["rollover"] = rollover

    except Exception as e:

        print(f"❌ IMU 읽기 오류: {e}")

        with _state_lock:
            _imu_state["connected"] = False

    finally:

        ser.close()