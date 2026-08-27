import os

import libsql_client
from werkzeug.security import check_password_hash, generate_password_hash

_raw_db_url = os.environ.get("TURSO_DATABASE_URL", "file:users.db")
# libsql:// 는 웹소켓(Hrana) 프로토콜을 쓰는데, 서버리스 환경에서 연결이
# 불안정해서 매 요청이 짧게 끝나는 https:// (Hrana-over-HTTP)로 바꿔서 사용.
DB_URL = _raw_db_url.replace("libsql://", "https://", 1)
DB_AUTH_TOKEN = os.environ.get("TURSO_AUTH_TOKEN")


def get_client():
    if DB_AUTH_TOKEN:
        return libsql_client.create_client_sync(url=DB_URL, auth_token=DB_AUTH_TOKEN)
    return libsql_client.create_client_sync(url=DB_URL)


def init_db():
    with get_client() as client:
        client.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                nickname TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
            )
            """
        )


def _row_to_dict(rs, row):
    return dict(zip(rs.columns, row))


def nickname_exists(nickname, exclude_user_id=None):
    with get_client() as client:
        if exclude_user_id is None:
            rs = client.execute("SELECT 1 FROM users WHERE nickname = ?", [nickname])
        else:
            rs = client.execute(
                "SELECT 1 FROM users WHERE nickname = ? AND id != ?",
                [nickname, exclude_user_id],
            )
        return len(rs.rows) > 0


def create_user(nickname, password):
    if nickname_exists(nickname):
        raise ValueError("이미 사용 중인 닉네임이에요.")
    with get_client() as client:
        rs = client.execute(
            "INSERT INTO users (nickname, password_hash) VALUES (?, ?) RETURNING id",
            [nickname, generate_password_hash(password)],
        )
        return rs.rows[0][0]


def verify_user(nickname, password):
    with get_client() as client:
        rs = client.execute("SELECT * FROM users WHERE nickname = ?", [nickname])
    if len(rs.rows) == 0:
        return None
    user = _row_to_dict(rs, rs.rows[0])
    if not check_password_hash(user["password_hash"], password):
        return None
    return user


def get_user(user_id):
    with get_client() as client:
        rs = client.execute("SELECT * FROM users WHERE id = ?", [user_id])
    if len(rs.rows) == 0:
        return None
    return _row_to_dict(rs, rs.rows[0])


def update_nickname(user_id, new_nickname):
    if nickname_exists(new_nickname, exclude_user_id=user_id):
        raise ValueError("이미 사용 중인 닉네임이에요.")
    with get_client() as client:
        client.execute(
            "UPDATE users SET nickname = ? WHERE id = ?", [new_nickname, user_id]
        )
