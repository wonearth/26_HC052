"""
FOCAL_LENGTH 실측용 1회성 스크립트.

사용법 (파이에서, app.py와 같은 폴더에서):
    python3 calibrate_focal_length.py --distance 2.0

동작:
  1. 카메라로 한 프레임을 찍는다.
  2. YOLO로 사람을 찾아 바운딩 박스 높이(px)를 잰다.
  3. FOCAL_LENGTH = (박스 높이 px * 실측 거리 m) / 사람 실제 키(m) 로 역산한다.
  4. 결과를 출력한다 — 그 값을 app.py의 FOCAL_LENGTH에 붙여넣으면 된다.

카메라 앞 지정한 거리에 사람이 정면으로, 전신이 다 나오게 서 있어야 정확하다.
여러 번(다른 거리에서) 재서 평균 내면 더 안정적이다.
"""
import argparse

import cv2
import numpy as np
import onnxruntime as ort
from picamera2 import Picamera2

YOLO_SIZE = 320
NMS_THRESHOLD = 0.45
PERSON_CLASS_ID = 0


def find_tallest_person_bbox(frame, session, input_name):
    h_orig, w_orig = frame.shape[:2]
    scale = min(YOLO_SIZE / w_orig, YOLO_SIZE / h_orig)
    new_w, new_h = int(round(w_orig * scale)), int(round(h_orig * scale))
    resized = cv2.resize(frame, (new_w, new_h), interpolation=cv2.INTER_LINEAR)

    img = np.full((YOLO_SIZE, YOLO_SIZE, 3), 114, dtype=np.uint8)
    pad_x, pad_y = (YOLO_SIZE - new_w) // 2, (YOLO_SIZE - new_h) // 2
    img[pad_y:pad_y + new_h, pad_x:pad_x + new_w] = resized
    img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
    tensor = np.ascontiguousarray(img.transpose(2, 0, 1)[np.newaxis]).astype(np.float32) / 255.0

    outputs = session.run(None, {input_name: tensor})
    predictions = np.squeeze(outputs[0]).T

    boxes, confidences = [], []
    for pred in predictions:
        scores = pred[4:]
        class_id = int(np.argmax(scores))
        confidence = float(scores[class_id])
        if class_id != PERSON_CLASS_ID or confidence <= 0.40:
            continue
        cx, cy, w, h = pred[:4]
        x1 = int((cx - w / 2 - pad_x) / scale)
        y1 = int((cy - h / 2 - pad_y) / scale)
        bw, bh = int(w / scale), int(h / scale)
        x1, y1 = max(0, x1), max(0, y1)
        bw, bh = min(bw, w_orig - x1), min(bh, h_orig - y1)
        if bw > 0 and bh > 0:
            boxes.append([x1, y1, bw, bh])
            confidences.append(confidence)

    if not boxes:
        return None

    indices = cv2.dnn.NMSBoxes(boxes, confidences, score_threshold=0.20, nms_threshold=NMS_THRESHOLD)
    if len(indices) == 0:
        return None

    best = max(indices.flatten(), key=lambda i: confidences[i])
    return boxes[best]


def main():
    parser = argparse.ArgumentParser(description="카메라 앞 실측 거리로 FOCAL_LENGTH를 역산")
    parser.add_argument("--distance", type=float, required=True, help="사람과 카메라 사이 실측 거리 (m)")
    parser.add_argument("--height", type=float, default=1.7, help="그 사람의 실제 키 (m), 기본 1.7")
    args = parser.parse_args()

    print("카메라 초기화 중...")
    picam2 = Picamera2()
    picam2.configure(picam2.create_video_configuration(main={"size": (640, 480), "format": "RGB888"}))
    picam2.start()
    import time
    time.sleep(1.0)

    print("YOLO 모델 로드 중...")
    session = ort.InferenceSession("./yolov8n.onnx", providers=["CPUExecutionProvider"])
    input_name = session.get_inputs()[0].name

    frame = picam2.capture_array("main")
    frame = cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)
    picam2.stop()

    bbox = find_tallest_person_bbox(frame, session, input_name)
    if bbox is None:
        print("❌ 사람을 못 찾았습니다. 카메라 정면에 전신이 나오게 서 있는지 확인하고 다시 시도하세요.")
        return

    _, _, bw, bbox_height_px = bbox
    focal_length = (bbox_height_px * args.distance) / args.height

    print(f"감지된 바운딩 박스 높이: {bbox_height_px}px")
    print(f"입력한 실측 거리: {args.distance}m, 키: {args.height}m")
    print(f"\n계산된 FOCAL_LENGTH = {focal_length:.1f}")
    print(f"\napp.py의 FOCAL_LENGTH = 524.0 를 아래처럼 바꿔주세요:")
    print(f"FOCAL_LENGTH = {focal_length:.1f}")


if __name__ == "__main__":
    main()
