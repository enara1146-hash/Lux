from lux.server import jobs


def test_recover_on_startup_requeues_queued_and_fails_running(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(jobs, "DATA_DIR", tmp_path)
    monkeypatch.setattr(jobs, "DB_FILE", tmp_path / "lux.db")

    queued = jobs.create("queued task", "demo")
    running = jobs.create("running task", "demo")
    jobs.update(running["id"], status="running", phase="implementation")

    resumed = jobs.recover_on_startup()

    assert resumed == [queued["id"]]
    assert jobs.get(queued["id"])["status"] == "queued"
    failed = jobs.get(running["id"])
    assert failed["status"] == "failed"
    assert failed["phase"] == "failed"
    assert "service restarted" in failed["error"]


def test_claim_next_is_atomic_and_marks_worker() -> None:
    jobs.create("claim me", "demo")
    first = jobs.claim_next("worker-a")
    assert first is not None
    assert first["status"] == "claimed"
    assert first["worker_id"] == "worker-a"
    assert jobs.claim_next("worker-b") is None
