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


# =========================
# 저장
# =========================
from datetime import datetime, timedelta, timezone

import libsql_client as _libsql_client


def _to_sql_datetime(iso_str):
    dt = datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
    dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt.strftime("%Y-%m-%d %H:%M:%S")


def create_ride(user_id, started_at, ended_at, distance_km, duration_sec,
                 avg_speed_kmh, hard_brake_count=0, safety_score=None):
    with get_client() as client:
        rs = client.execute(
            """
            INSERT INTO rides
                (user_id, started_at, ended_at, distance_km, duration_sec,
                 avg_speed_kmh, hard_brake_count, safety_score)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            RETURNING id
            """,
            [
                user_id, _to_sql_datetime(started_at), _to_sql_datetime(ended_at),
                distance_km, duration_sec, avg_speed_kmh, hard_brake_count, safety_score,
            ],
        )
        return rs.rows[0][0]


def add_points(ride_id, points):
    if not points:
        return
    with get_client() as client:
        stmts = [
            _libsql_client.Statement(
                "INSERT INTO ride_points (ride_id, seq, lat, lng, recorded_at, risk_level) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                [ride_id, i, p["lat"], p["lng"], _to_sql_datetime(p["recorded_at"]),
                 p.get("risk_level", "safe")],
            )
            for i, p in enumerate(points)
        ]
        client.batch(stmts)


def add_events(ride_id, events):
    if not events:
        return
    with get_client() as client:
        stmts = [
            _libsql_client.Statement(
                """
                INSERT INTO ride_events
                    (ride_id, occurred_at, risk_level, object_class, distance_m,
                     ttc_sec, in_collision_zone, lat, lng)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    ride_id, _to_sql_datetime(e["occurred_at"]), e["risk_level"],
                    e.get("object_class"), e.get("distance_m"), e.get("ttc_sec"),
                    1 if e.get("in_collision_zone") else 0, e.get("lat"), e.get("lng"),
                ],
            )
            for e in events
        ]
        client.batch(stmts)


# =========================
# 조회
# =========================
_RISK_ORDER = ["danger", "warning", "caution"]
_RISK_KOR = {"danger": "위험", "warning": "경고", "caution": "주의"}


def _worst_risk(counts):
    for level in _RISK_ORDER:
        if counts.get(level):
            return level, counts[level]
    return "safe", 0


def _risk_label(risk_level, count):
    if risk_level == "safe":
        return "안전"
    return f"{_RISK_KOR[risk_level]} {count}회"


def _format_date(sql_dt):
    dt = datetime.strptime(sql_dt, "%Y-%m-%d %H:%M:%S")
    return f"{dt.month}월 {dt.day}일"


def weekly_summary(user_id):
    with get_client() as client:
        rs = client.execute(
            """
            SELECT COUNT(*), COALESCE(SUM(distance_km), 0), AVG(safety_score)
            FROM rides
            WHERE user_id = ? AND started_at >= datetime('now', '-7 days')
            """,
            [user_id],
        )
    count, distance_km, avg_score = rs.rows[0]
    return {
        "count": count,
        "distance_km": round(distance_km, 1),
        "avg_score": round(avg_score) if avg_score is not None else None,
    }


def streak_days(user_id):
    with get_client() as client:
        rs = client.execute(
            "SELECT DISTINCT date(started_at) AS d FROM rides WHERE user_id = ? ORDER BY d DESC",
            [user_id],
        )
    dates = {row[0] for row in rs.rows}
    if not dates:
        return 0
    day = datetime.utcnow().date()
    if str(day) not in dates:
        day -= timedelta(days=1)
    streak = 0
    while str(day) in dates:
        streak += 1
        day -= timedelta(days=1)
    return streak


def list_recent_rides(user_id, limit=5):
    with get_client() as client:
        rs = client.execute(
            """
            SELECT id, started_at, distance_km, duration_sec, avg_speed_kmh
            FROM rides WHERE user_id = ? ORDER BY started_at DESC LIMIT ?
            """,
            [user_id, limit],
        )
        result = []
        for ride_id, started_at, distance_km, duration_sec, avg_speed_kmh in rs.rows:
            ev = client.execute(
                "SELECT risk_level, COUNT(*) FROM ride_events WHERE ride_id = ? GROUP BY risk_level",
                [ride_id],
            )
            counts = {r[0]: r[1] for r in ev.rows}
            risk_level, count = _worst_risk(counts)
            result.append({
                "id": ride_id,
                "date": _format_date(started_at),
                "distance_km": round(distance_km, 1),
                "duration_min": round(duration_sec / 60),
                "avg_speed": round(avg_speed_kmh, 1),
                "risk_level": risk_level,
                "risk_label": _risk_label(risk_level, count),
            })
        return result


def get_latest_ride_id(user_id):
    with get_client() as client:
        rs = client.execute(
            "SELECT id FROM rides WHERE user_id = ? ORDER BY started_at DESC LIMIT 1",
            [user_id],
        )
    return rs.rows[0][0] if rs.rows else None


def get_ride_detail(ride_id, user_id):
    with get_client() as client:
        rs = client.execute(
            "SELECT * FROM rides WHERE id = ? AND user_id = ?", [ride_id, user_id]
        )
        if len(rs.rows) == 0:
            return None
        ride = dict(zip(rs.columns, rs.rows[0]))

        pts = client.execute(
            "SELECT lat, lng, risk_level FROM ride_points WHERE ride_id = ? ORDER BY seq",
            [ride_id],
        )
        ride["points"] = [dict(zip(pts.columns, r)) for r in pts.rows]

        evs = client.execute(
            """
            SELECT occurred_at, risk_level, object_class, distance_m, ttc_sec,
                   in_collision_zone, lat, lng
            FROM ride_events WHERE ride_id = ? ORDER BY occurred_at
            """,
            [ride_id],
        )
        ride["events"] = [dict(zip(evs.columns, r)) for r in evs.rows]
        return ride


# =========================
# 달력 / 날짜별 조회
# =========================
_RISK_RANK = {"safe": 0, "caution": 1, "warning": 2, "danger": 3}


def get_latest_ride_date(user_id):
    with get_client() as client:
        rs = client.execute(
            "SELECT date(started_at) FROM rides WHERE user_id = ? ORDER BY started_at DESC LIMIT 1",
            [user_id],
        )
    if not rs.rows:
        return None
    return datetime.strptime(rs.rows[0][0], "%Y-%m-%d").date()


def get_ride_days_for_month(user_id, year, month):
    start = f"{year:04d}-{month:02d}-01"
    end_year, end_month = (year + 1, 1) if month == 12 else (year, month + 1)
    end = f"{end_year:04d}-{end_month:02d}-01"

    with get_client() as client:
        rs = client.execute(
            "SELECT id, date(started_at) FROM rides "
            "WHERE user_id = ? AND started_at >= ? AND started_at < ?",
            [user_id, start, end],
        )
        date_by_ride = {row[0]: row[1] for row in rs.rows}
        if not date_by_ride:
            return {}

        placeholders = ",".join("?" * len(date_by_ride))
        ev = client.execute(
            f"SELECT ride_id, risk_level FROM ride_events WHERE ride_id IN ({placeholders})",
            list(date_by_ride.keys()),
        )
        worst_by_ride = {}
        for ride_id, risk_level in ev.rows:
            if _RISK_RANK.get(risk_level, 0) > _RISK_RANK.get(worst_by_ride.get(ride_id), -1):
                worst_by_ride[ride_id] = risk_level

    result = {}
    for ride_id, date_str in date_by_ride.items():
        risk = worst_by_ride.get(ride_id, "safe")
        if _RISK_RANK[risk] > _RISK_RANK.get(result.get(date_str), -1):
            result[date_str] = risk
    return result


def list_rides_for_date(user_id, date_str):
    with get_client() as client:
        rs = client.execute(
            """
            SELECT id, started_at, ended_at, distance_km, duration_sec, avg_speed_kmh, safety_score
            FROM rides WHERE user_id = ? AND date(started_at) = ? ORDER BY started_at
            """,
            [user_id, date_str],
        )
        result = []
        for ride_id, started_at, ended_at, distance_km, duration_sec, avg_speed_kmh, safety_score in rs.rows:
            ev = client.execute(
                "SELECT risk_level, COUNT(*) FROM ride_events WHERE ride_id = ? GROUP BY risk_level",
                [ride_id],
            )
            counts = {r[0]: r[1] for r in ev.rows}
            risk_level, count = _worst_risk(counts)
            started = datetime.strptime(started_at, "%Y-%m-%d %H:%M:%S")
            ended = datetime.strptime(ended_at, "%Y-%m-%d %H:%M:%S")
            result.append({
                "id": ride_id,
                "time_range": f"{started:%H:%M}–{ended:%H:%M}",
                "distance_km": round(distance_km, 1),
                "duration_min": round(duration_sec / 60),
                "avg_speed": round(avg_speed_kmh, 1),
                "safety_score": safety_score,
                "risk_level": risk_level,
                "risk_label": _risk_label(risk_level, count),
            })
        return result
