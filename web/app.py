import os
import secrets
from functools import wraps

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

import accounts
import rides

PI_LIVE_URL = os.environ.get("PI_LIVE_URL", "http://raspberrypi.local:5000/")

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY") or secrets.token_hex(32)
accounts.init_db()
rides.init_db()


@app.context_processor
def inject_pi_live_url():
    return {"pi_live_url": PI_LIVE_URL}


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
    weekly = {"distance_km": 12.4, "count": 4, "avg_score": 88}
    streak_days = 3
    recent_rides = [
        {"date": "8월 25일", "distance_km": 5.2, "duration_min": 22, "avg_speed": 14.1,
         "risk_label": "주의 1회", "risk_level": "caution"},
        {"date": "8월 23일", "distance_km": 3.8, "duration_min": 17, "avg_speed": 13.4,
         "risk_label": "위험 1회", "risk_level": "danger"},
    ]
    current_user = accounts.get_user(session["user_id"])
    return render_template(
        "home.html", weekly=weekly, streak_days=streak_days, recent_rides=recent_rides,
        current_user=current_user,
    )


@app.route("/report")
@login_required
def report():
    return render_template("report.html")


@app.route("/settings")
@login_required
def settings():
    current_user = accounts.get_user(session["user_id"])
    return render_template("settings.html", current_user=current_user)


if __name__ == "__main__":
    app.run(port=5000, debug=True)
