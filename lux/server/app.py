from __future__ import annotations

import json
import logging
import mimetypes
import os
import secrets
import threading
import time
from pathlib import Path
from typing import Annotated, Literal
from urllib.parse import urlparse

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.responses import FileResponse, HTMLResponse, StreamingResponse
from pydantic import BaseModel, Field

from . import artifacts, auth, jobs, settings, supervisor

app = FastAPI(title="Lux", version="0.3.5")
API_KEY = os.getenv("LUX_API_KEY")
AUTH_ENABLED = os.getenv("LUX_AUTH_ENABLED", "false").lower() == "true"
logging.basicConfig(level=os.getenv("LUX_LOG_LEVEL", "INFO"))
logger = logging.getLogger("lux.api")


def current_user(authorization: Annotated[str | None, Header()] = None) -> str | None:
    if not AUTH_ENABLED:
        return None
    token = authorization.removeprefix("Bearer ").strip() if authorization else None
    user_id = auth.user_for_token(token)
    if not user_id:
        raise HTTPException(status_code=401, detail="Login required")
    return user_id


def require_key(x_lux_key: Annotated[str | None, Header()] = None, authorization: Annotated[str | None, Header()] = None) -> None:
    bearer = authorization.removeprefix("Bearer ").strip() if authorization else None
    supplied = x_lux_key or bearer
    if not API_KEY:
        if AUTH_ENABLED:
            raise HTTPException(status_code=503, detail="Lux authentication is enabled but LUX_API_KEY is not configured")
        return
    if not supplied:
        raise HTTPException(status_code=401, detail="API key is required")
    if not secrets.compare_digest(supplied or "", API_KEY):
        raise HTTPException(status_code=403, detail="Invalid API key")


def _start_job(job_id: str) -> None:
    from .worker import run as run_job

    worker_thread = threading.Thread(
        target=run_job,
        args=(job_id,),
        daemon=True,
        name=f"lux-worker-{job_id}",
    )
    worker_thread.start()
    logger.info("Started worker thread %s for job %s", worker_thread.name, job_id)


@app.on_event("startup")
def recover_jobs() -> None:
    auth.bootstrap_admin()
    if os.getenv("LUX_EXTERNAL_WORKER", "false").lower() == "true":
        jobs.recover_on_startup()
        return
    queued_ids = jobs.recover_on_startup()
    for job_id in queued_ids:
        try:
            _start_job(job_id)
        except Exception:
            logger.exception("Unable to resume queued job %s after startup", job_id)
            jobs.update(job_id, status="failed", phase="failed", error="Unable to resume queued job")


class JobRequest(BaseModel):
    prompt: str = Field(min_length=1, max_length=20_000)
    project_name: str = Field(default="default", pattern=r"^[A-Za-z0-9._-]{1,80}$")
    repository_url: str | None = Field(default=None, max_length=500)
    export_targets: list[Literal["web", "exe", "apk"]] = Field(default_factory=list, max_length=3)


class AdminUpdate(BaseModel):
    model: str | None = Field(default=None, max_length=200)
    base_url: str | None = Field(default=None, max_length=500)
    api_key: str | None = Field(default=None, max_length=500)
    auth_enabled: bool | None = None
    max_repairs: int | None = Field(default=None, ge=0, le=5)


class AuthRequest(BaseModel):
    email: str = Field(min_length=3, max_length=320)
    password: str = Field(min_length=12, max_length=200)


class ApprovalRequest(BaseModel):
    approve: bool
    reason: str | None = Field(default=None, max_length=2000)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/api/jobs", dependencies=[Depends(require_key)])
def create_job(request: JobRequest, user_id: str | None = Depends(current_user)) -> dict:
    if request.repository_url:
        parsed = urlparse(request.repository_url)
        if parsed.scheme != "https" or parsed.netloc != "github.com":
            raise HTTPException(status_code=422, detail="repository_url must be an HTTPS GitHub URL")
    logger.info("Creating job for project %s", request.project_name)
    job = jobs.create(request.prompt, request.project_name, user_id)
    job = jobs.update(
        job["id"],
        plan=supervisor.task_plan(request.prompt),
        export_targets=request.export_targets,
    ) or job
    if request.repository_url:
        job = jobs.update(job["id"], repository_url=request.repository_url) or job
    try:
        if os.getenv("LUX_EXTERNAL_WORKER", "false").lower() == "true":
            logger.info("Queued job %s for external worker", job["id"])
        else:
            _start_job(job["id"])
    except Exception as exc:
        logger.exception("Unable to start job %s", job["id"])
        jobs.update(job["id"], status="failed", error=f"{type(exc).__name__}: {exc}"[:4000])
    return jobs.get(job["id"]) or job


@app.get("/api/jobs", dependencies=[Depends(require_key)])
def list_jobs(user_id: str | None = Depends(current_user)) -> list[dict]:
    items = jobs.recent(100)
    if AUTH_ENABLED:
        items = [item for item in items if item.get("owner_id") == user_id]
    return items


@app.get("/api/jobs/{job_id}", dependencies=[Depends(require_key)])
def get_job(job_id: str, user_id: str | None = Depends(current_user)) -> dict:
    job = jobs.get(job_id)
    if not job or (AUTH_ENABLED and job.get("owner_id") != user_id):
        raise HTTPException(status_code=404, detail="Job not found")
    return job


@app.post("/api/jobs/{job_id}/approval", dependencies=[Depends(require_key)])
def approve_job(job_id: str, request: ApprovalRequest, user_id: str | None = Depends(current_user)) -> dict:
    job = jobs.get(job_id)
    if not job or (AUTH_ENABLED and job.get("owner_id") != user_id):
        raise HTTPException(status_code=404, detail="Job not found")
    job = jobs.approve(job_id, request.approve)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


@app.post("/api/jobs/{job_id}/cancel", dependencies=[Depends(require_key)])
def cancel_job(job_id: str, user_id: str | None = Depends(current_user)) -> dict:
    job = jobs.get(job_id)
    if not job or (AUTH_ENABLED and job.get("owner_id") != user_id):
        raise HTTPException(status_code=404, detail="Job not found")
    try:
        from .worker import cancel as cancel_worker
        cancel_worker(job_id)
    except Exception:
        logger.exception("Unable to interrupt worker for job %s", job_id)
    job = jobs.cancel(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    job = jobs.update(job_id, phase="cancelled") or job
    return job


@app.get("/api/jobs/{job_id}/artifacts", dependencies=[Depends(require_key)])
def list_artifacts(job_id: str, user_id: str | None = Depends(current_user)) -> list[dict]:
    job = jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return artifacts.list_files(job)


@app.get("/api/jobs/{job_id}/preview", dependencies=[Depends(require_key)])
@app.get("/api/jobs/{job_id}/preview/{path:path}", dependencies=[Depends(require_key)])
def preview_webapp(job_id: str, path: str = "index.html", user_id: str | None = Depends(current_user)) -> FileResponse:
    job = jobs.get(job_id)
    if not job or (AUTH_ENABLED and job.get("owner_id") != user_id):
        raise HTTPException(status_code=404, detail="Job not found")
    if "web" not in job.get("export_targets", []):
        raise HTTPException(status_code=404, detail="Web preview was not requested")
    file_path = artifacts.resolve_file(job, path)
    media_type = mimetypes.guess_type(file_path.name)[0] or "application/octet-stream"
    return FileResponse(file_path, media_type=media_type)


@app.get("/api/jobs/{job_id}/artifact", dependencies=[Depends(require_key)])
def download_artifact(job_id: str, path: str, user_id: str | None = Depends(current_user)) -> FileResponse:
    job = jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    file_path = artifacts.resolve_file(job, path)
    return FileResponse(file_path, filename=file_path.name)


@app.get("/", response_class=HTMLResponse)
def browser_ui() -> HTMLResponse:
    page = Path(__file__).with_name("index.html").read_text(encoding="utf-8")
    page = page.replace("__LUX_AUTH_ENABLED__", str(AUTH_ENABLED).lower())
    return HTMLResponse(page)


@app.post("/api/auth/register")
def register(request: AuthRequest) -> dict:
    try:
        return auth.register(request.email, request.password)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.post("/api/auth/login")
def login(request: AuthRequest) -> dict[str, str]:
    try:
        return {"token": auth.login(request.email, request.password)}
    except ValueError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc


@app.get("/api/jobs/{job_id}/stream", dependencies=[Depends(require_key)])
def stream_job(job_id: str, user_id: str | None = Depends(current_user)) -> StreamingResponse:
    job = jobs.get(job_id)
    if not job or (AUTH_ENABLED and job.get("owner_id") != user_id):
        raise HTTPException(status_code=404, detail="Job not found")

    def events():
        last = None
        event_index = 0
        while True:
            current = jobs.get(job_id)
            if not current:
                yield "event: error\ndata: " + json.dumps({"error": "Job not found"}) + "\n\n"
                return
            snapshot = {
                "id": current["id"],
                "status": current["status"],
                "error": current.get("error"),
                "phase": current.get("phase"),
                "attempt": current.get("attempt", 0),
                "iteration": current.get("iteration", 0),
                "elapsed_seconds": current.get("elapsed_seconds", 0),
                "max_repairs": current.get("max_repairs", 0),
                "verification": current.get("verification"),
                "plan": current.get("plan", []),
            }
            if snapshot != last:
                yield "event: job\ndata: " + json.dumps(snapshot) + "\n\n"
                last = snapshot
            for event in current.get("events", [])[event_index:]:
                kind = event.get("type", "message")
                yield f"event: {kind}\ndata: {json.dumps(event)}\n\n"
            event_index = len(current.get("events", []))
            if current["status"] in {"succeeded", "failed", "cancelled"}:
                return
            time.sleep(1)

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )

def require_admin(x_lux_admin_key: Annotated[str | None, Header()] = None) -> None:
    if not settings.valid_admin(x_lux_admin_key):
        raise HTTPException(status_code=403, detail="Admin access required")


@app.get("/admin", response_class=HTMLResponse)
@app.get("/admin/", response_class=HTMLResponse)
def admin_page() -> HTMLResponse:
    return HTMLResponse("""<!doctype html><html><head><title>Lux Admin</title>
    <style>body{font:15px system-ui;max-width:900px;margin:30px auto;background:#202020;color:#eee;padding:20px}
    input,button{padding:9px;margin:5px 0;width:100%;background:#303030;color:#eee;border:1px solid #555;border-radius:6px}
    pre{background:#151515;padding:15px;white-space:pre-wrap}</style></head><body>
    <h1>Lux Admin</h1><input id="key" type="password" placeholder="LUX_ADMIN_KEY">
    <button onclick="load()">Load configuration and operations</button>
    <input id="model" placeholder="Model"><input id="base" placeholder="OpenAI-compatible base URL">
    <input id="api" type="password" placeholder="Replace provider API key (leave blank to keep current)">
    <input id="repairs" type="number" min="0" max="5" placeholder="Automatic repair attempts">
    <button onclick="save()">Save configuration</button><pre id="out"></pre>
    <script>
    const h=()=>({'Content-Type':'application/json','X-Lux-Admin-Key':document.getElementById('key').value});
    async function load(){let r=await fetch('/admin/config',{headers:h()});let x=await r.json();out.textContent=JSON.stringify(x,null,2);if(r.ok){model.value=x.model||'';base.value=x.base_url||'';repairs.value=x.max_repairs??2}}
    async function save(){let r=await fetch('/admin/config',{method:'POST',headers:h(),body:JSON.stringify({model:model.value,base_url:base.value,api_key:api.value||null,max_repairs:Number(repairs.value)})});out.textContent=JSON.stringify(await r.json(),null,2)}
    </script></body></html>""")


@app.get("/admin/config", dependencies=[Depends(require_admin)])
def admin_config() -> dict:
    return settings.public_config()


@app.post("/admin/config", dependencies=[Depends(require_admin)])
def update_admin_config(request: AdminUpdate) -> dict:
    values = {"OPENAI_MODEL": request.model, "OPENAI_BASE_URL": request.base_url,
              "OPENAI_API_KEY": request.api_key,
              "LUX_MAX_REPAIRS": str(request.max_repairs) if request.max_repairs is not None else None}
    for name, value in values.items():
        if value:
            settings.set_value(name, value)
    if request.auth_enabled is not None:
        settings.set_value("LUX_AUTH_ENABLED", str(request.auth_enabled).lower())
    return settings.public_config()


@app.get("/admin/operations", dependencies=[Depends(require_admin)])
def admin_operations() -> list[dict]:
    return jobs.recent()
