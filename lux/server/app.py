from __future__ import annotations

import os
import secrets
from typing import Annotated

from fastapi import Depends, FastAPI, Header, HTTPException
from pydantic import BaseModel, Field

from . import jobs

app = FastAPI(title="Lux", version="0.3.5")
API_KEY = os.getenv("LUX_API_KEY")


def require_key(x_lux_key: Annotated[str | None, Header()] = None) -> None:
    if API_KEY and not x_lux_key:
        raise HTTPException(status_code=401, detail="X-Lux-Key is required")
    if API_KEY and not secrets.compare_digest(x_lux_key or "", API_KEY):
        raise HTTPException(status_code=403, detail="Invalid API key")


class JobRequest(BaseModel):
    prompt: str = Field(min_length=1, max_length=20_000)
    project_name: str = Field(default="default", pattern=r"^[A-Za-z0-9._-]{1,80}$")


class ApprovalRequest(BaseModel):
    approve: bool
    reason: str | None = Field(default=None, max_length=2000)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/api/jobs", dependencies=[Depends(require_key)])
def create_job(request: JobRequest) -> dict:
    return jobs.create(request.prompt, request.project_name)


@app.get("/api/jobs/{job_id}", dependencies=[Depends(require_key)])
def get_job(job_id: str) -> dict:
    job = jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


@app.post("/api/jobs/{job_id}/approval", dependencies=[Depends(require_key)])
def approve_job(job_id: str, request: ApprovalRequest) -> dict:
    job = jobs.approve(job_id, request.approve)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


@app.post("/api/jobs/{job_id}/cancel", dependencies=[Depends(require_key)])
def cancel_job(job_id: str) -> dict:
    job = jobs.cancel(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return job
