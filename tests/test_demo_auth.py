from lux.server import auth


def test_demo_auth_accepts_non_empty_credentials(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(auth, "DATA_DIR", tmp_path)
    monkeypatch.setattr(auth, "DB_FILE", tmp_path / "lux.db")
    monkeypatch.setenv("LUX_DEMO_AUTH", "true")

    token = auth.login("any@example.com", "anything")

    assert auth.user_for_token(token)
