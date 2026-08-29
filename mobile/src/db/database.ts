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
  `);
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
