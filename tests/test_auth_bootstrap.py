from lux.server import auth


def test_bootstrap_admin_uses_environment_secret(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(auth, "DATA_DIR", tmp_path)
    monkeypatch.setattr(auth, "DB_FILE", tmp_path / "lux.db")
    monkeypatch.setenv("LUX_DEFAULT_ADMIN_EMAIL", "admin@admin.com")
    monkeypatch.setenv("LUX_DEFAULT_ADMIN_PASSWORD", "test-password-123")

    auth.bootstrap_admin()

    assert auth.login("admin@admin.com", "test-password-123")
