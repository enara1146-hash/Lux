from lux.server import app as app_module, artifacts


def test_web_preview_serves_requested_workspace_file(tmp_path, monkeypatch) -> None:
    workspace = tmp_path / "projects" / "demo" / "job-1"
    workspace.mkdir(parents=True)
    (workspace / "index.html").write_text("<h1>Preview</h1>", encoding="utf-8")
    monkeypatch.setattr(artifacts, "DATA_DIR", tmp_path)
    monkeypatch.setattr(
        app_module.jobs,
        "get",
        lambda _job_id: {"id": "job-1", "project_name": "demo", "export_targets": ["web"]},
    )

    response = app_module.preview_webapp("job-1")

    assert response.media_type == "text/html"
    assert response.path.endswith("index.html")
