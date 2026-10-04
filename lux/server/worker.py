from __future__ import annotations

import os
import logging
from pathlib import Path

from openhands.sdk import Agent, Conversation, LLM, Tool
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
    try:
        llm = LLM(
            model=os.getenv("LLM_MODEL") or os.getenv("OPENAI_MODEL") or "gpt-4o-mini",
            api_key=os.getenv("LLM_API_KEY") or os.getenv("OPENAI_API_KEY"),
            base_url=os.getenv("LLM_BASE_URL") or os.getenv("OPENAI_BASE_URL"),
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
