"""
레이더 점 목록에서 "전방에서 다가오는 대상 하나"를 뽑아 radar_sensor에 넘긴다 (전방 대상 추출).

흐름: 점 필터(진행 복도 + 거리 범위) → 가장 가까운 대상 주변을 한 덩어리로 묶음 → 연속 N프레임 지속돼야 인정
      → 중앙값 필터로 떨림 제거 → 거리/접근속도/좌우위치를 update_target()으로 전달.

!! 아래 숫자들은 합성 데이터로 정한 초기값이다. 실제 레이더 로그(tools/radar_probe.py로 저장)를 재생해서
!! 맞춰야 한다. 특히 VELOCITY_APPROACH_SIGN은 실물에서 사람이 다가가 보고 반드시 확인할 것.
좌표: x = 좌우(+오른쪽), y = 전방, z = 위 (TI 데모 기준 가정).
"""
import statistics
from collections import deque

import radar_sensor

# --- 점 필터 ---
MIN_RANGE_M = 0.5
MAX_RANGE_M = 25.0
CORRIDOR_HALF_WIDTH_M = radar_sensor.CORRIDOR_HALF_WIDTH_M  # 진행 복도 폭은 한 곳에서만 정의
MIN_SNR_DB = None            # 이 값 미만의 약한 점은 버림. None이면 SNR 필터 안 함 (실데이터 보고 결정)

# --- 덩어리 묶기 ---
CLUSTER_RANGE_TOL_M = 1.0    # 가장 가까운 점과 이 거리 이내의 점은 같은 대상으로 봄
CLUSTER_LATERAL_TOL_M = 1.0
MIN_CLUSTER_POINTS = 1

# --- 지속/안정화 ---
CONFIRM_FRAMES = 3           # 연속 이만큼 잡혀야 인정 (한 프레임짜리 노이즈/노면 반사 제거)
MISS_TOLERANCE_FRAMES = 1    # 인정된 대상이 이만큼은 놓쳐도 유지(코스팅)
MAX_RANGE_JUMP_M = 3.0       # 프레임 사이에 이보다 크게 튀면 다른 대상/노이즈로 보고 지속 카운트 초기화
SMOOTH_WINDOW = 5            # 중앙값 필터 길이

# --- 속도 ---
VELOCITY_APPROACH_SIGN = -1.0   # 다가올 때 레이더가 주는 속도의 부호 (TI 기본은 다가오면 음수로 가정 — 실물 확인!)
IGNORE_RECEDING_BELOW_MPS = -0.5  # 접근속도가 이보다 작으면(멀어지는 중) 충돌 위험으로 보지 않고 제외


def _median(values):
    return statistics.median(values)


class ForwardTargetExtractor:
    def __init__(self):
        self._reset()

    def _reset(self):
        self._streak = 0
        self._misses = 0
        self._confirmed = False
        self._last_range = None
        self._history = deque(maxlen=SMOOTH_WINDOW)

    def _candidate(self, points):
        forward = [
            p for p in points
            if p["y"] > 0
            and MIN_RANGE_M <= p["range_m"] <= MAX_RANGE_M
            and abs(p["x"]) <= CORRIDOR_HALF_WIDTH_M
            and (MIN_SNR_DB is None or p.get("snr_db") is None or p["snr_db"] >= MIN_SNR_DB)
        ]
        if not forward:
            return None
        nearest = min(forward, key=lambda p: p["range_m"])
        cluster = [
            p for p in forward
            if abs(p["range_m"] - nearest["range_m"]) <= CLUSTER_RANGE_TOL_M
            and abs(p["x"] - nearest["x"]) <= CLUSTER_LATERAL_TOL_M
        ]
        if len(cluster) < MIN_CLUSTER_POINTS:
            return None
        closing = _median([p["v"] for p in cluster]) * VELOCITY_APPROACH_SIGN
        if closing < IGNORE_RECEDING_BELOW_MPS:
            return None  # 멀어지는 대상(앞서 가는 차 등)은 충돌 위험 대상이 아님
        return {
            "range_m": _median([p["range_m"] for p in cluster]),
            "lateral_m": _median([p["x"] for p in cluster]),
            "closing_mps": closing,
        }

    def _output(self):
        return {
            "distance_m": _median([h["range_m"] for h in self._history]),
            "lateral_m": _median([h["lateral_m"] for h in self._history]),
            "closing_speed_mps": _median([h["closing_mps"] for h in self._history]),
        }

    def process(self, points):
        """프레임 하나의 점 목록을 처리. 인정된 대상이 있으면 dict, 없으면 None."""
        cand = self._candidate(points)
        if cand is None:
            self._misses += 1
            if self._misses > MISS_TOLERANCE_FRAMES:
                self._reset()
                return None
            return self._output() if self._confirmed else None

        if self._last_range is not None and abs(cand["range_m"] - self._last_range) > MAX_RANGE_JUMP_M:
            self._reset()  # 다른 대상이거나 노이즈 — 처음부터 다시 세어서 인정받아야 함
        self._misses = 0
        self._streak += 1
        self._last_range = cand["range_m"]
        self._history.append(cand)
        if self._streak >= CONFIRM_FRAMES:
            self._confirmed = True
        return self._output() if self._confirmed else None


_extractor = ForwardTargetExtractor()


def handle_frame(parsed):
    """radar_reader.on_frame에 연결하는 함수: 프레임마다 전방 대상을 갱신하거나 지운다."""
    target = _extractor.process(parsed["points"])
    if target is None:
        radar_sensor.clear_target()
    else:
        radar_sensor.update_target(target["distance_m"], target["closing_speed_mps"], target["lateral_m"])
