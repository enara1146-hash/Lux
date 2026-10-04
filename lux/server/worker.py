from __future__ import annotations

import logging
import os
import subprocess
from pathlib import Path

from openhands.sdk import LLM, Agent, Conversation, Tool
from openhands.tools.file_editor import FileEditorTool
from openhands.tools.task_tracker import TaskTrackerTool
from openhands.tools.terminal import TerminalTool

from . import jobs, settings

DATA_DIR = Path(os.getenv("LUX_DATA_DIR", "/data")).resolve()
logger = logging.getLogger("lux.worker")


def _provider_model(model: str, base_url: str | None) -> str:
    if base_url and "openrouter.ai" in base_url and not model.startswith("openrouter/"):
        return "openrouter/" + model
    return model


def _content_text(content: object) -> str:
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return ""
    parts: list[str] = []
    for item in content:
        if isinstance(item, str):
            parts.append(item)
        else:
            text = getattr(item, "text", None)
            if isinstance(text, str):
                parts.append(text)
    return "".join(parts)


def _chunk_text(chunk: object) -> str:
    if isinstance(chunk, dict):
        choices = chunk.get("choices") or []
        if not choices:
            return ""
        first = choices[0]
        delta = first.get("delta") if isinstance(first, dict) else None
        content = delta.get("content") if isinstance(delta, dict) else None
        return _content_text(content)
    choices = getattr(chunk, "choices", None) or []
    if not choices:
        return ""
    delta = getattr(choices[0], "delta", None)
    return _content_text(getattr(delta, "content", None))


def _event_text(event: object) -> str:
    if getattr(event, "source", None) != "agent":
        return ""
    message = getattr(event, "llm_message", None)
    return _content_text(getattr(message, "content", None))


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
            subprocess.run(
                ["git", "clone", "--depth", "1", repository_url, str(workspace)],
                check=True,
                timeout=180,
            )
        except Exception as exc:
            logger.exception("Repository clone failed for job %s", job_id)
            jobs.update(job_id, status="failed", error=f"Repository clone failed: {exc}"[:4000])
            return
    try:
        base_url = settings.effective(
            "LLM_BASE_URL",
            settings.effective("OPENAI_BASE_URL", "https://openrouter.ai/api/v1"),
        )
        model = settings.effective(
            "LLM_MODEL",
            settings.effective("OPENAI_MODEL", "nvidia/nemotron-3-ultra-550b-a55b:free"),
        )
        llm = LLM(
            model=_provider_model(model or "", base_url),
            api_key=settings.effective("LLM_API_KEY", settings.effective("OPENAI_API_KEY")),
            base_url=base_url,
        )
        agent = Agent(
            llm=llm,
            tools=[
                Tool(name=TerminalTool.name),
                Tool(name=FileEditorTool.name),
                Tool(name=TaskTrackerTool.name),
            ],
        )
        streamed_text = False
        agent_messages: list[str] = []

        def token_callback(chunk: object) -> None:
            nonlocal streamed_text
            text = _chunk_text(chunk)
            if text:
                streamed_text = True
                jobs.append_event(job_id, {"type": "token", "text": text})

        def conversation_callback(event: object) -> None:
            text = _event_text(event)
            if text:
                agent_messages.append(text)

        conversation = Conversation(
            agent=agent,
            workspace=str(workspace),
            callbacks=[conversation_callback],
            token_callbacks=[token_callback],
        )
        conversation.send_message(job["prompt"])
        conversation.run()
        if not streamed_text and agent_messages:
            jobs.append_event(job_id, {"type": "message", "text": agent_messages[-1]})
        verification = _verify_workspace(workspace)
        jobs.update(job_id, verification=verification)
        latest = jobs.get(job_id)
        if latest and latest["status"] == "cancelled":
            return
        jobs.update(job_id, status="succeeded")
    except Exception as exc:
        logger.exception("Job %s failed", job_id)
        message = f"{type(exc).__name__}: {exc}"[:4000]
        jobs.append_event(job_id, {"type": "error", "text": message})
        jobs.update(job_id, status="failed", error=message)


def _verify_workspace(workspace: Path) -> dict[str, object]:
    if not (workspace / "tests").exists() and not list(workspace.glob("test_*.py")):
        return {"status": "skipped", "reason": "No pytest tests detected"}
    try:
        result = subprocess.run(
            ["python", "-m", "pytest", "-q"],
            cwd=workspace,
            capture_output=True,
            text=True,
            check=False,
            timeout=int(os.getenv("LUX_TEST_TIMEOUT", "300")),
        )
        output = (result.stdout + "\n" + result.stderr)[-8000:]
        return {
            "status": "passed" if result.returncode == 0 else "failed",
            "return_code": result.returncode,
            "output": output,
        }
    except subprocess.TimeoutExpired:
        return {
            "status": "timed_out",
            "timeout_seconds": int(os.getenv("LUX_TEST_TIMEOUT", "300")),
        }
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        return {"status": "error", "error": f"{type(exc).__name__}: {exc}"}
