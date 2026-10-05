from lux.server import supervisor


def test_task_plan_has_acceptance_driven_stages() -> None:
    plan = supervisor.task_plan("Build a todo app")
    assert [task["id"] for task in plan] == ["inspect", "implement", "verify", "report"]
    assert all(task["status"] == "pending" for task in plan)
    assert all(task["acceptance"] for task in plan)
