# PM ADAS — 파이 ↔ 앱 BLE 통신 규약 (v1)

파이(BLE Peripheral)와 앱(BLE Central, React Native/Expo, 안드로이드)이 서로 다른 사람이
개발하기 때문에, 아래 규약대로만 맞추면 양쪽을 독립적으로 개발해도 나중에 바로 연결됨.

## 0. 역할

- **파이 = Peripheral (주변장치)**: BLE 광고(advertising)를 내보내고, GATT 서버 역할을 함.
- **앱 = Central (중심장치)**: 연결을 거는 쪽. QR로 얻은 파이의 MAC 주소로 직접 연결.

## 1. QR 코드 내용

각 파이의 BLE MAC 주소를 다음 포맷의 텍스트로 인코딩:

```
PMADAS:AA:BB:CC:DD:EE:FF
```

- `PMADAS:` 접두어로 다른 QR코드와 구분 (앱이 스캔 결과를 검증할 때 이 접두어 확인)
- 뒤에 오는 값은 파이의 실제 블루투스 MAC 주소 (콜론 구분, 대문자)
- 파이 MAC은 하드웨어 고유값이라 QR은 한 번만 만들어서 킥보드에 붙여두면 됨
  (파이에서 MAC 확인: `bluetoothctl show` 또는 `hciconfig`)

## 2. GATT 구조

**Service UUID** (이 프로젝트 전용, 고정값):
```
b4ecbebf-e498-4421-9b90-830fdef8c16a
```

| Characteristic | UUID | 속성 | 방향 |
|---|---|---|---|
| Control (제어) | `8ea73ee0-6fbd-4a5b-a121-e249ba53033a` | Write | 앱 → 파이 |
| Live Status (실시간 상태) | `0c3d0e6b-3de8-4ac5-9a23-30bd69cdfa2e` | Notify | 파이 → 앱 |
| Ride Data (주행기록 전송) | `10a90785-c204-4b26-aeac-56f0336b9f14` | Notify | 파이 → 앱 |

### 2-1. Control (제어) — 앱이 씀

1바이트 커맨드:

| 값 | 의미 |
|---|---|
| `0x01` | 주행 시작 — 파이는 GPS+이벤트 로컬 누적을 시작 |
| `0x02` | 주행 종료 — 파이는 누적을 멈추고, Ride Data characteristic으로 전체 기록을 청크 전송 시작 |

### 2-2. Live Status (실시간 상태) — 파이가 알림, 선택 기능

주행 중 위험 배너/경고음을 앱에서 실시간으로 보여주고 싶을 때만 사용. 안 쓰면 생략 가능
(파이 쪽에서 이 characteristic을 아예 구현 안 해도 나머지 흐름엔 영향 없음).

페이로드 (2바이트):
```
[0] risk_level   0=안전 1=주의 2=경고 3=위험
[1] event_flag   0=없음 1=새 위험 이벤트 발생
```

### 2-3. Ride Data (주행기록 전송) — 파이가 종료 후 청크로 전송

**청크 포맷** (각 notify 패킷):
```
[0-1] seq          청크 순번 (0부터, uint16 little-endian)
[2]   flag         0=중간 청크, 1=마지막 청크
[3..] payload      JSON 문자열을 UTF-8 바이트로 쪼갠 조각
```

- BLE 특성상 한 패킷 용량이 작음(MTU 협상에 따라 20~512바이트) → JSON 전체를 위 포맷으로 나눠 보냄
- 앱은 seq 순서대로 payload를 이어붙이고, flag=1인 청크를 받으면 전체를 합쳐 JSON.parse
- **재전송 규칙**: 앱이 일정 시간(예: 5초) 내 다음 seq를 못 받으면, Control characteristic에
  `0x02`(종료)를 다시 써서 파이에게 처음부터 재전송을 요청함. 파이는 매번 0x02를 받을 때마다
  현재 누적된 전체 데이터를 처음(seq=0)부터 다시 보냄 — 즉 앱 쪽에서 조립 실패 시 그냥
  "종료 버튼 다시 누르기"와 동일한 동작으로 재시도 가능.

## 3. 주행기록 JSON 스키마

```json
{
  "client_ride_uuid": "string (파이가 생성하는 라이딩 고유 ID, uuid4)",
  "started_at": "ISO8601 string",
  "ended_at": "ISO8601 string",
  "distance_km": 0.0,
  "duration_sec": 0,
  "avg_speed_kmh": 0.0,
  "max_speed_kmh": 0.0,
  "hard_brake_count": 0,
  "safety_score": 0,
  "points": [
    { "seq": 0, "lat": 0.0, "lng": 0.0, "recorded_at": "ISO8601", "risk_level": "안전" }
  ],
  "events": [
    {
      "occurred_at": "ISO8601",
      "risk_level": "위험",
      "object_class": "person",
      "distance_m": 0.0,
      "ttc_sec": 0.0,
      "lat": 0.0,
      "lng": 0.0
    }
  ]
}
```

- `risk_level`은 문자열 `"안전"/"주의"/"경고"/"위험"` 4단계 고정
- 필드명·단위는 위 스키마 그대로 고정 — 이후 앱/DB 쪽 파싱 코드가 이 스키마를 전제로 만들어짐

## 4. 연결 상태 규칙

- **시작 시점**: 앱-파이가 BLE로 연결되어 있어야 `0x01`(시작) 신호를 보낼 수 있음
- **주행 중**: 연결이 끊겨도 무방 — 파이는 자체적으로 GPS+이벤트를 계속 로컬에 누적함.
  연결 여부와 무관하게 동작해야 함 (파이 구현 시 이 부분이 핵심)
- **종료 시점**: 앱이 다시 파이와 BLE 연결(재연결, QR 재스캔 불필요 — 이미 아는 MAC으로
  바로 재연결)한 뒤 `0x02`(종료) 신호를 보내야 함. 파이는 이 시점에 누적을 멈추고 Ride Data
  전송을 시작

## 5. 안드로이드 참고사항

- BLE 스캔에는 안드로이드 OS 정책상 위치 권한이 필요함 (GPS 사용과 무관, OS 정책일 뿐)
- 앱은 QR에서 얻은 MAC으로 스캔 없이 바로 `connectGattToAddress` 형태로 연결 시도 가능
  (react-native-ble-plx 기준 `connectToDevice(mac)`)
