"""Exercise durable project identity, incremental preparation, and failed update recovery."""

import errno
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


def test_listing_projects_does_not_read_scientific_inputs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Library availability reads local manifests without inspecting scientific inputs."""
    project = ProjectInput.load(DemoProject().write(tmp_path / "data"))
    with TestClient(create_app(tmp_path / "cache")) as client:
        open_project(client, project)

        def reject_inspection(*_args, **_kwargs) -> None:
            """The library must not inspect scientific files or decode peak arrays."""
            pytest.fail("Listing projects inspected scientific files")

        with monkeypatch.context() as listing:
            listing.setattr(ProjectCache, "signature", reject_inspection)
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


@pytest.mark.parametrize("link_error", [None, errno.EXDEV, errno.EOPNOTSUPP, errno.EPERM])
def test_reused_gzip_working_copy_survives_snapshot_cleanup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, link_error: int | None
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
        if link_error is not None:

            def unsupported_link(_source: Path, _destination: Path) -> None:
                """Exercise copying of both maps and the generated indexed mzML."""
                raise OSError(link_error, "Hard linking unavailable")

            monkeypatch.setattr(os, "link", unsupported_link)
        updated = open_project(client, project)
        current = client.app.state.runtime.active[2]
        for source in previous.iterdir():
            if source.suffix in {".npz", ".mzML"}:
                destination = current / source.name
                assert destination.read_bytes() == source.read_bytes()
                assert os.path.samefile(source, destination) == (link_error is None)
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


def test_shared_registry_uses_current_cache_root_and_local_readiness(tmp_path: Path) -> None:
    """A root change keeps the project identity without reusing or clearing the other root."""
    project = ProjectInput.load(DemoProject().write(tmp_path / "data"))
    registry = tmp_path / "state/projects.sqlite"
    first_root = tmp_path / "first-cache"
    second_root = tmp_path / "second-cache"
    with TestClient(create_app(first_root, registry=registry)) as first:
        original = open_project(first, project)
        first_directory = first_root / "projects" / project.id
        with TestClient(create_app(second_root, registry=registry)) as second:
            record = second.get(f"/api/library/{project.id}").json()
            assert record["cache_directory"] == str(second_root / "projects" / project.id)
            assert record["status"] == "needs preparation" and not record["has_cache"]
            second.delete(f"/api/library/{project.id}/cache").raise_for_status()
            assert first_directory.is_dir()
            assert first.get(f"/api/library/{project.id}").json()["status"] == "ready"
            prepared = open_project(second, project)
            assert prepared["project_id"] == original["project_id"] == project.id
            assert (
                second.app.state.runtime.active[2].parent == second_root / "projects" / project.id
            )
            second.post(f"/api/library/{project.id}/close").raise_for_status()
            second.delete(f"/api/library/{project.id}/cache").raise_for_status()
            assert not second.get(f"/api/library/{project.id}").json()["has_cache"]
            assert first.get(f"/api/library/{project.id}").json()["status"] == "ready"
            assert (
                first.get(f"/api/projects/{original['token']}/sources/fraction_01/map").status_code
                == 200
            )
        with first.app.state.runtime.registry.connect() as connection:
            columns = {row["name"] for row in connection.execute("PRAGMA table_info(projects)")}
        assert "cache_directory" not in columns
        assert "prepared_configuration" not in columns and "prepared_version" not in columns


def test_deleting_project_only_clears_the_current_cache_root(tmp_path: Path) -> None:
    """Deleting from a new root leaves old caches and original scientific inputs untouched."""
    project = ProjectInput.load(DemoProject().write(tmp_path / "data"))
    registry = tmp_path / "state/projects.sqlite"
    first_root = tmp_path / "first-cache"
    with TestClient(create_app(first_root, registry=registry)) as client:
        open_project(client, project)
    marker = first_root / "projects" / project.id / "current.json"
    original = marker.read_bytes()
    with TestClient(create_app(tmp_path / "second-cache", registry=registry)) as client:
        client.delete(f"/api/library/{project.id}").raise_for_status()
        assert client.get("/api/library").json() == []
    assert marker.read_bytes() == original
    assert all(Path(source.mzml).is_file() for source in project.acquisitions)


@pytest.mark.parametrize("action", ["clear", "delete"])
def test_library_deletion_rejects_a_redirected_project_directory(
    tmp_path: Path, action: str
) -> None:
    """Both API deletion operations keep a project and external files when its path is unsafe."""
    with TestClient(create_app(tmp_path / "cache")) as client:
        project = client.post("/api/library", json={"name": "Draft"}).json()
        identifier = project["id"]
        directory = Path(project["cache_directory"])
        protected = tmp_path / "protected"
        protected.mkdir()
        sentinel = protected / "keep.txt"
        sentinel.write_text("Original data")
        directory.parent.mkdir(parents=True)
        directory.symlink_to(protected, target_is_directory=True)
        suffix = "/cache" if action == "clear" else ""
        response = client.delete(f"/api/library/{identifier}{suffix}")
        assert response.status_code == 400 and "without symlinks" in response.json()["detail"]
        assert sentinel.read_text() == "Original data"
        assert client.get(f"/api/library/{identifier}").status_code == 200


def test_missing_acquisition_header_reindexes_before_reusing_artifacts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Repair a missing catalog acquisition despite matching fingerprints and stale scans."""
    project = ProjectInput.load(DemoProject().write(tmp_path / "data"))
    missing = project.acquisitions[0]
    indexed = []
    original_index = ProjectPreparer.acquisition
    original_link = os.link
    with TestClient(create_app(tmp_path / "cache")) as client:
        open_project(client, project)
        previous = client.app.state.runtime.active[2]
        catalog = client.app.state.runtime.active[1]
        expected_scans = len(
            catalog.rows("SELECT ordinal FROM scans WHERE source=?", (missing.id,))
        )
        with catalog.connect() as connection:
            connection.execute("DELETE FROM acquisitions WHERE id=?", (missing.id,))
            connection.execute("UPDATE scans SET rt=-1 WHERE source=?", (missing.id,))
        # A fraction-label edit requires a staged update while all file signatures stay the same.
        project.acquisitions[1].fraction = "Renamed fraction"

        def index_acquisition(preparer: ProjectPreparer, target, source) -> None:
            """Record which raw acquisition actually needs rebuilding."""
            indexed.append(source.id)
            original_index(preparer, target, source)

        def link_valid_artifact(source: Path, destination: Path) -> None:
            """Reject partial reuse of an acquisition before its missing header is detected."""
            assert Path(source).stem != missing.id
            original_link(source, destination)

        monkeypatch.setattr(ProjectPreparer, "acquisition", index_acquisition)
        monkeypatch.setattr(os, "link", link_valid_artifact)
        updated = open_project(client, project)
        current = client.app.state.runtime.active[2]
        rebuilt = client.app.state.runtime.active[1]
        assert indexed == [missing.id]
        assert len(rebuilt.rows("SELECT id FROM acquisitions")) == 2
        assert (
            len(rebuilt.rows("SELECT ordinal FROM scans WHERE source=?", (missing.id,)))
            == expected_scans
        )
        assert rebuilt.scan(missing.id, 79)["rt"] == 237
        assert not os.path.samefile(
            previous / (missing.id + ".npz"), current / (missing.id + ".npz")
        )
        assert (
            client.get(
                f"/api/projects/{updated['token']}/sources/{missing.id}/spectra/79"
            ).status_code
            == 200
        )
