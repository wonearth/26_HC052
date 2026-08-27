import calendar
import os
import secrets
from datetime import datetime
from functools import wraps
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from flask import (
    Flask,
    Response,
    jsonify,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

import accounts
import rides

PI_LIVE_URL = os.environ.get("PI_LIVE_URL", "http://raspberrypi.local:5000/")
RIDE_TOKEN_MAX_AGE = 6 * 3600  # 토큰 유효시간(초) — 라이딩 하나가 이보다 길면 만료됨

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY") or secrets.token_hex(32)
accounts.init_db()
rides.init_db()

_ride_token_serializer = URLSafeTimedSerializer(app.secret_key, salt="pm-adas-ride-token")


def make_ride_token(user_id):
    return _ride_token_serializer.dumps({"user_id": user_id})


def verify_ride_token(token):
    try:
        data = _ride_token_serializer.loads(token, max_age=RIDE_TOKEN_MAX_AGE)
    except (BadSignature, SignatureExpired):
        return None
    return data.get("user_id")


def _pi_url_with_token(token):
    parts = urlsplit(PI_LIVE_URL)
    query = dict(parse_qsl(parts.query))
    query["token"] = token
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))


def _with_cors(response):
    response.headers["Access-Control-Allow-Origin"] = "*"
    return response



def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if "user_id" not in session:
            return redirect(url_for("login", next=request.path))
        return view(*args, **kwargs)
    return wrapped


@app.route("/signup", methods=["GET", "POST"])
def signup():
    if request.method == "POST":
        nickname = request.form.get("nickname", "").strip()
        password = request.form.get("password", "")
        if not (2 <= len(nickname) <= 12):
            return render_template("signup.html", error="닉네임은 2~12자로 입력해주세요.", nickname=nickname)
        if len(password) < 4:
            return render_template("signup.html", error="비밀번호는 4자 이상이어야 해요.", nickname=nickname)
        try:
            user_id = accounts.create_user(nickname, password)
        except ValueError as e:
            return render_template("signup.html", error=str(e), nickname=nickname)
        session["user_id"] = user_id
        session["nickname"] = nickname
        return redirect(url_for("home"))
    return render_template("signup.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        nickname = request.form.get("nickname", "").strip()
        password = request.form.get("password", "")
        user = accounts.verify_user(nickname, password)
        if user is None:
            return render_template("login.html", error="닉네임 또는 비밀번호가 올바르지 않아요.")
        session["user_id"] = user["id"]
        session["nickname"] = user["nickname"]
        return redirect(request.args.get("next") or url_for("home"))
    return render_template("login.html")


@app.route("/logout", methods=["POST"])
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.route("/api/check-nickname", methods=["POST"])
def check_nickname():
    data = request.get_json(silent=True) or {}
    nickname = (data.get("nickname") or "").strip()
    exclude_id = session.get("user_id")
    valid_length = 2 <= len(nickname) <= 12
    available = valid_length and not accounts.nickname_exists(nickname, exclude_user_id=exclude_id)
    return jsonify({"available": available})


@app.route("/api/change-nickname", methods=["POST"])
@login_required
def change_nickname():
    data = request.get_json(silent=True) or {}
    nickname = (data.get("nickname") or "").strip()
    if not (2 <= len(nickname) <= 12):
        return jsonify({"error": "닉네임은 2~12자로 입력해주세요."}), 400
    try:
        accounts.update_nickname(session["user_id"], nickname)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    session["nickname"] = nickname
    return jsonify({"ok": True})



@app.route("/")
@login_required
def home():
    user_id = session["user_id"]
    weekly = rides.weekly_summary(user_id)
    current_user = accounts.get_user(user_id)
    return render_template(
        "home.html",
        weekly=weekly,
        streak_days=rides.streak_days(user_id),
        recent_rides=rides.list_recent_rides(user_id),
        current_user=current_user,
    )


@app.route("/start-ride")
@login_required
def start_ride():
    token = make_ride_token(session["user_id"])
    return redirect(_pi_url_with_token(token))


SAFETY_PENALTY = {"danger": 15, "warning": 8, "caution": 3}


def _compute_safety_score(events):
    penalty = sum(SAFETY_PENALTY.get(e.get("risk_level"), 0) for e in events)
    return max(0, 100 - penalty)


@app.route("/api/rides", methods=["POST", "OPTIONS"])
def save_ride():
    if request.method == "OPTIONS":
        resp = jsonify({})
        resp.headers["Access-Control-Allow-Methods"] = "POST, OPTIONS"
        resp.headers["Access-Control-Allow-Headers"] = "Content-Type"
        return _with_cors(resp)

    data = request.get_json(silent=True) or {}
    user_id = verify_ride_token(data.get("token", ""))
    if user_id is None:
        resp = jsonify({"error": "라이딩 토큰이 유효하지 않아요."})
        resp.status_code = 401
        return _with_cors(resp)

    points = data.get("points") or []
    events = data.get("events") or []

    ride_id = rides.create_ride(
        user_id=user_id,
        started_at=data.get("started_at"),
        ended_at=data.get("ended_at"),
        distance_km=float(data.get("distance_km") or 0),
        duration_sec=int(data.get("duration_sec") or 0),
        avg_speed_kmh=float(data.get("avg_speed_kmh") or 0),
        hard_brake_count=int(data.get("hard_brake_count") or 0),
        safety_score=_compute_safety_score(events),
    )
    rides.add_points(ride_id, points)
    rides.add_events(ride_id, events)

    return _with_cors(jsonify({"ok": True, "ride_id": ride_id}))


_ZONE_KOR = {True: "진행 경로 내", False: "진행 경로 밖"}


def _describe_event(e):
    zone = _ZONE_KOR.get(bool(e.get("in_collision_zone")), "진행 경로 밖")
    cls = e.get("object_class") or "객체"
    ttc = e.get("ttc_sec")
    distance = e.get("distance_m")
    if ttc is not None and distance is not None:
        return f"전방 {zone} {cls} 접근 · TTC {ttc:.1f}초 · {distance:.1f}m"
    if distance is not None:
        return f"전방 {zone} {cls} 감지 · {distance:.1f}m"
    return f"전방 {zone} {cls} 감지"


def _build_route_segments(points, width=260, height=150, pad=14):
    if len(points) < 2:
        return []
    lats = [p["lat"] for p in points]
    lngs = [p["lng"] for p in points]
    lat_span = max(max(lats) - min(lats), 1e-6)
    lng_span = max(max(lngs) - min(lngs), 1e-6)
    min_lat, min_lng = min(lats), min(lngs)

    def project(p):
        x = pad + (p["lng"] - min_lng) / lng_span * (width - 2 * pad)
        y = height - pad - (p["lat"] - min_lat) / lat_span * (height - 2 * pad)
        return x, y

    segments = []
    current_risk = points[0]["risk_level"]
    current_pts = [project(points[0])]
    for p in points[1:]:
        pt = project(p)
        current_pts.append(pt)
        if p["risk_level"] != current_risk:
            segments.append({"risk": current_risk, "points": current_pts})
            current_risk = p["risk_level"]
            current_pts = [pt]
    segments.append({"risk": current_risk, "points": current_pts})

    for seg in segments:
        seg["d"] = "M" + " L".join(f"{x:.1f},{y:.1f}" for x, y in seg["points"])
    return segments


def _build_report_context(ride):
    started = datetime.strptime(ride["started_at"], "%Y-%m-%d %H:%M:%S")
    ended = datetime.strptime(ride["ended_at"], "%Y-%m-%d %H:%M:%S")
    duration_sec = ride["duration_sec"]

    events_ctx = [
        {
            "time": datetime.strptime(e["occurred_at"], "%Y-%m-%d %H:%M:%S").strftime("%H:%M:%S"),
            "risk_level": e["risk_level"],
            "desc": _describe_event(e),
        }
        for e in ride["events"]
    ]

    return {
        "ride": ride,
        "date_label": f"{started.month}월 {started.day}일 · {started:%H:%M}–{ended:%H:%M}",
        "route_segments": _build_route_segments(ride["points"]),
        "distance_km": round(ride["distance_km"], 1),
        "duration_label": f"{duration_sec // 60:02d}:{duration_sec % 60:02d}",
        "avg_speed_kmh": round(ride["avg_speed_kmh"], 1),
        "hard_brake_count": ride["hard_brake_count"],
        "safety_score": ride["safety_score"],
        "events": events_ctx,
    }


_WEEKDAY_KOR = ["월", "화", "수", "목", "금", "토", "일"]


def _shift_month(year, month, delta):
    idx = year * 12 + (month - 1) + delta
    return idx // 12, idx % 12 + 1


def _build_calendar(year, month, ride_days, today_str, selected_date):
    cal = calendar.Calendar(firstweekday=0)  # 월요일 시작
    weeks = []
    for week in cal.monthdayscalendar(year, month):
        row = []
        for day in week:
            if day == 0:
                row.append(None)
                continue
            date_str = f"{year:04d}-{month:02d}-{day:02d}"
            row.append({
                "day": day,
                "date": date_str,
                "risk_level": ride_days.get(date_str),
                "is_today": date_str == today_str,
                "is_selected": date_str == selected_date,
            })
        weeks.append(row)
    return weeks


def _format_kr_date(date_str):
    d = datetime.strptime(date_str, "%Y-%m-%d")
    return f"{d.month}월 {d.day}일 ({_WEEKDAY_KOR[d.weekday()]})"


@app.route("/report")
@login_required
def report():
    user_id = session["user_id"]
    today = datetime.utcnow().date()

    month_param = request.args.get("month")
    if month_param:
        try:
            year, month = (int(p) for p in month_param.split("-"))
        except ValueError:
            year, month = today.year, today.month
    else:
        latest_date = rides.get_latest_ride_date(user_id)
        year, month = (latest_date.year, latest_date.month) if latest_date else (today.year, today.month)

    ride_days = rides.get_ride_days_for_month(user_id, year, month)

    selected_date = request.args.get("date")
    if selected_date is None:
        if ride_days:
            selected_date = max(ride_days.keys())
        elif year == today.year and month == today.month:
            selected_date = today.isoformat()

    day_rides = rides.list_rides_for_date(user_id, selected_date) if selected_date else []
    prev_year, prev_month = _shift_month(year, month, -1)
    next_year, next_month = _shift_month(year, month, 1)

    return render_template(
        "report.html",
        weeks=_build_calendar(year, month, ride_days, today.isoformat(), selected_date),
        month_label=f"{year}년 {month}월",
        current_month=f"{year:04d}-{month:02d}",
        prev_month=f"{prev_year:04d}-{prev_month:02d}",
        next_month=f"{next_year:04d}-{next_month:02d}",
        selected_date=selected_date,
        selected_date_label=_format_kr_date(selected_date) if selected_date else None,
        day_rides=day_rides,
    )


@app.route("/report/<int:ride_id>")
@login_required
def report_detail(ride_id):
    ride = rides.get_ride_detail(ride_id, session["user_id"])
    if ride is None:
        return render_template("report_detail.html", ride=None), 404
    ctx = _build_report_context(ride)
    ctx["back_date"] = ride["started_at"][:10]
    return render_template("report_detail.html", **ctx)


@app.route("/settings")
@login_required
def settings():
    current_user = accounts.get_user(session["user_id"])
    return render_template("settings.html", current_user=current_user)


if __name__ == "__main__":
    app.run(port=5000, debug=True)
