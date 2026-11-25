"""Exercise durable project identity, incremental preparation, and failed update recovery."""

import gzip
import json
import os
from pathlib import Path
import shutil
import time

from fastapi.testclient import TestClient
import pytest

from mzloupe.app import create_app
from mzloupe.demo import DemoProject
from mzloupe.models import ProjectInput
from mzloupe.readers.idxml import IdXMLReader
from mzloupe.services.preparation import ProjectPreparer
from mzloupe.services.project_cache import ProjectCache


def finished(client: TestClient) -> dict:
    """Wait for a terminal preparation state without imposing a cold-start race."""
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        status = client.get("/api/status").json()
        if status["state"] != "preparing":
            return status
        time.sleep(0.02)
    pytest.fail("Project preparation did not finish")


def open_project(client: TestClient, project: ProjectInput) -> dict:
    """Save and open a definition through the same endpoint as the editor."""
    result = client.post("/api/open-configuration", json=project.model_dump())
    assert result.status_code == 202, result.text
    status = finished(client)
    assert status["state"] == "ready", status
    return status


def test_draft_library_archive_and_duplicate_survive_cache_removal(tmp_path: Path) -> None:
    """Save empty drafts and manage their history without requiring scientific inputs."""
    cache = tmp_path / "cache"
    registry = tmp_path / "state/projects.sqlite"
    with TestClient(create_app(cache, registry=registry)) as client:
        draft = client.post("/api/library", json={"name": "Pilot"}).json()
        assert draft["status"] == "draft" and draft["fractions"] == 0
        identifier = draft["id"]
        renamed = {**draft["configuration"], "name": "Renamed pilot"}
        result = client.post("/api/library", json=renamed).json()
        assert result["id"] == identifier and result["revision"] == 2
        duplicate = client.post(f"/api/library/{identifier}/duplicate").json()
        assert duplicate["id"] != identifier
        client.patch(f"/api/library/{identifier}", json={"archived": True}).raise_for_status()
        assert len(client.get("/api/library").json()) == 1
        assert len(client.get("/api/library?include_archived=true").json()) == 2
    shutil.rmtree(cache)
    with TestClient(create_app(cache, registry=registry)) as client:
        rows = client.get("/api/library?include_archived=true").json()
        assert {row["id"] for row in rows} == {identifier, duplicate["id"]}
        client.patch(f"/api/library/{identifier}", json={"archived": False}).raise_for_status()
        client.delete(f"/api/library/{duplicate['id']}").raise_for_status()
        assert [row["id"] for row in client.get("/api/library").json()] == [identifier]


def test_metadata_edits_reuse_the_same_project_cache(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Changing the project name must not reopen acquisitions or reimport identifications."""
    project = ProjectInput.load(DemoProject().write(tmp_path / "data"))
    with TestClient(create_app(tmp_path / "cache")) as client:
        initial = open_project(client, project)
        original_workspace = client.app.state.runtime.active[2]
        original_ids = client.app.state.runtime.active[1].rows("SELECT id FROM psms ORDER BY id")

        def reject_sources(*_args, **_kwargs) -> None:
            """Metadata edits must not enter expensive preparation or identification readers."""
            pytest.fail("Unchanged scientific inputs were re-read")

        monkeypatch.setattr(ProjectPreparer, "prepare", reject_sources)
        monkeypatch.setattr(IdXMLReader, "records", reject_sources)
        project.name = "Renamed experiment"
        updated = open_project(client, project)
        assert updated["project_id"] == initial["project_id"] == project.id
        assert updated["token"] != initial["token"]
        assert client.app.state.runtime.active[2] == original_workspace
        assert (
            client.app.state.runtime.active[1].rows("SELECT id FROM psms ORDER BY id")
            == original_ids
        )
        assert len(client.get("/api/library").json()) == 1


def test_added_fraction_reuses_maps_and_resolves_existing_sample_psms(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Prepare only the added fraction while resolving previously unmatched sample evidence."""
    project = ProjectInput.load(DemoProject().write(tmp_path / "data"))
    second = project.acquisitions.pop()
    indexed = []
    acquisition = ProjectPreparer.acquisition
    with TestClient(create_app(tmp_path / "cache")) as client:
        initial = open_project(client, project)
        old_workspace = client.app.state.runtime.active[2]
        old_map = (old_workspace / "fraction_01.npz").stat()
        query = {"sample": "Synthetic sample", "filters": json.dumps({"layers": ["Search"]})}
        before = client.get(f"/api/projects/{initial['token']}/psms", params=query).json()
        assert sum(row["resolved"] for row in before["rows"]) == 10

        def index_one(preparer: ProjectPreparer, catalog, source) -> None:
            """Record precisely which acquisitions require raw peak processing."""
            indexed.append(source.id)
            acquisition(preparer, catalog, source)

        monkeypatch.setattr(ProjectPreparer, "acquisition", index_one)
        project.acquisitions.append(second)
        plan = client.post("/api/preparation-plan", json=project.model_dump()).json()
        assert plan == {"added": 1, "changed": 0, "reused": 1}
        after = open_project(client, project)
        assert indexed == [second.id]
        assert after["project_id"] == initial["project_id"]
        new_workspace = client.app.state.runtime.active[2]
        assert new_workspace.parent == old_workspace.parent
        assert (new_workspace / "fraction_01.npz").stat().st_ino == old_map.st_ino
        rows = client.get(f"/api/projects/{after['token']}/psms", params=query).json()["rows"]
        assert len(rows) == 20 and all(row["resolved"] for row in rows)
        assert {row["source"] for row in rows} == {"fraction_01", "fraction_02"}


def test_changed_identification_reimports_only_that_layer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An idXML replacement refreshes its layer while preserving unrelated PSM IDs and maps."""
    project = ProjectInput.load(DemoProject().write(tmp_path / "data"))
    imports = []
    records = IdXMLReader.records
    with TestClient(create_app(tmp_path / "cache")) as client:
        open_project(client, project)
        old_ids = client.app.state.runtime.active[1].rows(
            "SELECT id FROM psms WHERE layer='Validated'"
        )
        path = Path(project.samples[0].identifications[0].path)
        stat = path.stat()
        os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns + 1000000))

        def import_one(reader: IdXMLReader):
            """Record which source files the incremental importer reloads."""
            imports.append(reader.path)
            yield from records(reader)

        def reject_signal(*_args, **_kwargs) -> None:
            """Identification edits reuse all mzML preparation."""
            pytest.fail("Identification update accessed raw mzML")

        monkeypatch.setattr(IdXMLReader, "records", import_one)
        monkeypatch.setattr(ProjectPreparer, "acquisition", reject_signal)
        open_project(client, project)
        assert imports == [path]
        assert (
            client.app.state.runtime.active[1].rows("SELECT id FROM psms WHERE layer='Validated'")
            == old_ids
        )
        assert (
            client.app.state.runtime.active[1].rows("SELECT COUNT(*) AS n FROM psms")[0]["n"] == 30
        )


def test_failed_update_preserves_the_previous_ready_revision(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A failed replacement keeps the old session and published cache usable for retry."""
    project = ProjectInput.load(DemoProject().write(tmp_path / "data"))
    with TestClient(create_app(tmp_path / "cache")) as client:
        initial = open_project(client, project)
        workspace = client.app.state.runtime.active[2]
        replacement = tmp_path / "replacement.mzML"
        shutil.copyfile(project.acquisitions[0].mzml, replacement)
        project.acquisitions[0].mzml = str(replacement)

        def fail_update(*_args, **_kwargs) -> None:
            """Simulate a native decoder failing after the previous project was ready."""
            raise RuntimeError("Synthetic decoder failure")

        monkeypatch.setattr(ProjectPreparer, "acquisition", fail_update)
        client.post("/api/open-configuration", json=project.model_dump()).raise_for_status()
        failure = finished(client)
        assert failure["state"] == "error" and "Synthetic decoder failure" in failure["message"]
        assert failure["token"] == initial["token"]
        assert client.app.state.runtime.active[2] == workspace
        assert client.app.state.runtime.cache_for(project.id).current() == workspace
        assert (
            client.get(f"/api/projects/{initial['token']}/sources/fraction_01/map").status_code
            == 200
        )
        saved = client.get(f"/api/library/{project.id}").json()
        assert saved["configuration"]["acquisitions"][0]["mzml"] == str(replacement)
        assert saved["status"] == "preparation failed"


def test_clearing_cache_keeps_saved_project_and_sources(tmp_path: Path) -> None:
    """Cache deletion leaves the project reopenable under the same ID after restarting."""
    project = ProjectInput.load(DemoProject().write(tmp_path / "data"))
    cache = tmp_path / "cache"
    with TestClient(create_app(cache)) as client:
        open_project(client, project)
        assert client.delete(f"/api/library/{project.id}/cache").status_code == 400
    with TestClient(create_app(cache)) as client:
        client.delete(f"/api/library/{project.id}/cache").raise_for_status()
        saved = client.get(f"/api/library/{project.id}").json()
        assert saved["status"] == "needs preparation" and not saved["has_cache"]
        assert all(Path(item.mzml).is_file() for item in project.acquisitions)
        client.post(f"/api/library/{project.id}/open").raise_for_status()
        assert finished(client)["project_id"] == project.id


def test_manifest_without_id_reopens_the_same_registered_project(tmp_path: Path) -> None:
    """Register programmatic manifests once, without requiring their producer to generate UUIDs."""
    manifest = DemoProject().write(tmp_path / "data")
    configuration = json.loads(manifest.read_text())
    configuration.pop("id")
    manifest.write_text(json.dumps(configuration))
    identities = []
    for _ in range(2):
        with TestClient(create_app(tmp_path / "cache", manifest)) as client:
            identities.append(finished(client)["project_id"])
            assert len(client.get("/api/library").json()) == 1
    assert identities[0] == identities[1]


def test_listing_projects_does_not_inspect_inputs_or_caches(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Historical project lists use only registry rows, including unavailable old sources."""
    project = ProjectInput.load(DemoProject().write(tmp_path / "data"))
    with TestClient(create_app(tmp_path / "cache")) as client:
        open_project(client, project)

        def reject_inspection(*_args, **_kwargs) -> None:
            """The library must not touch scientific files or inspect cache snapshots."""
            pytest.fail("Listing projects inspected source/cache files")

        with monkeypatch.context() as listing:
            listing.setattr(ProjectCache, "current", reject_inspection)
            listing.setattr(ProjectInput, "file_issues", reject_inspection)
            assert client.get("/api/library").json()[0]["id"] == project.id


def test_another_server_cannot_overwrite_an_active_project_cache(tmp_path: Path) -> None:
    """Multiple library readers can coexist, but a cache has only one server owner."""
    project = ProjectInput.load(DemoProject().write(tmp_path / "data"))
    cache = tmp_path / "cache"
    with TestClient(create_app(cache)) as first:
        status = open_project(first, project)
        with TestClient(create_app(cache)) as second:
            assert second.get("/api/library").json()[0]["id"] == project.id
            preview = second.post("/api/preparation-plan", json=project.model_dump())
            assert preview.json() == {"added": 0, "changed": 0, "reused": 2}
            assert not second.app.state.runtime.caches
            response = second.post(f"/api/library/{project.id}/open")
            assert response.status_code == 400
            assert "another mzLoupe server" in response.json()["detail"]
            assert (
                first.get(f"/api/projects/{status['token']}/sources/fraction_01/map").status_code
                == 200
            )


def test_lost_cache_artifact_is_rebuilt_without_losing_the_project(tmp_path: Path) -> None:
    """A partially cleared derived cache can be prepared again under the saved ID."""
    project = ProjectInput.load(DemoProject().write(tmp_path / "data"))
    with TestClient(create_app(tmp_path / "cache")) as client:
        open_project(client, project)
        workspace = client.app.state.runtime.active[2]
        (workspace / "fraction_01.npz").unlink()
        result = open_project(client, project)
        assert result["project_id"] == project.id
        assert client.app.state.runtime.active[2] != workspace
        assert (client.app.state.runtime.active[2] / "fraction_01.npz").is_file()


def test_reused_gzip_working_copy_survives_snapshot_cleanup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Reused indexed files stay valid after old snapshots are collected on shutdown."""
    project = ProjectInput.load(DemoProject().write(tmp_path / "data"))
    source = Path(project.acquisitions[0].mzml)
    compressed = source.with_suffix(".mzML.gz")
    compressed.write_bytes(gzip.compress(source.read_bytes()))
    project.acquisitions[0].mzml = str(compressed)
    cache = tmp_path / "cache"
    with TestClient(create_app(cache)) as client:
        open_project(client, project)
        previous = client.app.state.runtime.active[2]
        project.acquisitions[1].fraction = "Renamed fraction"

        def reject_decode(*_args, **_kwargs) -> None:
            """A metadata update must preserve the existing indexed working copy."""
            raise RuntimeError("Reused mzML was decoded again")

        monkeypatch.setattr(ProjectPreparer, "acquisition", reject_decode)
        updated = open_project(client, project)
        current = client.app.state.runtime.active[2]
        assert (
            client.get(
                f"/api/projects/{updated['token']}/sources/fraction_01/spectra/79"
            ).status_code
            == 200
        )
    assert not previous.exists()
    assert (current / "fraction_01.mzML").is_file()
    with TestClient(create_app(cache)) as client:
        reopened = open_project(client, project)
        assert (
            client.get(
                f"/api/projects/{reopened['token']}/sources/fraction_01/spectra/79"
            ).status_code
            == 200
        )


def test_unexpected_worker_failure_is_reported_without_hanging(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Unexpected worker errors become a terminal status rather than an infinite spinner."""
    project = ProjectInput.load(DemoProject().write(tmp_path / "data"))

    def unexpected(*_args, **_kwargs) -> None:
        """Simulate a programming error outside the native-reader error contract."""
        raise AssertionError("Unexpected preparation bug")

    monkeypatch.setattr(ProjectPreparer, "prepare", unexpected)
    with TestClient(create_app(tmp_path / "cache")) as client:
        client.post("/api/open-configuration", json=project.model_dump()).raise_for_status()
        status = finished(client)
        assert status["state"] == "error"
        assert "Unexpected preparation bug" in status["message"]


def test_import_paths_remain_associated_after_opening_an_exported_copy(tmp_path: Path) -> None:
    """An id-less producer manifest keeps its project even after an exported UUID copy opens."""
    manifest = DemoProject().write(tmp_path / "data")
    configuration = json.loads(manifest.read_text())
    configuration.pop("id")
    manifest.write_text(json.dumps(configuration))
    with TestClient(create_app(tmp_path / "cache")) as client:
        client.post("/api/open", json={"path": str(manifest)}).raise_for_status()
        identifier = finished(client)["project_id"]
        exported = tmp_path / "exported.json"
        exported.write_text(json.dumps(client.get("/api/configuration").json()))
        client.post("/api/open", json={"path": str(exported)}).raise_for_status()
        assert finished(client)["project_id"] == identifier
        client.post("/api/open", json={"path": str(manifest)}).raise_for_status()
        assert finished(client)["project_id"] == identifier
        assert len(client.get("/api/library").json()) == 1


def test_closing_workspace_allows_cache_cleanup_without_stopping_server(tmp_path: Path) -> None:
    """Close only the active workspace, invalidate its token, then clear and reopen its cache."""
    project = ProjectInput.load(DemoProject().write(tmp_path / "data"))
    with TestClient(create_app(tmp_path / "cache")) as client:
        initial = open_project(client, project)
        client.post(f"/api/library/{project.id}/close").raise_for_status()
        assert client.get("/api/status").json()["token"] is None
        assert client.get(f"/api/projects/{initial['token']}").status_code == 400
        client.delete(f"/api/library/{project.id}/cache").raise_for_status()
        assert client.get(f"/api/library/{project.id}").json()["has_cache"] is False
        assert open_project(client, project)["project_id"] == project.id
