from __future__ import annotations

import logging
import os
import subprocess
from pathlib import Path

from openhands.sdk import LLM, Agent, Conversation, Tool
from openhands.tools.file_editor import FileEditorTool
from openhands.tools.task_tracker import TaskTrackerTool
from openhands.tools.terminal import TerminalTool

from . import jobs

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
            model=os.getenv("LLM_MODEL") or os.getenv("OPENAI_MODEL") or "nvidia/nemotron-3-ultra-550b-a55b:free",
            api_key=os.getenv("LLM_API_KEY") or os.getenv("OPENAI_API_KEY"),
            base_url=os.getenv("LLM_BASE_URL") or os.getenv("OPENAI_BASE_URL") or "https://openrouter.ai/api/v1",
        )
        agent = Agent(llm=llm, tools=[
            Tool(name=TerminalTool.name),
            Tool(name=FileEditorTool.name),
            Tool(name=TaskTrackerTool.name),
        ])
        conversation = Conversation(agent=agent, workspace=str(workspace))
        conversation.send_message(job["prompt"])
        conversation.run()
        latest = jobs.get(job_id)
        if latest and latest["status"] == "cancelled":
            return
        jobs.update(job_id, status="succeeded")
    except Exception as exc:
        logger.exception("Job %s failed", job_id)
        jobs.update(job_id, status="failed", error=f"{type(exc).__name__}: {exc}"[:4000])
