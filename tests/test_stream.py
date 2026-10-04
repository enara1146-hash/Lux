import asyncio

import lux.server.app as app_module


def test_stream_uses_valid_sse_frames(monkeypatch) -> None:
    job = {
        "id": "job-1",
        "status": "succeeded",
        "error": None,
        "verification": {"status": "skipped"},
        "events": [{"type": "token", "text": "Hello"}],
    }
    monkeypatch.setattr(app_module.jobs, "get", lambda _job_id: job)

    response = app_module.stream_job("job-1", user_id=None)
    async def collect_frames() -> list[str]:
        return [frame async for frame in response.body_iterator]

    frames = asyncio.run(collect_frames())

    assert frames[0].startswith("event: job\ndata: ")
    assert frames[0].endswith("\n\n")
    assert frames[1] == 'event: token\ndata: {"type": "token", "text": "Hello"}\n\n'
