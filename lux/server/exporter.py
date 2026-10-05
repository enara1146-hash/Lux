from __future__ import annotations

import os
import subprocess
import zipfile
from pathlib import Path
from typing import Any


def _run(command: list[str], cwd: Path, timeout: int) -> dict[str, Any]:
    try:
        result = subprocess.run(command, cwd=cwd, capture_output=True, text=True, check=False, timeout=timeout)
        return {"command": " ".join(command), "status": "passed" if result.returncode == 0 else "failed", "output": (result.stdout + "\\n" + result.stderr).strip()[-6000:]}
    except FileNotFoundError as exc:
        return {"command": " ".join(command), "status": "unavailable", "error": f"Toolchain unavailable: {exc.filename}"}
    except subprocess.TimeoutExpired:
        return {"command": " ".join(command), "status": "timed_out"}


def _web_bundle(workspace: Path) -> dict[str, Any]:
    output = workspace / "exports" / "webapp.zip"
    output.parent.mkdir(exist_ok=True)
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in workspace.rglob("*"):
            if not path.is_file() or any(part in {".git", ".venv", "exports"} for part in path.parts):
                continue
            archive.write(path, path.relative_to(workspace).as_posix())
    return {"target": "web", "status": "passed", "artifact": str(output.relative_to(workspace))}


def export_workspace(workspace: Path, targets: list[str], timeout: int) -> dict[str, Any]:
    results: list[dict[str, Any]] = []
    normalized = {target.lower() for target in targets}
    if "web" in normalized or "webapp" in normalized:
        results.append(_web_bundle(workspace))
    if "exe" in normalized:
        entry = os.getenv("LUX_EXE_ENTRY", "main.py")
        if not (workspace / entry).exists():
            results.append({"target": "exe", "status": "unavailable", "error": f"Entry file not found: {entry}"})
        else:
            result = _run(["python", "-m", "PyInstaller", "--onefile", "--name", "lux-app", entry], workspace, timeout)
            result.update({"target": "exe", "artifact": "dist/lux-app.exe" if result["status"] == "passed" else None})
            results.append(result)
    if "apk" in normalized:
        gradle = workspace / ("gradlew.bat" if os.name == "nt" else "gradlew")
        if not gradle.exists():
            results.append({"target": "apk", "status": "unavailable", "error": "Gradle wrapper not found"})
        else:
            command = [str(gradle), "assembleDebug"]
            result = _run(command, workspace, timeout)
            apk_files = list(workspace.glob("**/build/outputs/apk/**/*.apk"))
            result.update({"target": "apk", "artifact": str(apk_files[0].relative_to(workspace)) if apk_files else None})
            results.append(result)
    return {"status": "passed" if results and all(item["status"] == "passed" for item in results) else "failed", "targets": results}
