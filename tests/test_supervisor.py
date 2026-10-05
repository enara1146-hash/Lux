from lux.server import supervisor


def test_task_plan_has_acceptance_driven_stages() -> None:
    plan = supervisor.task_plan("Build a todo app")
    assert [task["id"] for task in plan] == ["inspect", "implement", "verify", "report"]
    assert all(task["status"] == "pending" for task in plan)
    assert all(task["acceptance"] for task in plan)


def test_config_uses_bounded_speed_defaults(monkeypatch) -> None:
    monkeypatch.delenv("LUX_MAX_ITERATIONS", raising=False)
    monkeypatch.delenv("LUX_JOB_TIMEOUT", raising=False)
    config = supervisor.load_config()
    assert config.max_iterations == 30
    assert config.job_timeout == 1800
