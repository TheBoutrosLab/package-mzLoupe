"""Project editing uses the same configuration and leaves the active run intact."""

from pathlib import Path
import time
from typing import Any

from fastapi.testclient import TestClient
import pytest

from mzloupe.app import create_app
from mzloupe.demo import DemoProject
from mzloupe.models import ProjectInput
from mzloupe.services import project_files


@pytest.fixture
def configuration() -> dict[str, Any]:
    """Describe a saveable draft whose source files need not exist yet."""
    return {
        "name": "Remote draft",
        "acquisitions": [
            {"id": "run1", "sample": "Sample 1", "fraction": "F01", "mzml": "missing.mzML"}
        ],
        "samples": [
            {
                "name": "Sample 1",
                "identifications": [{"name": "Validated", "path": "missing.idXML"}],
            }
        ],
    }


def test_save_project_on_server_preserves_paths_and_ids(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Write a reusable server manifest in another directory without activating it."""
    manifest = DemoProject().write(tmp_path / "data")
    configuration = ProjectInput.load(manifest).model_dump()
    configuration["name"] = "Remote project – E. coli"
    configuration["acquisitions"][0]["mzml"] = "data/fraction_01.mzML"
    configuration["samples"][0]["identifications"][0]["path"] = "data/sample_Search.idXML"
    configuration["acquisitions"][0]["aliases"] = ["original_run.raw"]
    directory = tmp_path / "exports"
    directory.mkdir()
    monkeypatch.chdir(tmp_path)
    with TestClient(create_app(tmp_path / "cache")) as client:
        before = client.get("/api/status").json()
        response = client.post(
            "/api/save-project",
            json={"directory": str(directory), "filename": "remote.json", "project": configuration},
        )
        assert response.status_code == 200, response.text
        path = directory / "remote.json"
        assert response.json() == {"path": str(path)}
        saved = ProjectInput.load(path)
        assert saved.name == configuration["name"]
        assert saved.acquisitions[0].mzml == str(manifest.parent / "fraction_01.mzML")
        assert saved.acquisitions[0].aliases == ["original_run.raw"]
        assert saved.samples[0].identifications[0].path == str(
            manifest.parent / "sample_Search.idXML"
        )
        assert [row.id for row in saved.acquisitions] == [
            row["id"] for row in configuration["acquisitions"]
        ]
        assert path.read_text().endswith("\n")
        assert client.get("/api/status").json() == before
        assert client.get("/api/configuration").json() is None
    assert not list(directory.glob(".mzloupe-*.tmp"))


def test_save_requires_explicit_replacement_and_keeps_active_session(tmp_path: Path) -> None:
    """Protect an existing file and keep the loaded project unchanged after a save."""
    manifest = DemoProject().write(tmp_path / "data")
    project = ProjectInput.load(manifest)
    path = tmp_path / "saved.json"
    path.write_text("original contents")
    configuration = project.model_dump()
    configuration["name"] = "Saved edits"
    request = {"directory": str(tmp_path), "filename": path.name, "project": configuration}
    with TestClient(create_app(tmp_path / "cache")) as client:
        client.app.state.runtime.prepare(project)
        before = client.get("/api/status").json()
        assert before["state"] == "ready"
        response = client.post("/api/save-project", json=request)
        assert response.status_code == 409
        assert path.read_text() == "original contents"
        assert not list(tmp_path.glob(".mzloupe-*.tmp"))
        response = client.post("/api/save-project", json={**request, "overwrite": True})
        assert response.status_code == 200, response.text
        assert ProjectInput.load(path).name == "Saved edits"
        assert client.get("/api/status").json() == before
        assert client.get("/api/configuration").json()["name"] == project.name


@pytest.mark.parametrize(
    "filename", ["project.txt", "../escape.json", "sub/file.json", "sub\\file.json"]
)
def test_save_rejects_non_json_or_non_basename_targets(
    tmp_path: Path,
    configuration: dict[str, Any],
    filename: str,
) -> None:
    """Require JSON output and keep directory navigation in its separate input."""
    with TestClient(create_app(tmp_path / "cache")) as client:
        response = client.post(
            "/api/save-project",
            json={"directory": str(tmp_path), "filename": filename, "project": configuration},
        )
        assert response.status_code == 400
    assert not list(tmp_path.glob(".mzloupe-*.tmp"))


def test_save_draft_with_missing_sources_and_home_directory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    configuration: dict[str, Any],
) -> None:
    """Use the server's home directory and preserve drafts with unresolved file paths."""
    original_expanduser = Path.expanduser

    def expand_server_home(path: Path) -> Path:
        """Resolve the server home in this test without changing process environment variables."""
        return tmp_path if str(path) == "~" else original_expanduser(path)

    monkeypatch.setattr(Path, "expanduser", expand_server_home)
    with TestClient(create_app(tmp_path / "cache")) as client:
        response = client.post(
            "/api/save-project",
            json={"directory": "~", "filename": "draft.json", "project": configuration},
        )
        assert response.status_code == 200, response.text
        assert response.json()["path"] == str(tmp_path / "draft.json")
        saved = ProjectInput.load(tmp_path / "draft.json", validate_files=False)
        assert saved.file_issues()
        assert client.get("/api/status").json()["state"] == "empty"


def test_save_rejects_missing_directory(
    tmp_path: Path,
    configuration: dict[str, Any],
) -> None:
    """Report a missing output directory without creating it implicitly."""
    directory = tmp_path / "absent"
    with TestClient(create_app(tmp_path / "cache")) as client:
        response = client.post(
            "/api/save-project",
            json={"directory": str(directory), "filename": "draft.json", "project": configuration},
        )
        assert response.status_code == 400
    assert not directory.exists()


def test_failed_replace_keeps_original_file_and_cleans_temporary_data(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    configuration: dict[str, Any],
) -> None:
    """Leave the existing JSON intact if the filesystem rejects the final replacement."""
    path = tmp_path / "original.json"
    path.write_text("original contents")

    def reject_replace(_source: str | Path, _destination: str | Path) -> None:
        """Simulate an output permission failure after temporary data was written."""
        raise PermissionError("Permission denied")

    monkeypatch.setattr(project_files.os, "replace", reject_replace)
    with TestClient(create_app(tmp_path / "cache")) as client:
        response = client.post(
            "/api/save-project",
            json={
                "directory": str(tmp_path),
                "filename": path.name,
                "project": configuration,
                "overwrite": True,
            },
        )
        assert response.status_code == 400
        assert "Permission denied" in response.json()["detail"]
    assert path.read_text() == "original contents"
    assert not list(tmp_path.glob(".mzloupe-*.tmp"))


def test_open_configuration_without_manifest_and_reject_bad_paths(tmp_path: Path) -> None:
    """Open editor configuration directly and preserve the session on invalid paths."""
    manifest = DemoProject().write(tmp_path / "data")
    configuration = ProjectInput.load(manifest).model_dump()
    manifest.unlink()
    with TestClient(create_app(tmp_path / "cache")) as client:
        assert client.get("/api/configuration").json() is None
        assert client.post("/api/validate-project", json=configuration).json() == {"issues": []}
        assert client.post("/api/open-configuration", json=configuration).status_code == 202
        for _ in range(100):
            status = client.get("/api/status").json()
            if status["state"] != "preparing":
                break
            time.sleep(0.05)
        assert status["state"] == "ready", status
        assert client.get("/api/configuration").json() == configuration
        configuration["acquisitions"][0]["mzml"] = str(tmp_path / "missing.mzML")
        issues = client.post("/api/validate-project", json=configuration).json()["issues"]
        assert issues[0]["id"] == "fraction_01"
        assert issues[0]["field"] == "mzml"
        assert client.post("/api/open-configuration", json=configuration).status_code == 400
        assert client.get("/api/status").json()["token"] == status["token"]


def test_json_import_is_staged_and_duplicate_fraction_is_rejected(tmp_path: Path) -> None:
    """Stage manifest imports without opening them and reject duplicate fractions."""
    manifest = DemoProject().write(tmp_path / "data")
    with TestClient(create_app(tmp_path / "cache")) as client:
        response = client.post("/api/import-project", json={"path": str(manifest)})
        assert response.status_code == 200
        configuration = response.json()
        assert configuration["acquisitions"][0]["mzml"].startswith(str(tmp_path))
        assert client.get("/api/status").json()["state"] == "empty"
        configuration["acquisitions"][1]["fraction"] = configuration["acquisitions"][0]["fraction"]
        assert client.post("/api/open-configuration", json=configuration).status_code == 422
        assert client.get("/api/status").json()["state"] == "empty"


def test_file_browser_filters_sources_and_keeps_directories(tmp_path: Path) -> None:
    """List supported source files alongside directories and reject invalid requests."""
    for name in ("run.mzML", "run.mzML.gz", "result.idXML", "project.json", "other.txt"):
        (tmp_path / name).write_text("")
    (tmp_path / "subdirectory").mkdir()
    with TestClient(create_app(tmp_path / "cache")) as client:
        result = client.get("/api/files", params={"path": str(tmp_path), "kind": "mzml"}).json()
        files = {row["name"] for row in result["entries"] if not row["directory"]}
        assert files == {"run.mzML", "run.mzML.gz"}
        assert any(row["name"] == "subdirectory" and row["directory"] for row in result["entries"])
        directories = client.get(
            "/api/files",
            params={"path": str(tmp_path), "kind": "directory"},
        ).json()
        assert directories["entries"]
        assert all(entry["directory"] for entry in directories["entries"])
        assert (
            client.get("/api/files", params={"path": str(tmp_path / "missing")}).status_code == 400
        )
        assert (
            client.get(
                "/api/files", params={"path": str(tmp_path), "kind": "unsupported"}
            ).status_code
            == 400
        )
