from __future__ import annotations

import logging
import os
import subprocess
import json
from pathlib import Path

from openhands.sdk import LLM, Agent, Conversation, Tool
from openhands.tools.file_editor import FileEditorTool
from openhands.tools.task_tracker import TaskTrackerTool
from openhands.tools.terminal import TerminalTool

from . import jobs, settings

DATA_DIR = Path(os.getenv("LUX_DATA_DIR", "/data")).resolve()
logger = logging.getLogger("lux.worker")


def run(job_id: str) -> None:
    job = jobs.get(job_id)
    if not job:
        return
    if job["status"] in {"cancelled", "waiting_for_approval"}:
        return
    workspace = (DATA_DIR / "projects" / job["project_name"] / job_id).resolve()
    workspace.mkdir(parents=True, exist_ok=True)
    jobs.update(job_id, status="running", workspace=str(workspace))
    repository_url = job.get("repository_url")
    if repository_url:
        try:
            subprocess.run(["git", "clone", "--depth", "1", repository_url, str(workspace)], check=True, timeout=180)
        except Exception as exc:
            logger.exception("Repository clone failed for job %s", job_id)
            jobs.update(job_id, status="failed", error=f"Repository clone failed: {exc}"[:4000])
            return
    try:
        llm = LLM(
            model=settings.effective("LLM_MODEL", settings.effective("OPENAI_MODEL", "nvidia/nemotron-3-ultra-550b-a55b:free")),
            api_key=settings.effective("LLM_API_KEY", settings.effective("OPENAI_API_KEY")),
            base_url=settings.effective("LLM_BASE_URL", settings.effective("OPENAI_BASE_URL", "https://openrouter.ai/api/v1")),
        )
        agent = Agent(llm=llm, tools=[
            Tool(name=TerminalTool.name),
            Tool(name=FileEditorTool.name),
            Tool(name=TaskTrackerTool.name),
        ])
        conversation = Conversation(agent=agent, workspace=str(workspace))
        conversation.send_message(job["prompt"])
        conversation.run()
        verification = _verify_workspace(workspace)
        jobs.update(job_id, verification=verification)
        latest = jobs.get(job_id)
        if latest and latest["status"] == "cancelled":
            return
        jobs.update(job_id, status="succeeded")
    except Exception as exc:
        logger.exception("Job %s failed", job_id)
        jobs.update(job_id, status="failed", error=f"{type(exc).__name__}: {exc}"[:4000])


def _verify_workspace(workspace: Path) -> dict[str, object]:
    if not (workspace / "tests").exists() and not list(workspace.glob("test_*.py")):
        return {"status": "skipped", "reason": "No pytest tests detected"}
    try:
        result = subprocess.run(
            ["python", "-m", "pytest", "-q"],
            cwd=workspace,
            capture_output=True,
            text=True,
            timeout=int(os.getenv("LUX_TEST_TIMEOUT", "300")),
        )
        output = (result.stdout + "\\n" + result.stderr)[-8000:]
        return {"status": "passed" if result.returncode == 0 else "failed",
                "return_code": result.returncode, "output": output}
    except subprocess.TimeoutExpired:
        return {"status": "timed_out", "timeout_seconds": int(os.getenv("LUX_TEST_TIMEOUT", "300"))}
    except Exception as exc:
        return {"status": "error", "error": f"{type(exc).__name__}: {exc}"}
