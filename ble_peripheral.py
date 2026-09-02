"""
파이를 BLE 주변장치(Peripheral/GATT 서버)로 만들어 앱과 통신한다.
BLE_PROTOCOL.md(v2)의 서비스/캐릭터리스틱 규약을 그대로 구현.

v2: GPS는 폰이 직접 기록한다. 파이는 카메라 위험 이벤트만 시각과 함께 기록해서
종료 시 넘겨주고, 앱이 자기 GPS 기록과 시각을 맞춰서 최종 데이터를 합친다.
(예전엔 폰 GPS를 실시간으로 파이에 계속 전송했는데, 블루투스가 끊기면 그 구간
경로가 통째로 비는 문제가 있어서 이 방식으로 바꿈 — BLE_PROTOCOL.md 상단 참고)

필요 패키지 (파이에서 미리 설치):
    sudo apt install bluetooth bluez
    pip3 install bluezero

주의:
- 이 모듈은 macOS/일반 PC에서는 동작하지 않는다 (BlueZ/D-Bus가 있는 라즈베리파이 OS 전용).
- bluezero 버전에 따라 add_characteristic()의 콜백 시그니처나 adapter 조회 방식이
  조금씩 다를 수 있다. 아래 코드가 설치된 버전과 안 맞으면 bluezero 공식 예제
  (https://github.com/ukBaz/python-bluezero/tree/main/examples)를 참고해서 맞춰야 한다.
"""
import json
import threading
import time
import uuid as uuid_lib
from datetime import datetime, timezone

try:
    from bluezero import adapter, peripheral
    _BLUEZERO_AVAILABLE = True
except ImportError:
    _BLUEZERO_AVAILABLE = False

# BLE_PROTOCOL.md 와 반드시 값이 일치해야 함
SERVICE_UUID = "b4ecbebf-e498-4421-9b90-830fdef8c16a"
CHAR_CONTROL_UUID = "8ea73ee0-6fbd-4a5b-a121-e249ba53033a"
CHAR_LIVE_STATUS_UUID = "0c3d0e6b-3de8-4ac5-9a23-30bd69cdfa2e"
CHAR_RIDE_DATA_UUID = "10a90785-c204-4b26-aeac-56f0336b9f14"

CONTROL_START = 0x01
CONTROL_STOP = 0x02

CHUNK_PAYLOAD_SIZE = 150       # 청크당 payload 바이트 수 (MTU 여유를 둔 보수적인 값)
LIVE_STATUS_INTERVAL_SEC = 2.0  # 실시간 위험도 notify 주기
EVENT_COOLDOWN_SEC = 3.0       # 같은 대상이 연속으로 이벤트를 계속 만들지 않도록 최소 간격

RISK_TO_KOREAN = {"safe": "안전", "caution": "주의", "warning": "경고", "danger": "위험"}
# web/app.py의 _compute_safety_score()와 동일한 감점 기준 (일관성 유지)
SAFETY_PENALTY = {"위험": 15, "경고": 8, "주의": 3, "안전": 0}


class RideSession:
    """주행 시작~종료 동안 카메라 위험 이벤트를 누적하고, 종료 시 하나의 JSON으로 요약한다."""

    def __init__(self):
        self._lock = threading.Lock()
        self._active = False
        self._reset()

    def _reset(self):
        self._client_ride_uuid = None
        self._started_at = None
        self._events = []
        self._last_event_at = {}

    def start(self):
        with self._lock:
            self._reset()
            self._active = True
            self._client_ride_uuid = str(uuid_lib.uuid4())
            self._started_at = datetime.now(timezone.utc)

    def is_active(self):
        with self._lock:
            return self._active

    def record_event(self, risk_key, object_class, distance_m, ttc_sec):
        """risk_key는 safe/caution/warning/danger. 위치는 안 담음 — 앱이 시각 기준으로 붙임."""
        with self._lock:
            if not self._active:
                return
            risk_level = RISK_TO_KOREAN.get(risk_key, "위험")
            now = time.monotonic()
            key = object_class or "unknown"
            last = self._last_event_at.get(key, 0)
            if now - last < EVENT_COOLDOWN_SEC:
                return
            self._last_event_at[key] = now
            self._events.append({
                "occurred_at": datetime.now(timezone.utc).isoformat(),
                "risk_level": risk_level,
                "object_class": key,
                "distance_m": distance_m if distance_m is not None else 0.0,
                "ttc_sec": ttc_sec if ttc_sec is not None else 0.0,
            })

    def stop_and_package(self):
        """활성 라이딩이 없으면 None. 있으면 종료 처리하고 BLE_PROTOCOL.md 스키마의 dict를 반환."""
        with self._lock:
            if self._client_ride_uuid is None:
                return None
            self._active = False
            ended_at = datetime.now(timezone.utc)
            duration_sec = max(0, int((ended_at - self._started_at).total_seconds()))
            penalty = sum(SAFETY_PENALTY.get(e["risk_level"], 0) for e in self._events)
            safety_score = max(0, 100 - penalty)

            return {
                "client_ride_uuid": self._client_ride_uuid,
                "started_at": self._started_at.isoformat(),
                "ended_at": ended_at.isoformat(),
                "duration_sec": duration_sec,
                "safety_score": safety_score,
                "events": self._events,
            }


class BlePeripheralServer:
    """
    live_state_getter: () -> dict   # app.py의 get_live_state()와 동일한 형태
        {"risk": "safe"|"caution"|"warning"|"danger", "class_name":..., "distance_m":..., "ttc_sec":...}
    """

    def __init__(self, live_state_getter, local_name="PM-ADAS-Pi"):
        if not _BLUEZERO_AVAILABLE:
            raise RuntimeError("bluezero가 설치되어 있지 않습니다 (pip3 install bluezero)")
        self._live_state_getter = live_state_getter
        self._local_name = local_name
        self._session = RideSession()
        self._periph = None
        self._live_thread = None
        self._stop_live = threading.Event()

    def _on_control_write(self, value, options=None):
        command = value[0] if value else None
        if command == CONTROL_START:
            print("▶️  BLE: 주행 시작 신호 수신")
            self._session.start()
            self._start_live_loop()
        elif command == CONTROL_STOP:
            print("⏹  BLE: 주행 종료 신호 수신")
            self._stop_live_loop()
            payload = self._session.stop_and_package()
            if payload is not None:
                self._send_ride_data(payload)
            else:
                print("⚠️  종료 신호를 받았지만 진행 중이던 라이딩이 없습니다 (재전송 요청일 수 있음)")

    def _start_live_loop(self):
        self._stop_live.clear()
        self._live_thread = threading.Thread(target=self._live_loop, daemon=True)
        self._live_thread.start()

    def _stop_live_loop(self):
        self._stop_live.set()
        if self._live_thread is not None:
            self._live_thread.join(timeout=2)

    def _live_loop(self):
        """주행 중 카메라 위험도를 주기적으로 확인 — 이벤트 기록 + 실시간 상태 알림."""
        while not self._stop_live.is_set() and self._session.is_active():
            state = self._live_state_getter() or {}
            risk_key = state.get("risk", "safe")

            if risk_key in ("warning", "danger"):
                self._session.record_event(
                    risk_key,
                    state.get("class_name"),
                    state.get("distance_m"),
                    state.get("ttc_sec"),
                )

            self._update_live_status_characteristic(risk_key)
            time.sleep(LIVE_STATUS_INTERVAL_SEC)

    def _update_live_status_characteristic(self, risk_key):
        rank = {"safe": 0, "caution": 1, "warning": 2, "danger": 3}.get(risk_key, 0)
        try:
            self._periph.characteristics[1].set_value([rank, 0])
        except Exception as e:
            print(f"⚠️  실시간 상태 알림 실패: {e}")

    def _send_ride_data(self, payload):
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        chunks = [data[i:i + CHUNK_PAYLOAD_SIZE] for i in range(0, len(data), CHUNK_PAYLOAD_SIZE)] or [b""]
        total = len(chunks)
        for seq, chunk in enumerate(chunks):
            is_last = 1 if seq == total - 1 else 0
            packet = bytes([seq & 0xFF, (seq >> 8) & 0xFF, is_last]) + chunk
            try:
                self._periph.characteristics[2].set_value(list(packet))
            except Exception as e:
                print(f"❌ 주행기록 전송 실패(chunk {seq}/{total}): {e}")
                return
            time.sleep(0.02)  # 청크 사이 살짝 텀 (BLE 스택 과부하 방지)
        print(f"✅ 주행기록 전송 완료 ({total}개 청크, {len(data)} bytes)")

    def start(self):
        """블루투스 GATT 서버를 시작한다. publish()는 블로킹 호출이라 별도 스레드에서 실행할 것."""
        adapters = list(adapter.Adapter.available())
        if not adapters:
            raise RuntimeError("사용 가능한 블루투스 어댑터를 찾을 수 없습니다")
        adapter_address = adapters[0].address

        self._periph = peripheral.Peripheral(adapter_address, local_name=self._local_name)
        self._periph.add_service(srv_id=1, uuid=SERVICE_UUID, primary=True)

        self._periph.add_characteristic(
            srv_id=1, chr_id=1, uuid=CHAR_CONTROL_UUID,
            value=[], notifying=False,
            flags=["write"],
            write_callback=self._on_control_write,
        )
        self._periph.add_characteristic(
            srv_id=1, chr_id=2, uuid=CHAR_LIVE_STATUS_UUID,
            value=[0, 0], notifying=False,
            flags=["notify"],
        )
        self._periph.add_characteristic(
            srv_id=1, chr_id=3, uuid=CHAR_RIDE_DATA_UUID,
            value=[], notifying=False,
            flags=["notify"],
        )

        print(f"📡 BLE 주변장치 시작: {self._local_name} ({adapter_address})")
        self._periph.publish()  # 블로킹 — GLib 메인루프 실행
