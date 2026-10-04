from __future__ import annotations

import os
import secrets
from pathlib import Path
from typing import Annotated

from fastapi import Depends, FastAPI, Header, HTTPException
from pydantic import BaseModel, Field

app = FastAPI(title="Lux", version="0.3.5")
DATA_DIR = Path(os.getenv("LUX_DATA_DIR", "/data")).resolve()
API_KEY = os.getenv("LUX_API_KEY")


def require_key(x_lux_key: Annotated[str | None, Header()] = None) -> None:
    if API_KEY and not x_lux_key:
        raise HTTPException(status_code=401, detail="X-Lux-Key is required")
    if API_KEY and not secrets.compare_digest(x_lux_key or "", API_KEY):
        raise HTTPException(status_code=403, detail="Invalid API key")


class JobRequest(BaseModel):
    prompt: str = Field(min_length=1, max_length=20_000)
    project_name: str = Field(default="default", pattern=r"^[A-Za-z0-9._-]{1,80}$")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/api/jobs", dependencies=[Depends(require_key)])
def create_job(request: JobRequest) -> dict[str, str]:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    job_id = secrets.token_urlsafe(16)
    return {"id": job_id, "status": "queued", "project_name": request.project_name}
