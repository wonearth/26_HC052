import type { RawRideEvent, RideEvent, RidePoint } from "../types/ride";

/**
 * 파이가 보낸 이벤트(위치 없음)에, 발생 시각과 제일 가까운 폰의 GPS 포인트를 찾아
 * 위치를 붙인다. 실시간으로 위치를 몰라도 종료 후 시각 기준으로 짝을 맞추면 됨
 * (BLE_PROTOCOL.md 3-3 참고).
 */
export function attachLocationToEvents(events: RawRideEvent[], points: RidePoint[]): RideEvent[] {
  if (points.length === 0) {
    return events.map((event) => ({ ...event, lat: 0, lng: 0 }));
  }

  const pointTimes = points.map((p) => new Date(p.recorded_at).getTime());

  return events.map((event) => {
    const eventTime = new Date(event.occurred_at).getTime();
    let closestIndex = 0;
    let closestDiff = Infinity;
    for (let i = 0; i < pointTimes.length; i++) {
      const diff = Math.abs(pointTimes[i] - eventTime);
      if (diff < closestDiff) {
        closestDiff = diff;
        closestIndex = i;
      }
    }
    const closest = points[closestIndex];
    return { ...event, lat: closest.lat, lng: closest.lng };
  });
}
