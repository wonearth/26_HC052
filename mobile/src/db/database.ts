import * as SQLite from "expo-sqlite";
import type { RideEvent, RidePayload, RidePoint, RideSummary } from "../types/ride";

let dbPromise: Promise<SQLite.SQLiteDatabase> | null = null;

function getDb(): Promise<SQLite.SQLiteDatabase> {
  if (!dbPromise) dbPromise = SQLite.openDatabaseAsync("pmadas.db");
  return dbPromise;
}

export async function initDb(): Promise<void> {
  const db = await getDb();
  await db.execAsync(`
    PRAGMA journal_mode = WAL;

    CREATE TABLE IF NOT EXISTS rides (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      client_ride_uuid TEXT UNIQUE NOT NULL,
      started_at TEXT NOT NULL,
      ended_at TEXT NOT NULL,
      distance_km REAL NOT NULL,
      duration_sec INTEGER NOT NULL,
      avg_speed_kmh REAL NOT NULL,
      max_speed_kmh REAL NOT NULL,
      hard_brake_count INTEGER NOT NULL,
      safety_score INTEGER NOT NULL,
      created_at TEXT NOT NULL DEFAULT (datetime('now'))
    );

    CREATE TABLE IF NOT EXISTS ride_points (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      ride_id INTEGER NOT NULL REFERENCES rides(id),
      seq INTEGER NOT NULL,
      lat REAL NOT NULL,
      lng REAL NOT NULL,
      recorded_at TEXT NOT NULL,
      risk_level TEXT NOT NULL
    );

    CREATE TABLE IF NOT EXISTS ride_events (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      ride_id INTEGER NOT NULL REFERENCES rides(id),
      occurred_at TEXT NOT NULL,
      risk_level TEXT NOT NULL,
      object_class TEXT NOT NULL,
      distance_m REAL NOT NULL,
      ttc_sec REAL NOT NULL,
      lat REAL NOT NULL,
      lng REAL NOT NULL
    );

    CREATE TABLE IF NOT EXISTS app_settings (
      key TEXT PRIMARY KEY,
      value TEXT
    );
  `);
}

const NICKNAME_KEY = "nickname";

export async function getNickname(): Promise<string | null> {
  const db = await getDb();
  const row = await db.getFirstAsync<{ value: string }>(
    `SELECT value FROM app_settings WHERE key = ?`,
    [NICKNAME_KEY]
  );
  return row?.value ?? null;
}

export async function setNickname(nickname: string): Promise<void> {
  const db = await getDb();
  await db.runAsync(
    `INSERT INTO app_settings (key, value) VALUES (?, ?)
     ON CONFLICT(key) DO UPDATE SET value = excluded.value`,
    [NICKNAME_KEY, nickname]
  );
}

/** 라이딩 기록 전체 삭제 (초기화) — 닉네임 등 다른 설정은 그대로 둔다. */
export async function clearAllRides(): Promise<void> {
  const db = await getDb();
  await db.withTransactionAsync(async () => {
    await db.runAsync(`DELETE FROM ride_events`);
    await db.runAsync(`DELETE FROM ride_points`);
    await db.runAsync(`DELETE FROM rides`);
  });
}

/** client_ride_uuid가 이미 있으면 그 ride_id를 그대로 반환 (BLE 재시도로 중복 저장되는 것 방지) */
export async function saveRide(payload: RidePayload): Promise<number> {
  const db = await getDb();

  const existing = await db.getFirstAsync<{ id: number }>(
    `SELECT id FROM rides WHERE client_ride_uuid = ?`,
    [payload.client_ride_uuid]
  );
  if (existing) return existing.id;

  let rideId = -1;

  await db.withTransactionAsync(async () => {
    const result = await db.runAsync(
      `INSERT INTO rides
        (client_ride_uuid, started_at, ended_at, distance_km, duration_sec,
         avg_speed_kmh, max_speed_kmh, hard_brake_count, safety_score)
       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)`,
      [
        payload.client_ride_uuid,
        payload.started_at,
        payload.ended_at,
        payload.distance_km,
        payload.duration_sec,
        payload.avg_speed_kmh,
        payload.max_speed_kmh,
        payload.hard_brake_count,
        payload.safety_score,
      ]
    );
    rideId = result.lastInsertRowId;

    for (const point of payload.points) {
      await db.runAsync(
        `INSERT INTO ride_points (ride_id, seq, lat, lng, recorded_at, risk_level)
         VALUES (?, ?, ?, ?, ?, ?)`,
        [rideId, point.seq, point.lat, point.lng, point.recorded_at, point.risk_level]
      );
    }

    for (const event of payload.events) {
      await db.runAsync(
        `INSERT INTO ride_events
          (ride_id, occurred_at, risk_level, object_class, distance_m, ttc_sec, lat, lng)
         VALUES (?, ?, ?, ?, ?, ?, ?, ?)`,
        [
          rideId,
          event.occurred_at,
          event.risk_level,
          event.object_class,
          event.distance_m,
          event.ttc_sec,
          event.lat,
          event.lng,
        ]
      );
    }
  });

  return rideId;
}

export async function listRides(): Promise<RideSummary[]> {
  const db = await getDb();
  return db.getAllAsync<RideSummary>(
    `SELECT id, client_ride_uuid, started_at, ended_at, distance_km, duration_sec,
            avg_speed_kmh, max_speed_kmh, hard_brake_count, safety_score
     FROM rides ORDER BY started_at DESC`
  );
}

export async function getRideDetail(
  rideId: number
): Promise<{ summary: RideSummary; points: RidePoint[]; events: RideEvent[] } | null> {
  const db = await getDb();
  const summary = await db.getFirstAsync<RideSummary>(
    `SELECT id, client_ride_uuid, started_at, ended_at, distance_km, duration_sec,
            avg_speed_kmh, max_speed_kmh, hard_brake_count, safety_score
     FROM rides WHERE id = ?`,
    [rideId]
  );
  if (!summary) return null;

  const points = await db.getAllAsync<RidePoint>(
    `SELECT seq, lat, lng, recorded_at, risk_level FROM ride_points
     WHERE ride_id = ? ORDER BY seq ASC`,
    [rideId]
  );
  const events = await db.getAllAsync<RideEvent>(
    `SELECT occurred_at, risk_level, object_class, distance_m, ttc_sec, lat, lng
     FROM ride_events WHERE ride_id = ? ORDER BY occurred_at ASC`,
    [rideId]
  );

  return { summary, points, events };
}

const RISK_RANK: Record<string, number> = { 안전: 0, 주의: 1, 경고: 2, 위험: 3 };
const RANK_TO_RISK = ["안전", "주의", "경고", "위험"];

export interface RideDaySummary {
  date: string; // YYYY-MM-DD
  riskLevel: string;
  rideCount: number;
}

/** yearMonth: "YYYY-MM". 그 달에 라이딩이 있었던 날짜와 그날의 최악 위험도를 반환. */
export async function getRideDaysForMonth(yearMonth: string): Promise<RideDaySummary[]> {
  const db = await getDb();
  const rows = await db.getAllAsync<{ day: string; risk_level: string | null; ride_count: number }>(
    `SELECT date(r.started_at) AS day,
            re.risk_level AS risk_level,
            COUNT(DISTINCT r.id) AS ride_count
     FROM rides r
     LEFT JOIN ride_events re ON re.ride_id = r.id
     WHERE strftime('%Y-%m', r.started_at) = ?
     GROUP BY day, re.risk_level`,
    [yearMonth]
  );

  const byDay = new Map<string, { rank: number; rideCount: number }>();
  for (const row of rows) {
    const rank = row.risk_level ? RISK_RANK[row.risk_level] ?? 0 : 0;
    const existing = byDay.get(row.day);
    if (!existing || rank > existing.rank) {
      byDay.set(row.day, { rank, rideCount: (existing?.rideCount ?? 0) + row.ride_count });
    } else {
      existing.rideCount += row.ride_count;
    }
  }

  return [...byDay.entries()].map(([date, v]) => ({
    date,
    riskLevel: RANK_TO_RISK[v.rank],
    rideCount: v.rideCount,
  }));
}

export async function listRidesForDate(date: string): Promise<RideSummary[]> {
  const db = await getDb();
  return db.getAllAsync<RideSummary>(
    `SELECT id, client_ride_uuid, started_at, ended_at, distance_km, duration_sec,
            avg_speed_kmh, max_speed_kmh, hard_brake_count, safety_score
     FROM rides WHERE date(started_at) = ? ORDER BY started_at DESC`,
    [date]
  );
}

export interface SummaryStats {
  rideCount: number;
  totalDistanceKm: number;
  avgSafetyScore: number;
}

export async function getSummaryStats(): Promise<SummaryStats> {
  const db = await getDb();
  const row = await db.getFirstAsync<{ ride_count: number; total_km: number; avg_score: number }>(
    `SELECT COUNT(*) AS ride_count,
            COALESCE(SUM(distance_km), 0) AS total_km,
            COALESCE(AVG(safety_score), 0) AS avg_score
     FROM rides`
  );
  return {
    rideCount: row?.ride_count ?? 0,
    totalDistanceKm: row?.total_km ?? 0,
    avgSafetyScore: Math.round(row?.avg_score ?? 0),
  };
}
