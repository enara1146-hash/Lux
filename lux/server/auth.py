from __future__ import annotations

import hashlib
import hmac
import os
import secrets
import sqlite3
import time
import uuid
from pathlib import Path

DATA_DIR = Path(os.getenv("LUX_DATA_DIR", "/data")).resolve()
DB_FILE = DATA_DIR / "lux.db"


def _connect() -> sqlite3.Connection:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(DB_FILE, timeout=30)
    db.row_factory = sqlite3.Row
    db.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id TEXT PRIMARY KEY,
            email TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            created_at REAL NOT NULL
        )
    """)
    db.execute("""
        CREATE TABLE IF NOT EXISTS sessions (
            token TEXT PRIMARY KEY,
            user_id TEXT NOT NULL,
            created_at REAL NOT NULL
        )
    """)
    db.commit()
    return db


def _hash(password: str, salt: bytes | None = None) -> str:
    salt = salt or secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 310_000)
    return salt.hex() + "$" + digest.hex()


def _verify(password: str, encoded: str) -> bool:
    salt_hex, digest = encoded.split("$", 1)
    actual = _hash(password, bytes.fromhex(salt_hex)).split("$", 1)[1]
    return hmac.compare_digest(actual, digest)


def register(email: str, password: str) -> dict[str, str]:
    user_id = str(uuid.uuid4())
    normalized = email.lower().strip()
    with _connect() as db:
        try:
            db.execute("INSERT INTO users VALUES (?, ?, ?, ?)",
                       (user_id, normalized, _hash(password), time.time()))
            db.commit()
        except sqlite3.IntegrityError as exc:
            raise ValueError("Email is already registered") from exc
    return {"id": user_id, "email": normalized}


def bootstrap_admin() -> None:
    email = os.getenv("LUX_DEFAULT_ADMIN_EMAIL", "admin@admin.com").strip().lower()
    password = os.getenv("LUX_DEFAULT_ADMIN_PASSWORD", "").strip()
    if not password:
        return
    with _connect() as db:
        exists = db.execute("SELECT 1 FROM users WHERE email = ?", (email,)).fetchone()
        if not exists:
            db.execute(
                "INSERT INTO users VALUES (?, ?, ?, ?)",
                (str(uuid.uuid4()), email, _hash(password), time.time()),
            )
            db.commit()


def login(email: str, password: str) -> str:
    normalized = email.lower().strip()
    if os.getenv("LUX_DEMO_AUTH", "false").lower() == "true" and normalized and password:
        with _connect() as db:
            user = db.execute("SELECT * FROM users WHERE email = ?", (normalized,)).fetchone()
            if not user:
                user_id = str(uuid.uuid4())
                db.execute("INSERT INTO users VALUES (?, ?, ?, ?)", (user_id, normalized, _hash(secrets.token_urlsafe(24)), time.time()))
                db.commit()
                user = {"id": user_id}
            token = secrets.token_urlsafe(32)
            db.execute("INSERT INTO sessions VALUES (?, ?, ?)", (token, user["id"], time.time()))
            db.commit()
            return token
    with _connect() as db:
        user = db.execute("SELECT * FROM users WHERE email = ?", (normalized,)).fetchone()
        if not user or not _verify(password, user["password_hash"]):
            raise ValueError("Invalid email or password")
        token = secrets.token_urlsafe(32)
        db.execute("INSERT INTO sessions VALUES (?, ?, ?)", (token, user["id"], time.time()))
        db.commit()
        return token


def user_for_token(token: str | None) -> str | None:
    if not token:
        return None
    with _connect() as db:
        row = db.execute("SELECT user_id FROM sessions WHERE token = ?", (token,)).fetchone()
        return row["user_id"] if row else None
