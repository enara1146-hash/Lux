from __future__ import annotations

import os
import sqlite3
from pathlib import Path

DATA_DIR = Path(os.getenv("LUX_DATA_DIR", "/data")).resolve()
DB_FILE = DATA_DIR / "lux.db"
ADMIN_KEY = os.getenv("LUX_ADMIN_KEY", "123456789")


def _connect() -> sqlite3.Connection:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(DB_FILE, timeout=30)
    db.execute("CREATE TABLE IF NOT EXISTS settings (name TEXT PRIMARY KEY, value TEXT NOT NULL)")
    db.commit()
    return db


def get(name: str, default: str | None = None) -> str | None:
    with _connect() as db:
        row = db.execute("SELECT value FROM settings WHERE name = ?", (name,)).fetchone()
    return row[0] if row else default


def set_value(name: str, value: str) -> None:
    with _connect() as db:
        db.execute("INSERT OR REPLACE INTO settings(name, value) VALUES (?, ?)", (name, value))
        db.commit()


def effective(name: str, default: str | None = None) -> str | None:
    return get(name, os.getenv(name, default))


def valid_admin(candidate: str | None) -> bool:
    return bool(ADMIN_KEY and candidate and candidate == ADMIN_KEY)


def public_config() -> dict[str, str | bool | None]:
    return {
        "model": effective("OPENAI_MODEL", "nvidia/nemotron-3-ultra-550b-a55b:free"),
        "base_url": effective("OPENAI_BASE_URL", "https://openrouter.ai/api/v1"),
        "auth_enabled": effective("LUX_AUTH_ENABLED", "false") == "true",
        "api_key_configured": bool(effective("OPENAI_API_KEY") or effective("LLM_API_KEY")),
        "admin_key_configured": bool(ADMIN_KEY),
    }
