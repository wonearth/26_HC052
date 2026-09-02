const LABELS: Record<string, string> = {
  impact: "충돌 감지",
  rollover: "전복 감지",
};

/** IMU 이벤트는 한글로, 카메라가 인식한 객체(person, bicycle 등)는 그대로 보여준다. */
export function formatObjectClass(objectClass: string): string {
  return LABELS[objectClass] ?? objectClass;
}
