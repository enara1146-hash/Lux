from __future__ import annotations

import logging
import os
import secrets
import threading
from pathlib import Path
from typing import Annotated

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.responses import FileResponse, HTMLResponse
from pydantic import BaseModel, Field

from . import artifacts, jobs

app = FastAPI(title="Lux", version="0.3.5")
API_KEY = os.getenv("LUX_API_KEY")
AUTH_ENABLED = os.getenv("LUX_AUTH_ENABLED", "false").lower() == "true"
logging.basicConfig(level=os.getenv("LUX_LOG_LEVEL", "INFO"))
logger = logging.getLogger("lux.api")


def require_key(x_lux_key: Annotated[str | None, Header()] = None, authorization: Annotated[str | None, Header()] = None) -> None:
    bearer = authorization.removeprefix("Bearer ").strip() if authorization else None
    supplied = x_lux_key or bearer
    if not AUTH_ENABLED:
        return
    if not API_KEY:
        raise HTTPException(status_code=503, detail="Lux authentication is enabled but LUX_API_KEY is not configured")
    if not supplied:
        raise HTTPException(status_code=401, detail="API key is required")
    if not secrets.compare_digest(supplied or "", API_KEY):
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
    logger.info("Creating job for project %s", request.project_name)
    job = jobs.create(request.prompt, request.project_name)
    try:
        from .worker import run as run_job
        threading.Thread(target=run_job, args=(job["id"],), daemon=True).start()
    except Exception as exc:
        logger.exception("Unable to start job %s", job["id"])
        jobs.update(job["id"], status="failed", error=f"{type(exc).__name__}: {exc}"[:4000])
    return jobs.get(job["id"]) or job


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


@app.get("/api/jobs/{job_id}/artifacts", dependencies=[Depends(require_key)])
def list_artifacts(job_id: str) -> list[dict]:
    job = jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return artifacts.list_files(job)


@app.get("/api/jobs/{job_id}/artifact", dependencies=[Depends(require_key)])
def download_artifact(job_id: str, path: str) -> FileResponse:
    job = jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    file_path = artifacts.resolve_file(job, path)
    return FileResponse(file_path, filename=file_path.name)


@app.get("/", response_class=HTMLResponse)
def browser_ui() -> HTMLResponse:
    page = Path(__file__).with_name("index.html").read_text(encoding="utf-8")
    return HTMLResponse(page)
