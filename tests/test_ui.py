from lux.server.app import browser_ui


def test_browser_ui_injects_auth_mode() -> None:
    response = browser_ui()
    html = response.body.decode("utf-8")
    assert "__LUX_AUTH_ENABLED__" not in html
    assert "themeToggle" in html
    assert "authOverlay" in html
