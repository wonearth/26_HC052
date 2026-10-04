"""
센서별 위험 판단을 모아 최종 위험도를 정하고, 부저/LED/앱/기록으로 내보내는 중재자.

왜 따로 있나: 예전엔 이 일이 카메라 프레임 루프 안에 있어서, 카메라 스레드가 죽거나 멈추면
레이더/초음파/IMU가 멀쩡해도 부저와 LED까지 같이 멈췄다. 지금은
  - 카메라는 "내 위험 단계 + 시각"만 publish_camera()로 올리고,
  - 초음파/레이더/IMU는 중재자가 직접 읽고,
  - 최종 판단과 모든 출력(부저/LED/앱/기록)은 이 중재 스레드 하나가 맡는다.
어느 한 센서가 예외를 내거나 멈춰도 나머지로 계속 판단하고 출력한다.

하드웨어를 직접 import하지 않고 함수(콜백)로만 주입받기 때문에 Mac에서 가짜 센서로 시험할 수 있다.
"""
import threading
import time

RISK_RANK = {"SAFE": 0, "CAUTION": 1, "WARNING": 2, "DANGER": 3}

TICK_SEC = 0.05            # 최종 판단 주기 — 반응 시간 가정(0.7초)에 비해 무시할 수준
CAMERA_STALE_SEC = 1.5     # 이 시간 넘게 카메라 값이 안 오면 "카메라 정보 없음"으로 처리
STARTUP_GRACE_SEC = 10.0   # 부팅 직후 첫 프레임이 오기 전까지는 "카메라 끊김"으로 보지 않음
LOG_INTERVAL_SEC = 10.0    # 같은 오류 로그는 이 간격으로만 출력 (20Hz로 도배 방지)


class RiskArbiter:
    def __init__(
        self, *,
        speed_getter,          # () -> km/h
        stopping_distance_fn,  # (speed_kmh) -> m
        risk_fn,               # (distance, ttc, in_zone, stopping_distance) -> "SAFE".."DANGER"
        ultrasonic_fn,         # () -> (risk, side, distance_cm)
        radar_fn,              # () -> {distance_m, ttc_sec, in_path} | None
        imu_fn,                # () -> {impact, rollover, ...}
        on_state,              # (target | None)
        on_camera_offline,     # () — 카메라 정보가 없고 다른 위험도 없을 때 "연결 끊김" 안내
        on_buzzer,             # (risk_key)
        on_led,                # (bool)
        on_impact_alarm,       # () — IMU 충격 감지 "순간"에 한 번
        on_sample,             # (risk_key_lower) — 안전점수용
        on_event,              # (risk_key_lower, track_id, class_name, distance, ttc)
        log=print,
    ):
        self._speed_getter = speed_getter
        self._stopping_distance_fn = stopping_distance_fn
        self._risk_fn = risk_fn
        self._ultrasonic_fn = ultrasonic_fn
        self._radar_fn = radar_fn
        self._imu_fn = imu_fn
        self._on_state = on_state
        self._on_camera_offline = on_camera_offline
        self._on_buzzer = on_buzzer
        self._on_led = on_led
        self._on_impact_alarm = on_impact_alarm
        self._on_sample = on_sample
        self._on_event = on_event
        self._log = log

        self._lock = threading.Lock()
        self._camera_target = None
        self._camera_at = 0.0
        self._created_at = time.monotonic()
        self._last_impact = False
        self._last_log_at = {}

    # ---- 카메라 쪽이 호출 ----
    def publish_camera(self, target):
        """카메라 한 프레임의 가장 위험한 대상(dict) 또는 None(위험 대상 없음)."""
        with self._lock:
            self._camera_target = target
            self._camera_at = time.monotonic()

    # ---- 내부 ----
    def _warn(self, name, error):
        now = time.monotonic()
        if now - self._last_log_at.get(name, 0.0) >= LOG_INTERVAL_SEC:
            self._last_log_at[name] = now
            self._log(f"⚠️  중재자: {name} 오류 — 이 센서 없이 계속 판단합니다: {error!r}")

    def _safe(self, name, fn, default):
        try:
            return fn()
        except Exception as e:
            self._warn(name, e)
            return default

    def _call(self, name, fn, *args):
        try:
            fn(*args)
        except Exception as e:
            self._warn(f"출력({name})", e)

    def _camera_state(self, now):
        with self._lock:
            target, at = self._camera_target, self._camera_at
        fresh = at > 0.0 and (now - at) <= CAMERA_STALE_SEC
        offline = (not fresh) and (at > 0.0 or (now - self._created_at) > STARTUP_GRACE_SEC)
        return (target if fresh else None), offline

    # ---- 한 번의 판단 ----
    def tick(self):
        now = time.monotonic()
        speed = self._safe("속도", self._speed_getter, 0.0)
        stopping = self._safe("정지거리", lambda: self._stopping_distance_fn(speed), 0.0)

        worst, camera_offline = self._camera_state(now)
        rank = RISK_RANK[worst["risk"]] if worst else -1

        # 초음파: 카메라보다 "더 높을 때만" 덮어씀 (기존과 같은 규칙)
        us = self._safe("초음파", self._ultrasonic_fn, None)
        if us:
            us_risk, us_side, us_cm = us
            if us_risk != "SAFE" and RISK_RANK[us_risk] > rank:
                rank = RISK_RANK[us_risk]
                worst = {
                    "risk": us_risk, "track_id": None, "class_name": f"초음파_{us_side}",
                    "distance": (us_cm / 100.0) if us_cm is not None else 0.0,
                    "ttc": None, "in_collision_zone": True,
                }

        # 레이더: 카메라와 같은 get_final_risk 기준을 써서 임계값이 두 벌이 되지 않게 함
        radar = self._safe("레이더", self._radar_fn, None)
        if radar:
            radar_risk = self._safe(
                "레이더 위험도",
                lambda: self._risk_fn(radar["distance_m"], radar["ttc_sec"], radar["in_path"], stopping),
                "SAFE",
            )
            if radar_risk != "SAFE" and RISK_RANK[radar_risk] > rank:
                rank = RISK_RANK[radar_risk]
                worst = {
                    "risk": radar_risk, "track_id": None, "class_name": "레이더_전방",
                    "distance": radar["distance_m"], "ttc": radar["ttc_sec"],
                    "in_collision_zone": radar["in_path"],
                }

        # IMU: 최상위 — 충격은 순간에 한 번 경고음, 충격/전복이면 무조건 DANGER
        imu = self._safe("IMU", self._imu_fn, {}) or {}
        impact = bool(imu.get("impact"))
        if impact and not self._last_impact:
            self._call("충격 경고음", self._on_impact_alarm)
        self._last_impact = impact
        if impact or imu.get("rollover"):
            worst = {
                "risk": "DANGER", "track_id": None,
                "class_name": "IMU_충돌" if impact else "IMU_전복",
                "distance": 0.0, "ttc": None, "in_collision_zone": True,
            }

        risk_key = worst["risk"] if worst else "SAFE"

        # 출력: 각각 독립적으로 실행 — 하나가 실패해도 나머지는 그대로 나감
        if worst is None and camera_offline:
            self._call("카메라 끊김 안내", self._on_camera_offline)
        else:
            self._call("상태", self._on_state, worst)
        self._call("부저", self._on_buzzer, risk_key)
        self._call("LED", self._on_led, risk_key == "DANGER")
        self._call("점수 샘플", self._on_sample, risk_key.lower())
        if worst is not None and risk_key in ("WARNING", "DANGER"):
            self._call(
                "기록", self._on_event, risk_key.lower(),
                worst["track_id"], worst["class_name"], worst["distance"], worst["ttc"],
            )

        return {"target": worst, "risk": risk_key, "camera_offline": camera_offline}

    def run(self):
        """중재 스레드 본체. 어떤 예외가 나도 이 루프는 계속 돈다."""
        while True:
            try:
                self.tick()
            except Exception as e:
                self._warn("중재 루프", e)
            time.sleep(TICK_SEC)
