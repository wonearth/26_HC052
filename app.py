import os
os.environ["OMP_NUM_THREADS"] = "1"
os.environ["MKL_NUM_THREADS"] = "1"

import threading
import cv2
import numpy as np
import onnxruntime as ort
import time
from scipy.optimize import linear_sum_assignment
from collections import deque
from picamera2 import Picamera2
from flask import Flask, Response, jsonify

import ble_peripheral
import imu_sensor
import ultrasonic_sensor

try:
    from gpiozero import Buzzer, LED
    _GPIO_AVAILABLE = True
except ImportError:
    _GPIO_AVAILABLE = False

# 설정값
YOLO_SIZE = 320
CONF_THRESHOLD = 0.20
NMS_THRESHOLD = 0.45
FRAME_SKIP = 2
MAX_CAMERA_FAILURES = 10   # 연속 실패 시 '카메라 끊김'으로 상태 전환
LOW_LIGHT_THRESHOLD = 80   # 평균 밝기(0~255) 이하면 저조도 보정 적용

FOCAL_LENGTH = 524.0       # Camera Module 3 임시값, 추후 실제 캘리브레이션
MAX_LOST_FRAMES = 5        # 객체를 잠깐 놓쳐도 ID 유지
MOTION_THRESHOLD = 0.3     # 작은 거리 변화는 노이즈로 무시
MIN_APPROACH_SPEED = 0.3   # TTC 계산 최소 접근속도
STATIONARY_MARGIN_MPS = 0.5  # 접근속도가 "내 킥보드 속도 + 이 여유" 이내면 정지된 차로 판단

REACTION_TIME_SEC = 0.7    # 라이더 반응 시간(실측 필요) — 이 시간 동안은 등속으로 더 나아간다고 가정
DECELERATION_MPS2 = 3.5    # 킥보드 제동 감속도(m/s^2, 실측 필요)

# COCO 클래스: (이름, 평균 실제 높이 m)
CLASS_INFO = {
    0: ("사람", 1.7),
    1: ("자전거", 1.6),
    2: ("자동차", 1.5),
    3: ("오토바이", 1.6),
    5: ("버스", 3.0),
    7: ("트럭", 2.5),
}

BUZZER_GPIO_PIN = 17  # 실제 배선한 GPIO 핀 번호 (BCM 기준)
LED_GPIO_PIN = 27      # 위험(DANGER) 단계에서만 켜지는 시각 경고등

buzzer = None
led = None
if _GPIO_AVAILABLE:
    try:
        buzzer = Buzzer(BUZZER_GPIO_PIN)
        print(f"✅ 버저 초기화 완료 (GPIO {BUZZER_GPIO_PIN})")
    except Exception as e:
        print(f"⚠️  버저 초기화 실패 — 버저 없이 동작합니다: {e}")
    try:
        led = LED(LED_GPIO_PIN)
        print(f"✅ LED 초기화 완료 (GPIO {LED_GPIO_PIN})")
    except Exception as e:
        print(f"⚠️  LED 초기화 실패 — LED 없이 동작합니다: {e}")
else:
    print("⚠️  gpiozero 라이브러리가 없어 버저/LED 없이 동작합니다 (pip3 install gpiozero)")

# 위험도별 부저 패턴 (on_time, off_time) — 청감 테스트 후 조정 가능.
# 주의/경고는 느린 "삐 ... 삐 ... 삐", 위험은 빠르게 끊어지는 "삐삐삐삐삐삐".
BUZZER_PATTERNS = {
    "SAFE": None,
    "CAUTION": (0.15, 0.6),
    "WARNING": (0.15, 0.6),
    "DANGER": (0.08, 0.08),
}
IMPACT_ALARM_SEC = 1.0  # IMU 충격 감지 시 끊기지 않고 울리는 경고음 길이

_buzzer_pattern = None       # 현재 재생 중인 패턴 (None=꺼짐) — 안 바뀌면 다시 트리거하지 않음
_impact_alarm_until = 0.0    # 이 시각까지는 충격 경고음이 위험도 패턴보다 우선
_led_active = False


def set_buzzer(risk_key):
    """위험도에 맞는 부저 패턴을 재생. 상태가 안 바뀌면 다시 트리거하지 않음.
    충격 경고음(sound_impact_alarm) 재생 중이면 잠깐 갱신을 미뤄서 덮어쓰지 않는다."""
    global _buzzer_pattern
    if buzzer is None or time.monotonic() < _impact_alarm_until:
        return
    pattern = BUZZER_PATTERNS.get(risk_key)
    if pattern == _buzzer_pattern:
        return
    _buzzer_pattern = pattern
    if pattern is None:
        buzzer.off()
    else:
        on_time, off_time = pattern
        buzzer.beep(on_time=on_time, off_time=off_time, background=True)


def sound_impact_alarm():
    """IMU가 설정한 충격(가속도 임계값 초과)을 감지했을 때 1초간 끊기지 않는 경고음."""
    global _impact_alarm_until, _buzzer_pattern
    if buzzer is None:
        return
    buzzer.beep(on_time=IMPACT_ALARM_SEC, off_time=0.1, n=1, background=True)
    _impact_alarm_until = time.monotonic() + IMPACT_ALARM_SEC
    _buzzer_pattern = None  # 알람이 끝나면 다음 프레임에 현재 위험도로 다시 세팅되게 리셋


def set_led(should_light):
    """상태가 바뀔 때만 GPIO를 건드림 — 매 프레임 호출해도 안전."""
    global _led_active
    if led is None or should_light == _led_active:
        return
    _led_active = should_light
    if should_light:
        led.on()
    else:
        led.off()

cv2.setNumThreads(1)


# IoU 계산
def bbox_iou(box1, box2):
    x1 = max(box1[0], box2[0])
    y1 = max(box1[1], box2[1])
    x2 = min(box1[2], box2[2])
    y2 = min(box1[3], box2[3])

    inter_area = max(0, x2 - x1) * max(0, y2 - y1)
    box1_area = max(0, box1[2] - box1[0]) * max(0, box1[3] - box1[1])
    box2_area = max(0, box2[2] - box2[0]) * max(0, box2[3] - box2[1])

    return inter_area / float(box1_area + box2_area - inter_area + 1e-5)


# 객체 Tracking
class STrack:
    def __init__(self, bbox, score, cls_id):
        self.bbox = np.array(bbox, dtype=np.float32)
        self.score = score
        self.cls_id = cls_id
        self.track_id = 0
        self.lost_frames = 0


class SimpleByteTracker:
    def __init__(self, track_thresh=0.45, match_thresh=0.45, max_lost_frames=MAX_LOST_FRAMES):
        self.track_thresh = track_thresh
        self.match_thresh = match_thresh
        self.max_lost_frames = max_lost_frames
        self.tracked_stracks = []
        self.next_id = 1

    def update(self, output_results):
        detections = []

        for res in output_results:
            x1, y1, w, h, score, cls_id = res
            if score >= self.track_thresh:
                detections.append(STrack([x1, y1, x1 + w, y1 + h], score, cls_id))

        # 검출이 잠깐 끊겨도 기존 ID 유지
        if len(detections) == 0:
            alive_tracks = []
            for track in self.tracked_stracks:
                track.lost_frames += 1
                if track.lost_frames <= self.max_lost_frames:
                    alive_tracks.append(track)
            self.tracked_stracks = alive_tracks
            return []

        matches, u_track, u_det = self.linear_assignment(
            self.tracked_stracks, detections, self.match_thresh
        )

        for t_idx, d_idx in matches:
            track = self.tracked_stracks[t_idx]
            det = detections[d_idx]
            track.bbox = det.bbox
            track.score = det.score
            track.cls_id = det.cls_id
            track.lost_frames = 0

        for t_idx in u_track:
            self.tracked_stracks[t_idx].lost_frames += 1

        self.tracked_stracks = [
            track for track in self.tracked_stracks
            if track.lost_frames <= self.max_lost_frames
        ]

        # 새 객체에 새로운 ID 부여
        for d_idx in u_det:
            new_track = detections[d_idx]
            new_track.track_id = self.next_id
            self.next_id += 1
            self.tracked_stracks.append(new_track)

        return [track for track in self.tracked_stracks if track.lost_frames == 0]

    def linear_assignment(self, tracks, dets, thresh):
        if not tracks or not dets:
            return [], list(range(len(tracks))), list(range(len(dets)))

        iou_matrix = np.zeros((len(tracks), len(dets)), dtype=np.float32)

        for t, track in enumerate(tracks):
            for d, det in enumerate(dets):
                if track.cls_id != det.cls_id:  # 다른 클래스는 같은 객체로 매칭하지 않음
                    iou_matrix[t, d] = 0.0
                else:
                    iou_matrix[t, d] = bbox_iou(track.bbox, det.bbox)

        row_ind, col_ind = linear_sum_assignment(-iou_matrix)
        matches = []
        u_track = list(range(len(tracks)))
        u_det = list(range(len(dets)))

        for r, c in zip(row_ind, col_ind):
            if iou_matrix[r, c] >= thresh:
                matches.append((r, c))
                if r in u_track:
                    u_track.remove(r)
                if c in u_det:
                    u_det.remove(c)

        return matches, u_track, u_det


# Collision Zone
def get_collision_zone(frame_width, frame_height, speed_kmh=0.0):
    # 킥보드 전방 예상 진행영역 — 속도가 빠를수록 더 멀리(화면 위쪽)까지 넓게 잡음
    # (제동/반응 거리가 속도에 비례해 늘어나므로 저속일 때보다 미리 봐야 함. 계수는 실측 튜닝 필요)
    top_y_ratio = max(0.35, 0.55 - speed_kmh * 0.005)
    return np.array([
        [int(frame_width * 0.38), int(frame_height * top_y_ratio)],
        [int(frame_width * 0.62), int(frame_height * top_y_ratio)],
        [int(frame_width * 0.88), frame_height - 1],
        [int(frame_width * 0.12), frame_height - 1]
    ], dtype=np.int32)


def is_in_collision_zone(x1, y1, x2, y2, collision_zone):
    object_point = (int((x1 + x2) / 2), int(y2))  # bbox 아래 중앙 = 객체의 지면 위치
    return cv2.pointPolygonTest(collision_zone, object_point, False) >= 0


# 거리 기록 / 접근속도 / TTC
distance_history = {}
time_history = {}


def update_distance_history(track_id, distance, current_time):
    if track_id not in distance_history:
        distance_history[track_id] = deque(maxlen=5)
        time_history[track_id] = deque(maxlen=5)

    distance_history[track_id].append(distance)
    time_history[track_id].append(current_time)


def calculate_approach_speed(track_id):
    distances = distance_history.get(track_id)
    times = time_history.get(track_id)

    if distances is None or times is None or len(distances) < 3:
        return 0.0

    distance_change = distances[0] - distances[-1]  # 양수 = 가까워짐
    time_change = times[-1] - times[0]

    if time_change <= 0:
        return 0.0

    return distance_change / time_change


def get_motion_state(approach_speed):
    if approach_speed > MOTION_THRESHOLD:
        return "APPROACHING"
    elif approach_speed < -MOTION_THRESHOLD:
        return "LEAVING"
    return "STABLE"


def calculate_ttc(distance, approach_speed):
    if approach_speed <= MIN_APPROACH_SPEED:
        return None
    return distance / approach_speed  # TTC = 거리 / 상대 접근속도


def calculate_stopping_distance(speed_kmh):
    """반응거리 + 제동거리. 현재 내 속도로는 몇 m 안에 멈출 수 있는지 — 이 거리보다
    가까우면 상대가 안 다가오고 있어도(TTC=None이어도) 이미 위험하다고 봐야 함."""
    speed_mps = max(0.0, speed_kmh) / 3.6
    reaction_distance = speed_mps * REACTION_TIME_SEC
    braking_distance = (speed_mps ** 2) / (2 * DECELERATION_MPS2)
    return reaction_distance + braking_distance


# 최종 위험도 판단 (거리 + TTC + Collision Zone + 정지 가능 거리)
def get_final_risk(distance, ttc, in_collision_zone, stopping_distance=0.0):
    danger_dist = max(5.0, stopping_distance)          # 정지 가능 거리가 더 멀면 그쪽을 기준으로
    caution_dist = max(10.0, stopping_distance * 2)     # DANGER 기준의 2배를 CAUTION 경계로

    if not in_collision_zone:  # 진행경로 밖
        return "CAUTION" if distance <= danger_dist else "SAFE"

    if ttc is not None and ttc <= 1.5:  # TTC 1.5초 이하
        return "DANGER"

    if distance <= danger_dist:  # 진행경로 안 + 정지 가능 거리 이내
        return "DANGER"

    if ttc is not None and ttc <= 3.0:  # TTC 3초 이하
        return "WARNING"

    if distance <= caution_dist:  # 진행경로 안 + 정지 가능 거리의 2배 이내
        return "CAUTION"

    if ttc is not None and ttc <= 5.0:  # TTC 5초 이하
        return "CAUTION"

    return "SAFE"

fps_list = deque(maxlen=30)


# 실시간 위험도 상태 공유 (감지 스레드 -> /api/live_state)
RISK_RANK = {"SAFE": 0, "CAUTION": 1, "WARNING": 2, "DANGER": 3}
RISK_TITLES = {
    "SAFE": "현재 상태 · 안전",
    "CAUTION": "현재 상태 · 주의",
    "WARNING": "현재 상태 · 경고",
    "DANGER": "현재 상태 · 위험",
}

_state_lock = threading.Lock()
_live_state = {
    "risk": "safe",
    "title": RISK_TITLES["SAFE"],
    "message": "위험 요소가 감지되지 않았어요.",
    "class_name": None,
    "distance_m": None,
    "ttc_sec": None,
    "in_collision_zone": False,
}

_event_recorder = None  # main()에서 BLE 세션 생성 후 연결됨 — record_ride_event(risk_key, track_id, class_name, distance, ttc)
_speed_getter = None  # main()에서 연결됨 — get_current_speed_kmh() (폰이 보낸 최신 주행속도)
_ble_server = None  # main()에서 연결됨 — get_ride_status() (개발자 모니터링 웹페이지용)
_risk_sampler = None  # main()에서 연결됨 — record_risk_sample(risk_key) (안전점수용 위험 노출 시간 누적)
_last_imu_impact = False  # IMU 충격 경고음을 감지 "순간"에 한 번만 울리기 위한 이전 프레임 상태

# 개발자 모니터링 웹페이지용 (BGR)
RISK_COLORS = {
    "SAFE": (34, 197, 94),
    "CAUTION": (4, 138, 202),
    "WARNING": (12, 88, 234),
    "DANGER": (38, 38, 220),
}

# 아무도 보고 있지 않으면 영상 합성/인코딩을 건너뛰어 라즈베리파이 부하를 아낀다.
_video_viewers = 0
_video_viewers_lock = threading.Lock()
_frame_lock = threading.Lock()
_latest_jpeg = None


def _inc_viewers():
    global _video_viewers
    with _video_viewers_lock:
        _video_viewers += 1


def _dec_viewers():
    global _video_viewers
    with _video_viewers_lock:
        _video_viewers = max(0, _video_viewers - 1)


def _has_viewers():
    with _video_viewers_lock:
        return _video_viewers > 0


def describe_target(class_name, distance, ttc, in_collision_zone):
    if class_name in ("IMU_충돌", "IMU_전복"):
        return f"IMU 센서 감지 · {class_name.split('_', 1)[1]}"
    if class_name in ("초음파_좌측", "초음파_우측"):
        return f"초음파 센서 감지 · {class_name.split('_', 1)[1]} 근접 · {distance:.2f}m"
    zone_desc = "진행 경로 내" if in_collision_zone else "진행 경로 밖"
    if ttc is not None:
        return f"전방 {zone_desc} {class_name} 접근 · TTC {ttc:.1f}초 · {distance:.1f}m"
    return f"전방 {zone_desc} {class_name} 감지 · {distance:.1f}m"


def update_live_state(worst_target):
    if worst_target is None:
        risk_key, message = "SAFE", "위험 요소가 감지되지 않았어요."
        class_name = distance = ttc = None
        in_collision_zone = False
    else:
        risk_key = worst_target["risk"]
        message = describe_target(
            worst_target["class_name"], worst_target["distance"],
            worst_target["ttc"], worst_target["in_collision_zone"]
        )
        class_name = worst_target["class_name"]
        distance = worst_target["distance"]
        ttc = worst_target["ttc"]
        in_collision_zone = worst_target["in_collision_zone"]
    with _state_lock:
        _live_state["risk"] = risk_key.lower()
        _live_state["title"] = RISK_TITLES[risk_key]
        _live_state["message"] = message
        _live_state["class_name"] = class_name
        _live_state["distance_m"] = distance
        _live_state["ttc_sec"] = ttc
        _live_state["in_collision_zone"] = in_collision_zone


def get_live_state():
    with _state_lock:
        return dict(_live_state)


def mark_camera_offline():
    with _state_lock:
        _live_state["risk"] = "warning"
        _live_state["title"] = "카메라 연결 끊김"
        _live_state["message"] = "카메라 입력이 없어 위험 감지가 중단됐어요. 점검이 필요해요."
        _live_state["class_name"] = None
        _live_state["distance_m"] = None
        _live_state["ttc_sec"] = None
        _live_state["in_collision_zone"] = False


def enhance_low_light(frame_bgr):
    """평균 밝기가 낮으면 CLAHE로 명암 대비를 높여 야간 탐지를 보조한다."""
    gray = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2GRAY)
    if gray.mean() >= LOW_LIGHT_THRESHOLD:
        return frame_bgr
    lab = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2LAB)
    l_channel, a_channel, b_channel = cv2.split(lab)
    clahe = cv2.createCLAHE(clipLimit=2.5, tileGridSize=(8, 8))
    l_channel = clahe.apply(l_channel)
    return cv2.cvtColor(cv2.merge((l_channel, a_channel, b_channel)), cv2.COLOR_LAB2BGR)


# 실시간 영상 처리 (백그라운드 스레드에서 계속 실행)
def detection_loop(picam2, yolo_session, yolo_input_name, tracker):
    global _latest_jpeg, _last_imu_impact

    frame_count = 0
    camera_failure_count = 0
    last_online_targets = []
    collision_zone = None
    collision_zone_dims = None

    while True:
        start_time = time.time()

        frame = picam2.capture_array("main")  # Camera Module 3 실시간 입력
        if frame is None:
            camera_failure_count += 1
            print(f"❌ 카메라 프레임 없음 ({camera_failure_count}회 연속)")
            if camera_failure_count >= MAX_CAMERA_FAILURES:
                mark_camera_offline()
            time.sleep(0.1)
            continue
        camera_failure_count = 0

        frame = cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)
        frame_count += 1
        h_orig, w_orig = frame.shape[:2]
        raw_frame = enhance_low_light(frame)  # 어두우면 명암 대비 보정 (밝으면 frame을 그대로 반환, 복사 없음)
        display_frame = frame.copy() if _has_viewers() else None  # 보는 사람이 없으면 합성/인코딩 자체를 생략

        # =========================
        # YOLO 객체 탐지
        # =========================
        if frame_count % FRAME_SKIP == 0:  # Raspberry Pi 부하 감소
            scale = min(YOLO_SIZE / w_orig, YOLO_SIZE / h_orig)
            new_w = int(round(w_orig * scale))
            new_h = int(round(h_orig * scale))

            resized = cv2.resize(raw_frame, (new_w, new_h), interpolation=cv2.INTER_LINEAR)

            # 종횡비를 유지하는 Letterbox
            img_yolo = np.full((YOLO_SIZE, YOLO_SIZE, 3), 114, dtype=np.uint8)
            pad_x = (YOLO_SIZE - new_w) // 2
            pad_y = (YOLO_SIZE - new_h) // 2
            img_yolo[pad_y:pad_y + new_h, pad_x:pad_x + new_w] = resized
            img_yolo = cv2.cvtColor(img_yolo, cv2.COLOR_BGR2RGB)

            yolo_tensor = np.ascontiguousarray(
                img_yolo.transpose(2, 0, 1)[np.newaxis]
            ).astype(np.float32) / 255.0

            try:
                yolo_outputs = yolo_session.run(None, {yolo_input_name: yolo_tensor})
            except Exception as e:
                print(f"❌ YOLO 추론 오류: {e}")
                break

            predictions = np.squeeze(yolo_outputs[0]).T
            target_classes = {0, 1, 2, 3, 5, 7}
            boxes, confidences, class_ids = [], [], []

            for pred in predictions:
                scores = pred[4:]
                class_id = int(np.argmax(scores))
                confidence = float(scores[class_id])

                if class_id not in target_classes:
                    continue

                required_conf = 0.40 if class_id == 0 else 0.20  # 사람은 오탐 방지 위해 높게 설정
                if confidence <= required_conf:
                    continue

                cx, cy, w, h = pred[:4]

                # Letterbox 좌표 → 원본 영상 좌표
                x1 = int((cx - w / 2 - pad_x) / scale)
                y1 = int((cy - h / 2 - pad_y) / scale)
                bw = int(w / scale)
                bh = int(h / scale)

                x1 = max(0, min(x1, w_orig - 1))
                y1 = max(0, min(y1, h_orig - 1))
                bw = min(bw, w_orig - x1)
                bh = min(bh, h_orig - y1)

                if bw <= 0 or bh <= 0:
                    continue

                boxes.append([x1, y1, bw, bh])
                confidences.append(confidence)
                class_ids.append(class_id)

            # NMS로 중복 Bounding Box 제거
            tracker_inputs = []

            if boxes:
                indices = cv2.dnn.NMSBoxes(
                    boxes, confidences,
                    score_threshold=CONF_THRESHOLD,
                    nms_threshold=NMS_THRESHOLD
                )

                if len(indices) > 0:
                    for i in indices.flatten():
                        x, y, w, h = boxes[i]

                        if h < 20 or w < 10:  # 너무 작은 객체 제거
                            continue

                        tracker_inputs.append([
                            x, y, w, h,
                            confidences[i],
                            class_ids[i]
                        ])

            last_online_targets = tracker.update(tracker_inputs)  # 객체 ID 추적

            # 추적이 끝난 track_id의 거리 기록은 정리 (안 그러면 라이딩 내내 계속 쌓임)
            alive_ids = {t.track_id for t in tracker.tracked_stracks}
            for stale_id in list(distance_history.keys() - alive_ids):
                del distance_history[stale_id]
                del time_history[stale_id]

        # 위험도 판단
        current_speed_kmh = _speed_getter() if _speed_getter is not None else 0.0
        if (
            collision_zone is None
            or collision_zone_dims is None
            or collision_zone_dims[0] != w_orig
            or collision_zone_dims[1] != h_orig
            or abs(collision_zone_dims[2] - current_speed_kmh) >= 1.0  # 1km/h 이상 바뀔 때만 재계산
        ):
            collision_zone = get_collision_zone(w_orig, h_orig, current_speed_kmh)
            collision_zone_dims = (w_orig, h_orig, current_speed_kmh)

        stopping_distance = calculate_stopping_distance(current_speed_kmh)

        frame_worst_rank = -1
        frame_worst_target = None

        for target in last_online_targets:
            x1, y1, x2, y2 = map(int, target.bbox)

            x1 = max(0, min(x1, w_orig - 1))
            y1 = max(0, min(y1, h_orig - 1))
            x2 = max(0, min(x2, w_orig - 1))
            y2 = max(0, min(y2, h_orig - 1))

            h_box = y2 - y1
            cls_id = target.cls_id
            track_id = target.track_id
            class_name, real_h = CLASS_INFO.get(cls_id, ("미확인 객체", 1.5))

            if h_box > 0:
                distance = (real_h * FOCAL_LENGTH) / h_box  # ① 거리 추정
                current_time = time.time()

                update_distance_history(track_id, distance, current_time)  # ② 동일 객체 거리 기록

                approach_speed = calculate_approach_speed(track_id)  # ③ 접근속도 계산
                motion_state = get_motion_state(approach_speed)

                # 주차된 차 판단: 카메라로 계산한 접근속도가 내 킥보드 속도로 설명되는 범위
                # 안이면(자동차 자체는 안 움직이고 내가 다가가는 것뿐) TTC 기반 위험 판단에서 제외.
                # 거리 자체가 가까우면(정지 가능 거리 이내) 아래 최종 위험도 판단에서 여전히 위험으로 잡힘.
                is_stationary_car = (
                    cls_id == 2
                    and motion_state == "APPROACHING"
                    and approach_speed <= (current_speed_kmh / 3.6) + STATIONARY_MARGIN_MPS
                )

                ttc = None
                if motion_state == "APPROACHING" and not is_stationary_car:
                    ttc = calculate_ttc(distance, approach_speed)  # ④ TTC

                in_collision_zone = is_in_collision_zone(
                    x1, y1, x2, y2, collision_zone
                )  # ⑤ 실제 진행경로 안인지 판단

                final_risk = get_final_risk(distance, ttc, in_collision_zone, stopping_distance)  # ⑥ 최종 위험도

                if display_frame is not None:
                    color = RISK_COLORS[final_risk]
                    cv2.rectangle(display_frame, (x1, y1), (x2, y2), color, 2)
                    label = f"{class_name} {distance:.1f}m"
                    (tw, th), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 1)
                    label_y1 = max(0, y1 - th - 8)
                    cv2.rectangle(display_frame, (x1, label_y1), (x1 + tw + 6, y1), color, -1)
                    cv2.putText(display_frame, label, (x1 + 3, y1 - 5),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)

                rank = RISK_RANK[final_risk]
                if rank > frame_worst_rank:
                    frame_worst_rank = rank
                    frame_worst_target = {
                        "risk": final_risk,
                        "track_id": track_id,
                        "class_name": class_name,
                        "distance": distance,
                        "ttc": ttc,
                        "in_collision_zone": in_collision_zone,
                    }

        ultrasonic_risk, ultrasonic_side, ultrasonic_cm = ultrasonic_sensor.get_worst_side()
        if ultrasonic_risk != "SAFE" and RISK_RANK[ultrasonic_risk] > frame_worst_rank:
            frame_worst_rank = RISK_RANK[ultrasonic_risk]
            frame_worst_target = {
                "risk": ultrasonic_risk,
                "track_id": None,
                "class_name": f"초음파_{ultrasonic_side}",
                "distance": (ultrasonic_cm / 100.0) if ultrasonic_cm is not None else 0.0,
                "ttc": None,
                "in_collision_zone": True,
            }

        if display_frame is not None:
            cv2.polylines(display_frame, [collision_zone], True, (255, 255, 0), 2)
            ok, jpeg_buf = cv2.imencode(".jpg", display_frame, [cv2.IMWRITE_JPEG_QUALITY, 70])
            if ok:
                with _frame_lock:
                    _latest_jpeg = jpeg_buf.tobytes()

        imu_state = imu_sensor.get_imu_state()
        if imu_state.get("impact") and not _last_imu_impact:
            sound_impact_alarm()
        _last_imu_impact = imu_state.get("impact", False)

        if imu_state.get("impact") or imu_state.get("rollover"):
            frame_worst_target = {
                "risk": "DANGER",
                "track_id": None,
                "class_name": "IMU_충돌" if imu_state.get("impact") else "IMU_전복",
                "distance": 0.0,
                "ttc": None,
                "in_collision_zone": True,
            }

        update_live_state(frame_worst_target)

        current_risk_key = frame_worst_target["risk"] if frame_worst_target is not None else "SAFE"
        set_buzzer(current_risk_key)
        set_led(current_risk_key == "DANGER")

        if _risk_sampler is not None:
            _risk_sampler(current_risk_key.lower())

        if frame_worst_target is not None and _event_recorder is not None:
            worst_risk_key = frame_worst_target["risk"].lower()
            if worst_risk_key in ("warning", "danger"):
                _event_recorder(
                    worst_risk_key,
                    frame_worst_target["track_id"],
                    frame_worst_target["class_name"],
                    frame_worst_target["distance"],
                    frame_worst_target["ttc"],
                )

        # FPS 계산 (콘솔 디버그용으로만 남김 — 화면에 그릴 곳이 없어짐)
        elapsed_time = max(time.time() - start_time, 0.001)
        fps_list.append(1.0 / elapsed_time)
        fps = sum(fps_list) / len(fps_list)


# =========================
# 개발자용 실시간 모니터링 웹페이지 (Flask)
# 최종 사용자용이 아니라, 우리가 개발/테스트 중 카메라·위험도·IMU 상태를 눈으로 확인하기 위한 용도.
# =========================
app = Flask(__name__)

DASHBOARD_HTML = """<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="utf-8">
<title>PM ADAS 실시간 모니터링</title>
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body {
    background: #0B1220; color: #E5E7EB;
    font-family: -apple-system, "Apple SD Gothic Neo", "Malgun Gothic", sans-serif;
    min-height: 100vh; display: flex; flex-direction: column;
  }
  .titlebar {
    background: #16213A; border-bottom: 1px solid #26324A;
    text-align: center; padding: 18px; font-size: 20px; font-weight: 800; color: #fff;
  }
  .main { flex: 1; display: flex; gap: 16px; padding: 16px; }
  .video-panel {
    flex: 2; background: #000; border-radius: 12px; overflow: hidden;
    display: flex; align-items: center; justify-content: center; min-height: 480px;
  }
  .video-panel img { width: 100%; height: 100%; object-fit: contain; }
  .stats-panel { flex: 1; display: flex; flex-direction: column; gap: 10px; min-width: 260px; }
  .stat-card {
    background: #16213A; border: 1px solid #26324A; border-radius: 12px;
    padding: 14px 18px; display: flex; justify-content: space-between; align-items: center;
  }
  .stat-card .label { color: #9CA3AF; font-size: 13px; font-weight: 700; }
  .stat-card .value { font-size: 20px; font-weight: 800; color: #22D3EE; font-variant-numeric: tabular-nums; }
  .stat-card.risk-safe .value { color: #22C55E; }
  .stat-card.risk-caution .value { color: #CA8A04; }
  .stat-card.risk-warning .value { color: #EA580C; }
  .stat-card.risk-danger .value { color: #DC2626; }
  .stat-card .value.connected { color: #22C55E; }
  .stat-card .value.disconnected { color: #6B7280; }
  .stat-card .value.imu-alert { color: #DC2626; }
  .footer {
    background: #16213A; border-top: 1px solid #26324A;
    text-align: center; padding: 16px; font-size: 18px; font-weight: 800; color: #fff;
    font-variant-numeric: tabular-nums;
  }
  .footer .l { color: #9CA3AF; font-size: 13px; font-weight: 700; margin-right: 10px; }
</style>
</head>
<body>
  <div class="titlebar">PM ADAS 실시간 모니터링</div>
  <div class="main">
    <div class="video-panel"><img src="/video_feed" alt="카메라 영상"></div>
    <div class="stats-panel">
      <div class="stat-card"><span class="label">속도</span><span class="value" id="v-speed">0 km/h</span></div>
      <div class="stat-card"><span class="label">TTC</span><span class="value" id="v-ttc">-</span></div>
      <div class="stat-card" id="card-risk"><span class="label">위험도</span><span class="value" id="v-risk">SAFE</span></div>
      <div class="stat-card"><span class="label">IMU</span><span class="value" id="v-imu">-</span></div>
      <div class="stat-card"><span class="label">BLE</span><span class="value" id="v-ble">-</span></div>
    </div>
  </div>
  <div class="footer"><span class="l">주행시간</span><span id="v-elapsed">00:00:00</span></div>

<script>
function fmtElapsed(sec) {
  sec = Math.max(0, sec | 0);
  const h = String(Math.floor(sec / 3600)).padStart(2, "0");
  const m = String(Math.floor((sec % 3600) / 60)).padStart(2, "0");
  const s = String(sec % 60).padStart(2, "0");
  return `${h}:${m}:${s}`;
}

async function poll() {
  try {
    const res = await fetch("/api/dashboard_state");
    const data = await res.json();

    document.getElementById("v-speed").textContent = `${data.speed_kmh.toFixed(1)} km/h`;
    document.getElementById("v-ttc").textContent = data.ttc_sec != null ? `${data.ttc_sec.toFixed(1)} s` : "-";
    document.getElementById("v-risk").textContent = data.risk.toUpperCase();
    document.getElementById("v-imu").textContent = data.imu_status;
    document.getElementById("v-imu").className = "value " + (
      data.imu_status === "정상" ? "connected" :
      data.imu_status === "미연결" ? "disconnected" : "imu-alert"
    );
    document.getElementById("v-ble").textContent = data.ride_active ? "Connected" : "대기 중";
    document.getElementById("v-elapsed").textContent = fmtElapsed(data.elapsed_sec);

    const bleEl = document.getElementById("v-ble");
    bleEl.className = "value " + (data.ride_active ? "connected" : "disconnected");

    const riskCard = document.getElementById("card-risk");
    riskCard.className = "stat-card risk-" + data.risk;
  } catch (e) {
    // 파이 재시작 중 등 일시적 오류는 무시하고 다음 폴링에서 재시도
  }
}
setInterval(poll, 1000);
poll();
</script>
</body>
</html>
"""


@app.route("/")
def dashboard():
    return DASHBOARD_HTML


def _stream_frames():
    _inc_viewers()
    try:
        while True:
            with _frame_lock:
                jpeg = _latest_jpeg
            if jpeg is not None:
                yield (b"--frame\r\nContent-Type: image/jpeg\r\n\r\n" + jpeg + b"\r\n")
            time.sleep(0.05)
    finally:
        _dec_viewers()


@app.route("/video_feed")
def video_feed():
    return Response(_stream_frames(), mimetype="multipart/x-mixed-replace; boundary=frame")


@app.route("/api/dashboard_state")
def dashboard_state():
    state = get_live_state()
    speed_kmh = _speed_getter() if _speed_getter is not None else 0.0
    ride_status = _ble_server.get_ride_status() if _ble_server is not None else {"active": False, "elapsed_sec": 0}
    return jsonify({
        "risk": state["risk"],
        "message": state["message"],
        "speed_kmh": speed_kmh,
        "ttc_sec": state["ttc_sec"],
        "imu_status": imu_sensor.get_imu_status_label(),
        "ride_active": ride_status["active"],
        "elapsed_sec": ride_status["elapsed_sec"],
    })


# 카메라/모델/트래커 전역 핸들 (스레드 간 공유)
picam2 = None
yolo_session = None
yolo_input_name = None
tracker = None


# Main 코드
def main():
    global picam2, yolo_session, yolo_input_name, tracker, _event_recorder, _speed_getter, _ble_server, _risk_sampler

    print("1. 프로그램 시작됨...")
    yolo_onnx = "./yolov8n.onnx"

    # Camera Module 3 초기화
    picam2 = Picamera2()

    camera_config = picam2.create_video_configuration(
        main={"size": (640, 480), "format": "RGB888"},
        controls={"FrameRate": 30}
    )

    picam2.configure(camera_config)
    picam2.start()
    time.sleep(1.0)  # 카메라 자동 노출/초점 안정화 대기

    print("2. Camera Module 3 시작 완료!")

    # ONNX Runtime Raspberry Pi CPU 최적화
    opts = ort.SessionOptions()
    opts.intra_op_num_threads = 2
    opts.inter_op_num_threads = 1
    opts.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL

    try:
        yolo_session = ort.InferenceSession(
            yolo_onnx,
            sess_options=opts,
            providers=["CPUExecutionProvider"]
        )
        print("3. ONNX 모델 로드 완료!")

    except Exception as e:
        print(f"❌ ONNX 모델 로드 실패: {e}")
        picam2.stop()
        return

    yolo_input_name = yolo_session.get_inputs()[0].name

    tracker = SimpleByteTracker(
        track_thresh=0.45,
        match_thresh=0.45,
        max_lost_frames=MAX_LOST_FRAMES
    )

    detection_thread = threading.Thread(
        target=detection_loop,
        args=(picam2, yolo_session, yolo_input_name, tracker),
        daemon=True,
    )
    detection_thread.start()
    print("4. 감지 스레드 시작!")

    imu_thread = threading.Thread(target=imu_sensor.imu_reader_loop, daemon=True)
    imu_thread.start()
    print("5. IMU 사고 감지 스레드 시작!")

    try:
        ble_server = ble_peripheral.BlePeripheralServer(
            live_state_getter=get_live_state,
            imu_getter=imu_sensor.get_imu_state,
        )
        ble_thread = threading.Thread(target=ble_server.start, daemon=True)
        ble_thread.start()
        _event_recorder = ble_server.record_ride_event
        _speed_getter = ble_server.get_current_speed_kmh
        _ble_server = ble_server
        _risk_sampler = ble_server.record_risk_sample
        print("6. BLE 주변장치 스레드 시작! (앱에서 QR 스캔 후 연결, GPS는 폰에서 받음)")
    except Exception as e:
        print(f"⚠️  BLE 주변장치 시작 실패 — 폰 앱 연동 없이 카메라 감지만 동작합니다: {e}")

    print("🚀 준비 완료! http://<파이 IP>:5000 에서 실시간 모니터링 페이지를 볼 수 있습니다. (Ctrl+C로 종료)")

    try:
        app.run(host="0.0.0.0", port=5000, threaded=True, use_reloader=False)
    except KeyboardInterrupt:
        print("종료 신호 수신, 정리 중...")
    finally:
        if picam2 is not None:
            picam2.stop()


if __name__ == "__main__":
    main()