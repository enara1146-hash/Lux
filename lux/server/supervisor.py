from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

from . import settings


@dataclass(frozen=True)
class SupervisorConfig:
    max_iterations: int
    max_repairs: int
    test_timeout: int


def _bounded_int(name: str, default: int, minimum: int, maximum: int) -> int:
    raw = settings.effective(name, str(default))
    try:
        return max(minimum, min(maximum, int(raw or default)))
    except (TypeError, ValueError):
        return default


def load_config() -> SupervisorConfig:
    return SupervisorConfig(
        max_iterations=_bounded_int("LUX_MAX_ITERATIONS", 80, 1, 500),
        max_repairs=_bounded_int("LUX_MAX_REPAIRS", 2, 0, 5),
        test_timeout=_bounded_int("LUX_TEST_TIMEOUT", 300, 10, 1800),
    )


def task_plan(prompt: str) -> list[dict[str, str]]:
    """Create a small, persisted execution graph visible to the user."""
    return [
        {"id": "inspect", "title": "Inspect the workspace", "status": "pending", "acceptance": "Relevant files and existing tests are identified."},
        {"id": "implement", "title": "Implement the requested change", "status": "pending", "acceptance": "The requested behavior is implemented in the workspace."},
        {"id": "verify", "title": "Run acceptance checks", "status": "pending", "acceptance": "Syntax checks, tests, and bounded smoke checks pass."},
        {"id": "report", "title": "Prepare the result", "status": "pending", "acceptance": "The response summarizes changes, checks, and artifacts."},
    ]


def execution_prompt(prompt: str) -> str:
    return (
        prompt
        + "\n\nWork autonomously through this sequence: inspect the workspace, make a concise "
        "plan, implement the change, run relevant tests, and perform a bounded smoke test when "
        "an application is created or changed. Treat the requested behavior as the acceptance "
        "criterion. Report observed output and failures. Do not leave a long-running server "
        "process running after the smoke test."
    )


def repair_prompt(verification: dict[str, Any]) -> str:
    output = str(verification.get("output", ""))[-6000:]
    return (
        "The automated checks failed. Diagnose the failure, repair the implementation, and rerun "
        "the relevant checks. Do not stop at describing the problem. Failure output:\n\n"
        + output
    )


def phase_event(phase: str, detail: str) -> dict[str, str]:
    return {"type": "activity", "phase": phase, "text": detail}


def env_is_configured() -> bool:
    return bool(os.getenv("LLM_API_KEY") or os.getenv("OPENAI_API_KEY"))
