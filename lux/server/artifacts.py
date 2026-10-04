from __future__ import annotations

import os
from pathlib import Path

from fastapi import HTTPException

DATA_DIR = Path(os.getenv("LUX_DATA_DIR", "/data")).resolve()
MAX_ARTIFACT_BYTES = int(os.getenv("LUX_MAX_ARTIFACT_BYTES", "10485760"))


def workspace(job: dict) -> Path:
    root = (DATA_DIR / "projects" / job["project_name"] / job["id"]).resolve()
    if not root.is_relative_to(DATA_DIR):
        raise HTTPException(status_code=400, detail="Invalid workspace")
    return root


def list_files(job: dict) -> list[dict[str, int | str]]:
    root = workspace(job)
    if not root.exists():
        return []
    result = []
    for path in root.rglob("*"):
        if path.is_file():
            size = path.stat().st_size
            if size <= MAX_ARTIFACT_BYTES:
                result.append({"path": path.relative_to(root).as_posix(), "size": size})
    return result


def resolve_file(job: dict, relative_path: str) -> Path:
    root = workspace(job)
    candidate = (root / relative_path).resolve()
    if not candidate.is_relative_to(root) or not candidate.is_file():
        raise HTTPException(status_code=404, detail="Artifact not found")
    if candidate.stat().st_size > MAX_ARTIFACT_BYTES:
        raise HTTPException(status_code=413, detail="Artifact exceeds size limit")
    return candidate
