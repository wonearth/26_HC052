import * as Location from "expo-location";
import type { RidePoint, RiskLevel } from "../types/ride";

const HARD_BRAKE_DELTA_KMH = 12.0;
const HARD_BRAKE_MIN_SPEED_KMH = 8.0;

export interface GpsSummary {
  points: RidePoint[];
  distance_km: number;
  avg_speed_kmh: number;
  max_speed_kmh: number;
  hard_brake_count: number;
}

/**
 * 주행 시작~종료 동안 폰이 스스로 GPS를 기록한다. 블루투스 연결 상태와 완전히
 * 무관하게 동작 — 파이한테 실시간으로 보내지 않고 로컬에만 쌓아뒀다가, 종료 시
 * 요약(getSummary)해서 파이의 위험 이벤트와 합친다 (mergeEvents.ts 참고).
 *
 * 거리는 두 GPS 점의 직선거리 대신 "속도 x 경과시간"으로 누적한다 — 도보 속도처럼
 * 느리게 이동하면 표본 간격에 비해 이동거리가 작아서 직선거리 방식은 계속 0으로
 * 걸러지는 문제가 있었음 (ble_peripheral.py의 예전 버그와 동일한 이유).
 */
export class RideGpsTracker {
  private subscription: Location.LocationSubscription | null = null;
  private points: RidePoint[] = [];
  private speedSamples: number[] = [];
  private distanceKm = 0;
  private lastSampleMs: number | null = null;
  private lastSpeedKmh: number | null = null;
  private hardBrakeCount = 0;
  private getCurrentRisk: () => RiskLevel = () => "안전";
  private onSpeedUpdate?: (speedKmh: number) => void;
  private onDistanceUpdate?: (distanceKm: number) => void;

  async start(options: {
    getCurrentRisk?: () => RiskLevel;
    onSpeedUpdate?: (speedKmh: number) => void;
    onDistanceUpdate?: (distanceKm: number) => void;
  } = {}): Promise<void> {
    const permission = await Location.requestForegroundPermissionsAsync();
    if (permission.status !== "granted") {
      throw new Error("휴대폰 위치 권한이 필요합니다.");
    }
    const servicesEnabled = await Location.hasServicesEnabledAsync();
    if (!servicesEnabled) {
      throw new Error("휴대폰의 위치(GPS) 기능을 켜주세요.");
    }

    this.stop();
    this.points = [];
    this.speedSamples = [];
    this.distanceKm = 0;
    this.lastSampleMs = null;
    this.lastSpeedKmh = null;
    this.hardBrakeCount = 0;
    this.getCurrentRisk = options.getCurrentRisk ?? (() => "안전");
    this.onSpeedUpdate = options.onSpeedUpdate;
    this.onDistanceUpdate = options.onDistanceUpdate;

    this.subscription = await Location.watchPositionAsync(
      { accuracy: Location.Accuracy.High, timeInterval: 1000, distanceInterval: 1 },
      (location) => this.handleUpdate(location)
    );
  }

  private handleUpdate(location: Location.LocationObject): void {
    const { latitude, longitude, speed } = location.coords;
    const speedKmh = speed != null && speed >= 0 ? speed * 3.6 : 0;
    const nowMs = location.timestamp;

    if (this.lastSampleMs != null) {
      const elapsedSec = Math.max(0, (nowMs - this.lastSampleMs) / 1000);
      this.distanceKm += speedKmh * (elapsedSec / 3600);
    }
    this.lastSampleMs = nowMs;

    if (
      this.lastSpeedKmh != null &&
      this.lastSpeedKmh >= HARD_BRAKE_MIN_SPEED_KMH &&
      this.lastSpeedKmh - speedKmh >= HARD_BRAKE_DELTA_KMH
    ) {
      this.hardBrakeCount += 1;
    }
    this.lastSpeedKmh = speedKmh;
    this.speedSamples.push(speedKmh);

    this.points.push({
      seq: this.points.length,
      lat: latitude,
      lng: longitude,
      recorded_at: new Date(nowMs).toISOString(),
      risk_level: this.getCurrentRisk(),
    });

    this.onSpeedUpdate?.(speedKmh);
    this.onDistanceUpdate?.(this.distanceKm);
  }

  stop(): void {
    this.subscription?.remove();
    this.subscription = null;
  }

  getSummary(): GpsSummary {
    const avg = this.speedSamples.length
      ? this.speedSamples.reduce((a, b) => a + b, 0) / this.speedSamples.length
      : 0;
    const max = this.speedSamples.length ? Math.max(...this.speedSamples) : 0;
    return {
      points: this.points,
      distance_km: Math.round(this.distanceKm * 1000) / 1000,
      avg_speed_kmh: Math.round(avg * 10) / 10,
      max_speed_kmh: Math.round(max * 10) / 10,
      hard_brake_count: this.hardBrakeCount,
    };
  }
}
