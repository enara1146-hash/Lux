from lux.server import worker


class _FakeConversation:
    def __init__(self) -> None:
        self.interrupted = False

    def interrupt(self) -> None:
        self.interrupted = True


def test_cancel_interrupts_active_conversation() -> None:
    conversation = _FakeConversation()
    with worker._ACTIVE_LOCK:
        worker._ACTIVE_CONVERSATIONS["job-1"] = conversation  # type: ignore[assignment]
    try:
        assert worker.cancel("job-1") is True
        assert conversation.interrupted is True
    finally:
        with worker._ACTIVE_LOCK:
            worker._ACTIVE_CONVERSATIONS.pop("job-1", None)


def test_cancel_returns_false_for_unknown_job() -> None:
    assert worker.cancel("missing-job") is False
