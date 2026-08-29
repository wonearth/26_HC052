"""
파이가 직접 라이딩 데이터를 Vercel(/api/rides)로 업로드하고,
실패하면 로컬 SQLite에 쌓아뒀다가 나중에 재시도하는 모듈.
"""
import json
import sqlite3
import urllib.error
import urllib.request
from pathlib import Path

DB_PATH = Path(__file__).with_name("pending_rides.db")


def _get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS pending_rides (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            payload TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        )
        """
    )
    return conn


def queue_pending(payload):
    with _get_conn() as conn:
        conn.execute("INSERT INTO pending_rides (payload) VALUES (?)", [json.dumps(payload)])


def list_pending():
    with _get_conn() as conn:
        rows = conn.execute("SELECT id, payload FROM pending_rides ORDER BY id").fetchall()
    return [(row[0], json.loads(row[1])) for row in rows]


def remove_pending(row_id):
    with _get_conn() as conn:
        conn.execute("DELETE FROM pending_rides WHERE id = ?", [row_id])


def upload_ride(upload_url, payload, timeout=8):
    """Vercel의 /api/rides로 업로드한다. 성공하면 True."""
    try:
        req = urllib.request.Request(
            upload_url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return 200 <= resp.status < 300
    except Exception as e:
        print(f"❌ 라이딩 업로드 실패: {e}")
        return False


def save_ride_reliably(upload_url, payload):
    """업로드 시도 후 실패하면 로컬에 보류시켜 나중에 재시도할 수 있게 한다."""
    if upload_ride(upload_url, payload):
        return True
    queue_pending(payload)
    print("⚠️  업로드 실패 — 로컬에 보류 저장, 다음 기회에 자동 재시도")
    return False


def flush_pending(upload_url):
    """보류 중인 라이딩들을 재시도. 백그라운드에서 주기적으로 호출."""
    for row_id, payload in list_pending():
        if upload_ride(upload_url, payload):
            remove_pending(row_id)
            print(f"✅ 보류 중이던 라이딩 업로드 성공 (id={row_id})")
