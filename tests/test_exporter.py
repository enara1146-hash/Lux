from zipfile import ZipFile

from lux.server.exporter import export_workspace


def test_web_export_creates_bundle(tmp_path) -> None:
    (tmp_path / "index.html").write_text("<h1>Lux</h1>", encoding="utf-8")

    result = export_workspace(tmp_path, ["web"], timeout=10)

    assert result["status"] == "passed"
    with ZipFile(tmp_path / "exports" / "webapp.zip") as archive:
        assert "index.html" in archive.namelist()
