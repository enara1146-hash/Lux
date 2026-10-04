from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path
from typing import Any

DATA_DIR = Path(os.getenv("LUX_DATA_DIR", "/data")).resolve()
JOBS_FILE = DATA_DIR / "jobs.json"
_lock = threading.Lock()


def _read() -> dict[str, dict[str, Any]]:
    try:
        return json.loads(JOBS_FILE.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}


def _write(data: dict[str, dict[str, Any]]) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    tmp = JOBS_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
    tmp.replace(JOBS_FILE)


def create(prompt: str, project_name: str) -> dict[str, Any]:
    import secrets
    job = {"id": secrets.token_urlsafe(16), "prompt": prompt, "project_name": project_name,
           "status": "queued", "created_at": time.time(), "updated_at": time.time()}
    with _lock:
        data = _read()
        data[job["id"]] = job
        _write(data)
    return job


def get(job_id: str) -> dict[str, Any] | None:
    with _lock:
        return _read().get(job_id)


def approve(job_id: str, approved: bool) -> dict[str, Any] | None:
    with _lock:
        data = _read()
        job = data.get(job_id)
        if not job:
            return None
        if job["status"] != "waiting_for_approval":
            return job
        job["status"] = "queued" if approved else "cancelled"
        job["approval"] = approved
        job["updated_at"] = time.time()
        _write(data)
        return job


def request_approval(job_id: str, reason: str) -> dict[str, Any] | None:
    with _lock:
        data = _read()
        job = data.get(job_id)
        if not job:
            return None
        job["status"] = "waiting_for_approval"
        job["approval_reason"] = reason[:2000]
        job["updated_at"] = time.time()
        _write(data)
        return job


def cancel(job_id: str) -> dict[str, Any] | None:
    with _lock:
        data = _read()
        job = data.get(job_id)
        if not job:
            return None
        if job["status"] in {"queued", "running", "waiting_for_approval"}:
            job["status"] = "cancelled"
            job["updated_at"] = time.time()
            _write(data)
        return job
