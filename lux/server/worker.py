from __future__ import annotations

import logging
import os
import subprocess
import time
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


def _short_detail(value: object, limit: int = 160) -> str:
    text = str(value).replace("\n", " ").strip()
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _event_activity(event: object) -> str | None:
    event_name = type(event).__name__
    source = getattr(event, "source", None)
    if event_name == "ActionEvent":
        action = getattr(event, "action", None)
        action_name = type(action).__name__ if action is not None else "tool"
        if action is not None:
            for field in ("command", "path", "query", "task"):
                detail = getattr(action, field, None)
                if detail:
                    return f"Using {action_name}: {_short_detail(detail)}"
        return f"Using {action_name}"
    if event_name == "ObservationEvent":
        observation = getattr(event, "observation", None)
        observation_name = type(observation).__name__ if observation is not None else "result"
        return f"Completed {observation_name}"
    if event_name == "MessageEvent" and source == "agent":
        return "Agent prepared a response"
    if "Error" in event_name:
        return "Agent reported an error"
    return None


def run(job_id: str) -> None:
    try:
        job = jobs.get(job_id)
        if not job:
            logger.error("Job %s disappeared before worker startup", job_id)
            return
        if job["status"] in {"cancelled", "waiting_for_approval"}:
            return

        workspace = (DATA_DIR / "projects" / job["project_name"] / job_id).resolve()
        logger.info("Starting worker for job %s in %s", job_id, workspace)
        jobs.update(job_id, status="running", workspace=str(workspace))
        workspace.mkdir(parents=True, exist_ok=True)

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
                jobs.update(
                    job_id,
                    status="failed",
                    error=f"Repository clone failed: {exc}"[:4000],
                )
                return

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
        token_buffer: list[str] = []
        last_token_flush = time.monotonic()

        def flush_tokens() -> None:
            nonlocal last_token_flush
            if token_buffer:
                jobs.append_event(job_id, {"type": "token", "text": "".join(token_buffer)})
                token_buffer.clear()
                last_token_flush = time.monotonic()

        def token_callback(chunk: object) -> None:
            nonlocal streamed_text
            text = _chunk_text(chunk)
            if text:
                streamed_text = True
                token_buffer.append(text)
                if (
                    len("".join(token_buffer)) >= 160
                    or time.monotonic() - last_token_flush >= 0.2
                ):
                    flush_tokens()

        def conversation_callback(event: object) -> None:
            text = _event_text(event)
            if text:
                agent_messages.append(text)
            activity = _event_activity(event)
            if activity:
                jobs.append_event(job_id, {"type": "activity", "text": activity})

        conversation = Conversation(
            agent=agent,
            workspace=str(workspace),
            callbacks=[conversation_callback],
            token_callbacks=[token_callback],
            max_iteration_per_run=int(settings.effective("LUX_MAX_ITERATIONS", "80")),
        )
        execution_prompt = (
            job["prompt"]
            + "\n\nAfter implementing the task, run the relevant tests. If this creates or changes "
            "an application, perform a bounded smoke test of it and include the observed output "
            "and any failures in your final response. Do not leave a long-running server process "
            "running after the smoke test."
        )
        jobs.append_event(job_id, {"type": "activity", "text": "Planning implementation"})
        conversation.send_message(execution_prompt)
        max_repairs = max(0, int(os.getenv("LUX_MAX_REPAIRS", "2")))
        verification: dict[str, object] = {"status": "skipped"}
        for attempt in range(max_repairs + 1):
            if attempt:
                jobs.append_event(
                    job_id,
                    {
                        "type": "activity",
                        "text": f"Repair attempt {attempt} of {max_repairs}",
                    },
                )
                failure_output = str(verification.get("output", ""))[-6000:]
                conversation.send_message(
                    "The automated checks failed. Diagnose and repair the implementation, "
                    "then rerun the relevant checks. Failure output:\n\n"
                    + failure_output
                )
            conversation.run()
            flush_tokens()
            verification = _verify_workspace(workspace)
            if verification["status"] in {"passed", "skipped"}:
                break
            if attempt < max_repairs:
                jobs.append_event(
                    job_id,
                    {"type": "activity", "text": "Checks failed; preparing an automatic repair"},
                )
        if not streamed_text and agent_messages:
            jobs.append_event(job_id, {"type": "message", "text": agent_messages[-1]})
        jobs.update(job_id, verification=verification)
        latest = jobs.get(job_id)
        if latest and latest["status"] == "cancelled":
            return
        jobs.update(job_id, status="succeeded")
        logger.info("Worker completed job %s", job_id)
    except Exception as exc:
        logger.exception("Worker crashed for job %s", job_id)
        message = f"{type(exc).__name__}: {exc}"[:4000]
        try:
            jobs.append_event(job_id, {"type": "error", "text": message})
            jobs.update(job_id, status="failed", error=message)
        except Exception:
            logger.exception("Unable to persist failure for job %s", job_id)


def _run_check(
    workspace: Path,
    command: list[str],
    timeout: int,
) -> dict[str, object]:
    try:
        result = subprocess.run(
            command,
            cwd=workspace,
            capture_output=True,
            text=True,
            check=False,
            timeout=timeout,
        )
        output = (result.stdout + "\n" + result.stderr).strip()[-8000:]
        return {
            "command": " ".join(command),
            "status": "passed" if result.returncode == 0 else "failed",
            "return_code": result.returncode,
            "output": output,
        }
    except subprocess.TimeoutExpired:
        return {
            "command": " ".join(command),
            "status": "timed_out",
            "timeout_seconds": timeout,
        }
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        return {
            "command": " ".join(command),
            "status": "error",
            "error": f"{type(exc).__name__}: {exc}",
        }


def _verify_workspace(workspace: Path) -> dict[str, object]:
    timeout = int(os.getenv("LUX_TEST_TIMEOUT", "300"))
    checks: list[dict[str, object]] = []
    python_files = [
        path for path in workspace.rglob("*.py")
        if ".venv" not in path.parts and ".git" not in path.parts
    ]
    if python_files:
        checks.append(_run_check(workspace, ["python", "-m", "compileall", "-q", "."], timeout))

    has_tests = (workspace / "tests").exists() or bool(list(workspace.glob("test_*.py")))
    if has_tests:
        checks.append(_run_check(workspace, ["python", "-m", "pytest", "-q"], timeout))

    if not checks:
        return {
            "status": "skipped",
            "reason": "No Python application or pytest tests detected",
            "checks": [],
        }

    failed = [check for check in checks if check["status"] != "passed"]
    output_parts = [
        f"$ {check['command']}\n{check.get('output', check.get('error', ''))}"
        for check in checks
    ]
    return {
        "status": "failed" if failed else "passed",
        "checks": checks,
        "output": "\n\n".join(output_parts)[-12000:],
    }
