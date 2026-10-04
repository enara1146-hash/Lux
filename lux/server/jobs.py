from __future__ import annotations

import json
import os
import sqlite3
import time
from pathlib import Path
from typing import Any

DATA_DIR = Path(os.getenv("LUX_DATA_DIR", "/data")).resolve()
DB_FILE = DATA_DIR / "lux.db"


def _connect() -> sqlite3.Connection:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(DB_FILE, timeout=30)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute("""
        CREATE TABLE IF NOT EXISTS jobs (
            id TEXT PRIMARY KEY,
            prompt TEXT NOT NULL,
            project_name TEXT NOT NULL,
            status TEXT NOT NULL,
            payload TEXT NOT NULL,
            created_at REAL NOT NULL,
            updated_at REAL NOT NULL
        )
    """)
    connection.commit()
    return connection


def _row(row: sqlite3.Row | None) -> dict[str, Any] | None:
    if row is None:
        return None
    result = dict(row)
    result.update(json.loads(result.pop("payload")))
    return result


def create(prompt: str, project_name: str, owner_id: str | None = None) -> dict[str, Any]:
    import secrets
    now = time.time()
    job = {"id": secrets.token_urlsafe(16), "prompt": prompt,
           "project_name": project_name, "owner_id": owner_id, "status": "queued",
           "created_at": now, "updated_at": now}
    with _connect() as connection:
        connection.execute(
            "INSERT INTO jobs VALUES (?, ?, ?, ?, ?, ?, ?)",
            (job["id"], prompt, project_name, "queued", json.dumps(job), now, now),
        )
    return job


def get(job_id: str) -> dict[str, Any] | None:
    with _connect() as connection:
        return _row(connection.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone())


def update(job_id: str, **changes: Any) -> dict[str, Any] | None:
    with _connect() as connection:
        row = connection.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
        job = _row(row)
        if not job:
            return None
        job.update(changes)
        job["updated_at"] = time.time()
        connection.execute(
            "UPDATE jobs SET status = ?, payload = ?, updated_at = ? WHERE id = ?",
            (job["status"], json.dumps(job), job["updated_at"], job_id),
        )
    return job


def approve(job_id: str, approved: bool) -> dict[str, Any] | None:
    job = get(job_id)
    if not job:
        return None
    if job["status"] == "waiting_for_approval":
        return update(job_id, status="queued" if approved else "cancelled", approval=approved)
    return job


def request_approval(job_id: str, reason: str) -> dict[str, Any] | None:
    return update(job_id, status="waiting_for_approval", approval_reason=reason[:2000])


def cancel(job_id: str) -> dict[str, Any] | None:
    job = get(job_id)
    if not job:
        return None
    if job["status"] in {"queued", "running", "waiting_for_approval"}:
        return update(job_id, status="cancelled")
    return job


def recent(limit: int = 50) -> list[dict[str, Any]]:
    with _connect() as connection:
        rows = connection.execute(
            "SELECT * FROM jobs ORDER BY updated_at DESC LIMIT ?", (max(1, min(limit, 200)),)
        ).fetchall()
    return [_row(row) for row in rows if _row(row)]
