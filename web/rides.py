from accounts import get_client


def init_db():
    with get_client() as client:
        client.execute(
            """
            CREATE TABLE IF NOT EXISTS rides (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL REFERENCES users(id),
                started_at TEXT NOT NULL,
                ended_at TEXT NOT NULL,
                distance_km REAL NOT NULL DEFAULT 0,
                duration_sec INTEGER NOT NULL DEFAULT 0,
                avg_speed_kmh REAL NOT NULL DEFAULT 0,
                safety_score INTEGER,
                hard_brake_count INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
            )
            """
        )
        client.execute(
            "CREATE INDEX IF NOT EXISTS idx_rides_user ON rides(user_id)"
        )

        # 경로 좌표 — 리포트 지도에서 위험도별로 구간 색칠하는 데 사용
        client.execute(
            """
            CREATE TABLE IF NOT EXISTS ride_points (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ride_id INTEGER NOT NULL REFERENCES rides(id),
                seq INTEGER NOT NULL,
                lat REAL NOT NULL,
                lng REAL NOT NULL,
                recorded_at TEXT NOT NULL,
                risk_level TEXT NOT NULL DEFAULT 'safe'
            )
            """
        )
        client.execute(
            "CREATE INDEX IF NOT EXISTS idx_ride_points_ride ON ride_points(ride_id)"
        )

        # 위험 이벤트 로그 — 리포트의 이벤트 타임라인, 추후 위험구간 집계에도 사용
        client.execute(
            """
            CREATE TABLE IF NOT EXISTS ride_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ride_id INTEGER NOT NULL REFERENCES rides(id),
                occurred_at TEXT NOT NULL,
                risk_level TEXT NOT NULL,
                object_class TEXT,
                distance_m REAL,
                ttc_sec REAL,
                in_collision_zone INTEGER NOT NULL DEFAULT 0,
                lat REAL,
                lng REAL
            )
            """
        )
        client.execute(
            "CREATE INDEX IF NOT EXISTS idx_ride_events_ride ON ride_events(ride_id)"
        )
