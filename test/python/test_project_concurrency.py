"""Keep polling and unrelated projects responsive while filesystem work is paused."""

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Event
from uuid import uuid4

from fastapi.testclient import TestClient
import pytest

from mzloupe.app import create_app
from mzloupe.demo import DemoProject
from mzloupe.models import ProjectInput
from mzloupe.services.project_cache import ProjectCache


class PausedOperation:
    """Pause one filesystem operation until assertions have run in other request threads."""

    def __init__(self) -> None:
        """Create separate events for reaching and releasing the blocked operation."""
        self.started = Event()
        self.resume = Event()

    def wait(self) -> None:
        """Signal that disk work started and wait for the test to release it."""
        self.started.set()
        if not self.resume.wait(timeout=15):
            raise TimeoutError("Test did not release the paused filesystem operation")

    def reached(self) -> None:
        """Fail promptly if the requested operation never reaches the intended disk work."""
        assert self.started.wait(timeout=5), "Filesystem operation was not reached"


def complete_preparation(client: TestClient) -> dict:
    """Wait behind the single preparation worker, including its completion callback."""
    client.app.state.runtime.executor.submit(lambda: None).result(timeout=5)
    status = client.get("/api/status").json()
    assert status["state"] == "ready", status
    return status


@pytest.mark.parametrize("delete", [False, True])
def test_slow_cache_cleanup_keeps_status_and_other_projects_responsive(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, delete: bool
) -> None:
    """Detach a cache before deletion while keeping both its reservation and file lease."""
    project = ProjectInput.load(DemoProject().write(tmp_path / "data"))
    other = project.model_copy(deep=True)
    other.id = str(uuid4())
    other.name = "Other project"
    pause = PausedOperation()
    original_clear = ProjectCache.clear

    def slow_clear(cache: ProjectCache) -> None:
        """Hold this project's disk cleanup while other requests run."""
        if cache.root.name == project.id:
            pause.wait()
        original_clear(cache)

    with TestClient(create_app(tmp_path / "cache")) as client:
        runtime = client.app.state.runtime
        runtime.registry.save(project)
        runtime.registry.save(other)
        cache = runtime.cache_for(project.id)
        monkeypatch.setattr(ProjectCache, "clear", slow_clear)
        with ThreadPoolExecutor(max_workers=4) as requests:
            suffix = "" if delete else "/cache"
            cleanup = requests.submit(client.delete, f"/api/library/{project.id}{suffix}")
            try:
                pause.reached()
                assert project.id not in runtime.caches
                status = requests.submit(client.get, "/api/status").result(timeout=2)
                assert status.status_code == 200
                for operation in ["open", "close"]:
                    response = requests.submit(
                        client.post, f"/api/library/{project.id}/{operation}"
                    ).result(timeout=2)
                    assert response.status_code == 400
                conflicting = requests.submit(
                    client.delete, f"/api/library/{project.id}/cache"
                ).result(timeout=2)
                assert conflicting.status_code == 400
                competitor = ProjectCache(runtime.cache, project.id, runtime.cache_version)
                with pytest.raises(ValueError, match="another mzLoupe server"):
                    competitor.acquire()
                response = requests.submit(client.post, f"/api/library/{other.id}/open").result(
                    timeout=2
                )
                assert response.status_code == 202
                ready = complete_preparation(client)
                assert ready["project_id"] == other.id
                assert cache.lease is not None
            finally:
                pause.resume.set()
            assert cleanup.result(timeout=5).status_code == 200
        assert cache.lease is None
        assert runtime.operations.action(project.id) is None


@pytest.mark.parametrize("phase", ["before", "after"])
def test_project_deletion_stays_reserved_through_registry_removal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, phase: str
) -> None:
    """A saved project cannot be reopened or overwritten in the cache-to-registry deletion gap."""
    manifest = DemoProject().write(tmp_path / "data")
    project = ProjectInput.load(manifest)
    pause = PausedOperation()
    with TestClient(create_app(tmp_path / "cache")) as client:
        runtime = client.app.state.runtime
        runtime.registry.save(project)
        original_delete = runtime.registry.delete

        def slow_delete(identifier: str) -> None:
            """Pause after cache removal but before deleting the saved definition."""
            if phase == "after":
                original_delete(identifier)
            pause.wait()
            if phase == "before":
                original_delete(identifier)

        monkeypatch.setattr(runtime.registry, "delete", slow_delete)
        with ThreadPoolExecutor(max_workers=3) as requests:
            deletion = requests.submit(client.delete, f"/api/library/{project.id}")
            try:
                pause.reached()
                assert (
                    requests.submit(client.get, "/api/status").result(timeout=2).status_code == 200
                )
                opened = requests.submit(client.post, f"/api/library/{project.id}/open").result(
                    timeout=2
                )
                saved = requests.submit(
                    client.post, "/api/library", json=project.model_dump()
                ).result(timeout=2)
                imported = requests.submit(
                    client.post, "/api/open", json={"path": str(manifest)}
                ).result(timeout=2)
                assert opened.status_code == saved.status_code == imported.status_code == 400
                if phase == "before":
                    assert runtime.registry.get(project.id)["id"] == project.id
                else:
                    with pytest.raises(ValueError, match="Unknown project"):
                        runtime.registry.get(project.id)
                competitor = ProjectCache(runtime.cache, project.id, runtime.cache_version)
                with pytest.raises(ValueError, match="another mzLoupe server"):
                    competitor.acquire()
            finally:
                pause.resume.set()
            assert deletion.result(timeout=5).status_code == 200
        assert runtime.operations.action(project.id) is None
        assert client.get(f"/api/library/{project.id}").status_code == 400


@pytest.mark.parametrize("fail", [False, True])
@pytest.mark.parametrize("phase", ["paths", "registry", "lease", "opened"])
def test_slow_project_open_io_keeps_status_responsive_and_releases_failures(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fail: bool, phase: str
) -> None:
    """Opening performs validation and registry/cache I/O outside the runtime state lock."""
    project = ProjectInput.load(DemoProject().write(tmp_path / "data"))
    pause = PausedOperation()
    with TestClient(create_app(tmp_path / "cache")) as client:
        runtime = client.app.state.runtime
        runtime.registry.save(project)
        target, method = {
            "paths": (ProjectInput, "resolve_paths"),
            "registry": (runtime.registry, "save"),
            "lease": (ProjectCache, "acquire"),
            "opened": (runtime.registry, "opened"),
        }[phase]
        original = getattr(target, method)

        def slow_operation(*args, **kwargs):
            """Pause exactly one synchronous opening operation before it reaches the worker."""
            if not pause.started.is_set():
                pause.wait()
                if fail:
                    raise ValueError("Synthetic opening failure")
            return original(*args, **kwargs)

        monkeypatch.setattr(target, method, slow_operation)
        with ThreadPoolExecutor(max_workers=3) as requests:
            opening = requests.submit(client.post, f"/api/library/{project.id}/open")
            try:
                pause.reached()
                assert (
                    requests.submit(client.get, "/api/status").result(timeout=2).status_code == 200
                )
                conflicting = requests.submit(
                    client.post, f"/api/library/{project.id}/open"
                ).result(timeout=2)
                assert conflicting.status_code == 400
                clearing = requests.submit(
                    client.delete, f"/api/library/{project.id}/cache"
                ).result(timeout=2)
                assert clearing.status_code == 400
            finally:
                pause.resume.set()
            assert opening.result(timeout=5).status_code == (400 if fail else 202)
        if fail:
            assert runtime.operations.action(project.id) is None
            assert client.post(f"/api/library/{project.id}/open").status_code == 202
        complete_preparation(client)
        assert runtime.operations.action(project.id) is None


def test_close_prunes_without_holding_state_or_scientific_access_locks(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A new project's inspection can proceed while the old project's close is pruning."""
    project = ProjectInput.load(DemoProject().write(tmp_path / "data"))
    other = project.model_copy(deep=True)
    other.id = str(uuid4())
    other.name = "Other project"
    pause = PausedOperation()
    original_prune = ProjectCache.prune

    def slow_prune(cache: ProjectCache) -> None:
        """Pause this project's snapshot collection after its readers are detached."""
        if cache.root.name == project.id:
            pause.wait()
        original_prune(cache)

    with TestClient(create_app(tmp_path / "cache")) as client:
        runtime = client.app.state.runtime
        runtime.registry.save(other)
        assert client.post("/api/open-configuration", json=project.model_dump()).status_code == 202
        complete_preparation(client)
        monkeypatch.setattr(ProjectCache, "prune", slow_prune)
        with ThreadPoolExecutor(max_workers=3) as requests:
            closing = requests.submit(client.post, f"/api/library/{project.id}/close")
            try:
                pause.reached()
                status = requests.submit(client.get, "/api/status").result(timeout=2).json()
                assert status["token"] is None
                assert (
                    requests.submit(client.post, f"/api/library/{project.id}/open")
                    .result(timeout=2)
                    .status_code
                    == 400
                )
                assert (
                    requests.submit(client.post, f"/api/library/{other.id}/open")
                    .result(timeout=2)
                    .status_code
                    == 202
                )
                ready = complete_preparation(client)
                spectrum = requests.submit(
                    client.get,
                    f"/api/projects/{ready['token']}/sources/fraction_01/spectra/79",
                ).result(timeout=2)
                assert spectrum.status_code == 200
            finally:
                pause.resume.set()
            assert closing.result(timeout=5).status_code == 200
        assert runtime.operations.action(project.id) is None


def test_cleanup_failure_releases_its_reservation_and_file_lease(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Failed filesystem cleanup never leaves the project permanently busy or locked."""
    with TestClient(create_app(tmp_path / "cache")) as client:
        runtime = client.app.state.runtime
        record = client.post("/api/library", json={"name": "Draft"}).json()
        identifier = record["id"]

        def fail_clear(_cache: ProjectCache) -> None:
            """Simulate an unreadable directory during deletion."""
            raise OSError("Synthetic cleanup failure")

        with monkeypatch.context() as failure:
            failure.setattr(ProjectCache, "clear", fail_clear)
            with pytest.raises(OSError, match="Synthetic cleanup failure"):
                client.delete(f"/api/library/{identifier}/cache")
        assert runtime.operations.action(identifier) is None
        assert identifier not in runtime.caches
        assert client.delete(f"/api/library/{identifier}/cache").status_code == 200


def test_failed_preparation_releases_its_reservation_for_retry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Worker failures release preparation ownership before a subsequent open is attempted."""
    project = ProjectInput.load(DemoProject().write(tmp_path / "data"))
    with TestClient(create_app(tmp_path / "cache")) as client:
        runtime = client.app.state.runtime
        runtime.registry.save(project)
        with monkeypatch.context() as failure:

            def fail_prepare(_project: ProjectInput) -> None:
                """Raise an unexpected worker error that must still release ownership."""
                raise AssertionError("Synthetic worker failure")

            failure.setattr(runtime, "prepare", fail_prepare)
            assert client.post(f"/api/library/{project.id}/open").status_code == 202
            runtime.executor.submit(lambda: None).result(timeout=5)
            assert client.get("/api/status").json()["state"] == "error"
        assert runtime.operations.action(project.id) is None
        assert client.post(f"/api/library/{project.id}/open").status_code == 202
        complete_preparation(client)
