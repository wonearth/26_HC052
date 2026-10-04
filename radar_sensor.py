"""
전방 레이더(TI AWR6843ISK) 인터페이스.

이 모듈은 "레이더가 찾은 전방 대상"을 app.py 쪽에 넘기는 입구만 담당한다.
실제 시리얼 읽기/TLV 파싱은 레이더 브링업 후 별도 스레드로 추가하고, 그 스레드가
update_target()만 호출하면 알림/기록/위험도 융합은 그대로 동작한다.

    update_target(distance_m, closing_speed_mps, lateral_m)  # 레이더 읽기 쪽만 호출 (시험 코드는 tests/ 에만 있음)
    get_forward_target()                                     # app.py 쪽 — 없거나 오래됐으면 None
"""
import threading
import time

TARGET_STALE_SEC = 0.5        # 이 시간 넘게 갱신이 없으면 "대상 없음" (센서 끊김/대상 사라짐 모두 안전하게 처리)
CORRIDOR_HALF_WIDTH_M = 1.0   # 진행 경로로 보는 좌우 폭 (킥보드 기준, 실측 후 조정)
MIN_APPROACH_SPEED = 0.3      # 이보다 느리게 다가오면 TTC를 계산하지 않음 (app.py와 동일 기준)

_lock = threading.Lock()
_target = None
_updated_at = 0.0


def update_target(distance_m, closing_speed_mps, lateral_m=0.0):
    """closing_speed_mps는 양수가 "가까워지는 중". 레이더 읽기 스레드가 프레임마다 호출."""
    global _target, _updated_at
    with _lock:
        _target = {
            "distance_m": float(distance_m),
            "closing_speed_mps": float(closing_speed_mps),
            "lateral_m": float(lateral_m),
        }
        _updated_at = time.monotonic()


def clear_target():
    global _target
    with _lock:
        _target = None


def get_forward_target():
    """{distance_m, closing_speed_mps, ttc_sec, in_path} 또는 None."""
    with _lock:
        if _target is None or time.monotonic() - _updated_at > TARGET_STALE_SEC:
            return None
        target = dict(_target)

    closing = target["closing_speed_mps"]
    target["ttc_sec"] = target["distance_m"] / closing if closing > MIN_APPROACH_SPEED else None
    target["in_path"] = abs(target["lateral_m"]) <= CORRIDOR_HALF_WIDTH_M
    return target
