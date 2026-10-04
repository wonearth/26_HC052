import serial
import time
from gpiozero import OutputDevice

# =========================
# 설정
# =========================
IMU_PORT = "/dev/ttyUSB0"
BAUD_RATE = 115200

BUZZER_PIN = 17

# 정상 자세에서 X 또는 Y가 45도 이상 변하면 넘어짐
TILT_THRESHOLD = 45.0

# 처음 기준 자세 측정 횟수
CALIBRATION_SAMPLES = 50


# =========================
# 부저 설정
# =========================
buzzer = OutputDevice(
    BUZZER_PIN,
    active_high=True,
    initial_value=False
)


# =========================
# IMU 연결
# =========================
ser = serial.Serial(
    IMU_PORT,
    BAUD_RATE,
    timeout=1
)

time.sleep(1)

print("==============================")
print(" IMU 넘어짐 감지 시작")
print(" 킥보드를 똑바로 세워두세요.")
print("==============================")


# =========================
# IMU 데이터 읽기
# =========================
def read_imu():

    line = ser.readline().decode(
        "utf-8",
        errors="ignore"
    ).strip()

    if not line:
        return None

    # 데이터 앞의 * 제거
    line = line.lstrip("*")

    try:
        values = line.split(",")

        if len(values) < 3:
            return None

        x = float(values[0])
        y = float(values[1])
        z = float(values[2])

        return x, y, z

    except ValueError:
        return None


# =========================
# 기준 자세 자동 측정
# =========================
samples = []

print("\n기준 자세 측정 중...")

while len(samples) < CALIBRATION_SAMPLES:

    data = read_imu()

    if data is not None:

        samples.append(data)

        print(
            f"\r측정 중: "
            f"{len(samples)}/{CALIBRATION_SAMPLES}",
            end=""
        )


# 평균값을 정상 자세로 저장
base_x = sum(v[0] for v in samples) / len(samples)
base_y = sum(v[1] for v in samples) / len(samples)
base_z = sum(v[2] for v in samples) / len(samples)


print("\n\n==============================")
print(" 기준 자세 설정 완료")
print("==============================")

print(
    f"X={base_x:.1f}° "
    f"Y={base_y:.1f}° "
    f"Z={base_z:.1f}°"
)

print(f"\n넘어짐 임계값: {TILT_THRESHOLD}°")
print("넘어짐 감지 시작\n")


# =========================
# 넘어짐 감지
# =========================
try:

    while True:

        data = read_imu()

        if data is None:
            continue

        x, y, z = data

        # 정상 자세와 현재 자세의 차이
        dx = abs(x - base_x)
        dy = abs(y - base_y)

        print(
            f"X={x:6.1f}° "
            f"Y={y:6.1f}° "
            f"Z={z:6.1f}° | "
            f"X변화={dx:5.1f}° "
            f"Y변화={dy:5.1f}°"
        )

        # =========================
        # 넘어짐 판단
        # X/Y만 사용
        # =========================
        if (
            dx >= TILT_THRESHOLD
            or dy >= TILT_THRESHOLD
        ):

            print("🚨 넘어짐 감지 → BUZZER ON")
            buzzer.on()

        else:

            buzzer.off()

        time.sleep(0.02)


except KeyboardInterrupt:

    print("\n프로그램 종료")


finally:

    buzzer.off()
    ser.close()