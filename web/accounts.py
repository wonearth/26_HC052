import sqlite3
from pathlib import Path

from werkzeug.security import check_password_hash, generate_password_hash

DB_PATH = Path(__file__).with_name("users.db")


def get_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with get_connection() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                nickname TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
            )
            """
        )


def nickname_exists(nickname, exclude_user_id=None):
    with get_connection() as conn:
        if exclude_user_id is None:
            row = conn.execute(
                "SELECT 1 FROM users WHERE nickname = ?", (nickname,)
            ).fetchone()
        else:
            row = conn.execute(
                "SELECT 1 FROM users WHERE nickname = ? AND id != ?",
                (nickname, exclude_user_id),
            ).fetchone()
        return row is not None


def create_user(nickname, password):
    if nickname_exists(nickname):
        raise ValueError("이미 사용 중인 닉네임이에요.")
    with get_connection() as conn:
        cursor = conn.execute(
            "INSERT INTO users (nickname, password_hash) VALUES (?, ?)",
            (nickname, generate_password_hash(password)),
        )
        return cursor.lastrowid


def verify_user(nickname, password):
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM users WHERE nickname = ?", (nickname,)
        ).fetchone()
    if row is None or not check_password_hash(row["password_hash"], password):
        return None
    return dict(row)


def get_user(user_id):
    with get_connection() as conn:
        row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    return dict(row) if row else None


def update_nickname(user_id, new_nickname):
    if nickname_exists(new_nickname, exclude_user_id=user_id):
        raise ValueError("이미 사용 중인 닉네임이에요.")
    with get_connection() as conn:
        conn.execute(
            "UPDATE users SET nickname = ? WHERE id = ?", (new_nickname, user_id)
        )
