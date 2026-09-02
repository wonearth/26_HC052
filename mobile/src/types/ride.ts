export type RiskLevel = "안전" | "주의" | "경고" | "위험";

export interface RidePoint {
  seq: number;
  lat: number;
  lng: number;
  recorded_at: string;
  risk_level: RiskLevel;
}

export interface RideEvent {
  occurred_at: string;
  risk_level: RiskLevel;
  object_class: string;
  distance_m: number;
  ttc_sec: number;
  lat: number;
  lng: number;
}

export interface RidePayload {
  client_ride_uuid: string;
  started_at: string;
  ended_at: string;
  distance_km: number;
  duration_sec: number;
  avg_speed_kmh: number;
  max_speed_kmh: number;
  hard_brake_count: number;
  safety_score: number;
  points: RidePoint[];
  events: RideEvent[];
}

export interface RideSummary {
  id: number;
  client_ride_uuid: string;
  started_at: string;
  ended_at: string;
  distance_km: number;
  duration_sec: number;
  avg_speed_kmh: number;
  max_speed_kmh: number;
  hard_brake_count: number;
  safety_score: number;
}
