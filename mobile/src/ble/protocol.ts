// BLE_PROTOCOL.md 의 규약을 코드로 옮긴 상수들.
// 파이 쪽 GATT 서버 구현과 반드시 값이 일치해야 함.

export const SERVICE_UUID = "b4ecbebf-e498-4421-9b90-830fdef8c16a";

export const CHARACTERISTIC_CONTROL = "8ea73ee0-6fbd-4a5b-a121-e249ba53033a";
export const CHARACTERISTIC_LIVE_STATUS = "0c3d0e6b-3de8-4ac5-9a23-30bd69cdfa2e";
export const CHARACTERISTIC_RIDE_DATA = "10a90785-c204-4b26-aeac-56f0336b9f14";
export const CHARACTERISTIC_PHONE_GPS = "7d2f4b8e-1a63-4c91-9e52-6b7f3d8a2041";

export const CONTROL_START = 0x01;
export const CONTROL_STOP = 0x02;

export const QR_PREFIX = "PMADAS:";

export const RISK_LEVEL_BY_CODE = ["안전", "주의", "경고", "위험"] as const;

/** QR 스캔 결과 문자열에서 파이의 BLE MAC 주소를 뽑아낸다. 형식이 아니면 null. */
export function parsePiMacFromQr(raw: string): string | null {
  const trimmed = raw.trim();
  if (!trimmed.startsWith(QR_PREFIX)) return null;
  const mac = trimmed.slice(QR_PREFIX.length).trim().toUpperCase();
  const macPattern = /^([0-9A-F]{2}:){5}[0-9A-F]{2}$/;
  return macPattern.test(mac) ? mac : null;
}
