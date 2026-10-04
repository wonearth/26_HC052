"""
좌/우 초음파 거리 센서 (HC-SR04 계열) 읽기.
GPIO 핀(BCM 기준): 왼쪽 TRIG=23 / ECHO=24, 오른쪽 TRIG=10 / ECHO=9.

주의: HC-SR04의 ECHO 핀은 5V 신호를 출력하는데 라즈베리파이 GPIO 입력은 3.3V까지만
견디므로, ECHO 쪽은 전압분배 등으로 3.3V 이하로 낮춰서 연결되어 있어야 한다
(배선 자체는 이미 되어 있다는 전제하에 이 모듈은 신호 읽기/판단만 담당).
"""
try:
    from gpiozero import DistanceSensor
    _ULTRASONIC_AVAILABLE = True
except ImportError:
    _ULTRASONIC_AVAILABLE = False

# 초음파 센서를 하드웨어에서 뺐다. False면 GPIO 핀을 아예 잡지 않고 항상 "안전"으로 보고한다
# (센서가 없는데 핀을 열어두면 떠 있는 echo 핀의 노이즈가 가짜 거리값으로 읽힐 수 있음).
# 다시 장착하면 True로 바꾸면 된다.
ULTRASONIC_ENABLED = False

LEFT_TRIG_PIN = 23
LEFT_ECHO_PIN = 24
RIGHT_TRIG_PIN = 10
RIGHT_ECHO_PIN = 9

# gpiozero DistanceSensor 기본 max_distance는 1m(=100cm) — 150cm 임계값을 정확히
# 구분하려면 그보다 넉넉하게 잡아야 함 (안 그러면 100cm 넘는 거리는 전부 뭉개짐)
MAX_DISTANCE_M = 2.5

SAFE_DISTANCE_CM = 105   # 이상이면 안전 (기존 150cm의 70%로 감소 — 덜 민감하게)
DANGER_DISTANCE_CM = 70   # 이하면 위험 (기존 100cm의 70%로 감소, 그 사이는 주의)

RISK_RANK = {"SAFE": 0, "CAUTION": 1, "DANGER": 2}

_sensor_left = None
_sensor_right = None

if not ULTRASONIC_ENABLED:
    print("ℹ️  초음파 센서 비활성화됨 (ULTRASONIC_ENABLED=False) — GPIO 23/24/10/9를 사용하지 않습니다")
elif _ULTRASONIC_AVAILABLE:
    try:
        _sensor_left = DistanceSensor(echo=LEFT_ECHO_PIN, trigger=LEFT_TRIG_PIN, max_distance=MAX_DISTANCE_M)
        _sensor_right = DistanceSensor(echo=RIGHT_ECHO_PIN, trigger=RIGHT_TRIG_PIN, max_distance=MAX_DISTANCE_M)
        print(
            f"✅ 초음파 센서 초기화 완료 "
            f"(좌: TRIG{LEFT_TRIG_PIN}/ECHO{LEFT_ECHO_PIN}, 우: TRIG{RIGHT_TRIG_PIN}/ECHO{RIGHT_ECHO_PIN})"
        )
    except Exception as e:
        print(f"⚠️  초음파 센서 초기화 실패 — 초음파 감지 없이 동작합니다: {e}")
        _sensor_left = None
        _sensor_right = None
else:
    print("⚠️  gpiozero 라이브러리가 없어 초음파 센서 없이 동작합니다 (pip3 install gpiozero)")


def _distance_cm(sensor):
    if sensor is None:
        return None
    try:
        return sensor.distance * 100.0
    except Exception:
        # 배선 불안정 등으로 echo 신호를 못 받으면 gpiozero가 예외를 던질 수 있음 —
        # 여기서 흡수하지 않으면 이 값을 쓰는 detection_loop 스레드 전체가 죽어서
        # 카메라 인식/LED/부저까지 한꺼번에 멈춰버림. 이번엔 그냥 "측정 안 됨"으로 처리.
        return None


def get_risk(distance_cm):
    if distance_cm is None:
        return "SAFE"
    if distance_cm <= DANGER_DISTANCE_CM:
        return "DANGER"
    if distance_cm < SAFE_DISTANCE_CM:
        return "CAUTION"
    return "SAFE"


def get_worst_side():
    """좌/우 중 더 위험한 쪽의 (위험도, "좌측"/"우측", 거리cm)를 반환."""
    left_cm = _distance_cm(_sensor_left)
    right_cm = _distance_cm(_sensor_right)
    left_risk = get_risk(left_cm)
    right_risk = get_risk(right_cm)

    if RISK_RANK[left_risk] >= RISK_RANK[right_risk]:
        return left_risk, "좌측", left_cm
    return right_risk, "우측", right_cm
