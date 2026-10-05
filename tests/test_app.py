from fastapi import HTTPException

from lux.server import app


def test_api_key_is_enforced_without_multi_user_auth(monkeypatch) -> None:
    monkeypatch.setattr(app, "API_KEY", "request-secret")
    monkeypatch.setattr(app, "AUTH_ENABLED", False)

    try:
        app.require_key("wrong", None)
    except HTTPException as exc:
        assert exc.status_code == 403
    else:
        raise AssertionError("invalid API key was accepted")

    app.require_key("request-secret", None)
