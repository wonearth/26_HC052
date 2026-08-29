import type { RideEvent, RidePayload, RidePoint, RiskLevel } from "../types/ride";

/** 파이/BLE 하드웨어 없이 앱 UI·저장·시각화를 검증하기 위한 더미 라이딩 데이터. */
export function generateMockRide(): RidePayload {
  const now = new Date();
  const startedAt = new Date(now.getTime() - 12 * 60 * 1000);

  const baseLat = 37.5665;
  const baseLng = 126.978;
  const riskLevels: RiskLevel[] = ["안전", "안전", "안전", "주의", "안전", "경고", "안전"];

  const points: RidePoint[] = Array.from({ length: 40 }, (_, i) => ({
    seq: i,
    lat: baseLat + i * 0.0006 + Math.sin(i / 5) * 0.0004,
    lng: baseLng + i * 0.0008,
    recorded_at: new Date(startedAt.getTime() + i * 18000).toISOString(),
    risk_level: riskLevels[i % riskLevels.length],
  }));

  const events: RideEvent[] = [
    {
      occurred_at: new Date(startedAt.getTime() + 4 * 60000).toISOString(),
      risk_level: "경고",
      object_class: "person",
      distance_m: 3.2,
      ttc_sec: 1.8,
      lat: points[15].lat,
      lng: points[15].lng,
    },
    {
      occurred_at: new Date(startedAt.getTime() + 8 * 60000).toISOString(),
      risk_level: "위험",
      object_class: "bicycle",
      distance_m: 1.5,
      ttc_sec: 0.9,
      lat: points[28].lat,
      lng: points[28].lng,
    },
  ];

  return {
    client_ride_uuid: `mock-${Date.now()}`,
    started_at: startedAt.toISOString(),
    ended_at: now.toISOString(),
    distance_km: 2.4,
    duration_sec: 12 * 60,
    avg_speed_kmh: 14.5,
    max_speed_kmh: 27.3,
    hard_brake_count: 2,
    safety_score: 82,
    points,
    events,
  };
}
