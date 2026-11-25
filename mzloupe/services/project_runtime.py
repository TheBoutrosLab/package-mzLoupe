"""Coordinate the durable project registry and atomically published preparation snapshots."""

from concurrent.futures import Future, ThreadPoolExecutor
from pathlib import Path
import shutil
import sqlite3
from tempfile import mkdtemp
from threading import Lock
from typing import Any

from mzloupe.models import ProjectInput
from mzloupe.services.preparation import ProjectPreparer
from mzloupe.services.project_cache import ProjectCache
from mzloupe.services.protein_grouping import ProteinGroupings
from mzloupe.services.psm_search import PsmSearch
from mzloupe.services.signal import SignalService
from mzloupe.storage.catalog import ProjectCatalog
from mzloupe.storage.registry import ProjectRegistry


class ProjectRuntime:
    """Keep saved projects independent of cache validity and active browser sessions."""

    cache_version = 6

    def __init__(self, cache: str | Path, registry: str | Path | None = None) -> None:
        """Create the registry and one preparation worker without reading source files."""
        self.cache = Path(cache).expanduser().resolve()
        self.cache.mkdir(parents=True, exist_ok=True)
        self.registry = ProjectRegistry(registry or ProjectRegistry.default_path())
        self.executor = ThreadPoolExecutor(max_workers=1)
        self.lock = Lock()
        self.signal_lock = Lock()
        self.metadata_lock = Lock()
        self.search_lock = Lock()
        self.search: PsmSearch | None = None
        self.signal: SignalService | None = None
        self.active: tuple[ProjectInput, ProjectCatalog, Path] | None = None
        self.token: str | None = None
        self.caches: dict[str, ProjectCache] = {}
        self.status: dict[str, Any] = {
            "state": "empty",
            "message": "Select a project",
            "progress": 0,
            "project_id": None,
        }

    def cache_for(self, identifier: str) -> ProjectCache:
        """Resolve the same project directory across edits, opens, and server restarts."""
        if identifier in self.caches:
            return self.caches[identifier]
        record = self.registry.get(identifier)
        directory = self.cache_directory(record)
        if not record["cache_directory"]:
            self.registry.set_cache(identifier, directory)
        cache = ProjectCache(directory, self.cache_version)
        cache.acquire()
        self.caches[identifier] = cache
        return cache

    def cache_directory(self, record: dict[str, Any]) -> Path:
        """Resolve registered storage without creating a cache or claiming its write lease."""
        if record["cache_directory"]:
            return Path(record["cache_directory"])
        return self.cache / "projects" / record["id"]

    def preparation_plan(self, project: ProjectInput) -> dict[str, int]:
        """Preview reuse without locking a project merely because its editor is open."""
        directory = self.cache_directory(self.registry.get(project.id))
        return ProjectCache(directory, self.cache_version).plan(project)

    def open(self, path: str | Path) -> None:
        """Register a manifest once and prepare its saved project identity."""
        path = Path(path).expanduser().resolve()
        project = ProjectInput.load(path, validate_files=False)
        self.registry.save(project, source_path=path)
        self.open_configuration(project)

    def open_configuration(self, project: ProjectInput) -> None:
        """Save a valid definition and queue preparation while keeping previous results usable."""
        with self.lock:
            if self.status["state"] == "preparing":
                raise ValueError("Project preparation is already running")
            if not project.acquisitions:
                raise ValueError("Add at least one mzML acquisition before exploring")
            project.resolve_paths(Path.cwd(), validate_files=False)
            self.registry.save(project)
            try:
                project.resolve_paths(Path.cwd())
            except ValueError as error:
                self.registry.report_error(project.id, str(error))
                raise
            self.cache_for(project.id)
            self.registry.opened(project.id)
            self.status = {
                "state": "preparing",
                "message": "Reading sources",
                "progress": 0,
                "project_id": project.id,
            }
        task = self.executor.submit(self.prepare, project)
        task.add_done_callback(lambda completed: self.preparation_finished(project, completed))

    def preparation_finished(self, project: ProjectInput, task: Future[None]) -> None:
        """Surface unexpected worker failures instead of leaving the UI preparing forever."""
        if task.cancelled():
            return
        error = task.exception()
        if error is not None:
            message = str(error) or type(error).__name__
            with self.lock:
                self.status = {
                    "state": "error",
                    "message": message,
                    "progress": 0,
                    "project_id": project.id,
                }
            self.registry.report_error(project.id, message)

    def progress(self, message: str, progress: float) -> None:
        """Publish preparation progress without replacing the previous active snapshot."""
        with self.lock:
            self.status = {
                **self.status,
                "state": "preparing",
                "message": message,
                "progress": progress,
            }

    def publish_ready(
        self, project: ProjectInput, catalog: ProjectCatalog, workspace: Path, stamp: str
    ) -> None:
        """Switch the browser revision only after metadata, maps, and groupings are complete."""
        with self.signal_lock, self.search_lock, self.metadata_lock, self.lock:
            self.active = (project, catalog, workspace)
            self.token = project.id + "-" + stamp[:16]
            self.signal = None
            self.search = None
            self.status = {
                "state": "ready",
                "message": project.name,
                "progress": 1,
                "project_id": project.id,
            }

    def prepare(self, project: ProjectInput) -> None:
        """Reuse unaffected inputs and publish a complete snapshot in this project's cache."""
        workspace = None
        published = False
        try:
            try:
                self.registry.get(project.id)
            except ValueError:
                self.registry.save(project)
            cache = self.cache_for(project.id)
            description = cache.describe(project)
            stamp = cache.fingerprint(description)
            previous = cache.current()
            old = cache.description(previous)
            metadata_only = (
                old.get("version") == self.cache_version
                and old.get("acquisitions") == description["acquisitions"]
                and old.get("identifications") == description["identifications"]
                and old.get("configuration", {}).get("acquisitions")
                == description["configuration"]["acquisitions"]
            )
            if metadata_only and previous is not None:
                catalog = ProjectCatalog(previous / "catalog.sqlite")
                catalog.groupings = ProteinGroupings(project, catalog)
                if old != description:
                    cache.publish(previous, description)
                self.registry.prepared(project, self.cache_version)
                self.publish_ready(project, catalog, previous, stamp)
                return
            if old.get("version") != self.cache_version:
                previous = None
            cache.root.mkdir(parents=True, exist_ok=True)
            workspace = Path(mkdtemp(prefix="revision-", dir=cache.root))
            catalog = ProjectPreparer(workspace).prepare(
                project, self.progress, previous, description
            )
            catalog.groupings = ProteinGroupings(project, catalog)
            if cache.describe(project) != description:
                raise ValueError("A source changed during preparation. Open the project again.")
            cache.publish(workspace, description)
            published = True
            self.registry.prepared(project, self.cache_version)
            self.publish_ready(project, catalog, workspace, stamp)
        except (OSError, ValueError, RuntimeError, TypeError, sqlite3.Error) as error:
            if workspace is not None and not published:
                shutil.rmtree(workspace)
            self.registry.report_error(project.id, str(error))
            with self.lock:
                self.status = {
                    "state": "error",
                    "message": str(error),
                    "progress": 0,
                    "project_id": project.id,
                }

    def library_record(self, record: dict[str, Any]) -> dict[str, Any]:
        """Describe saved state cheaply; validate scientific files only when opening or editing."""
        configuration = record["configuration"]
        directory = str(self.cache_directory(record))
        has_cache = record["prepared_configuration"] is not None
        state = (
            "ready"
            if record["prepared_configuration"] == configuration
            and record["prepared_version"] == self.cache_version
            else "needs preparation"
        )
        if not configuration["acquisitions"]:
            state = "draft"
        if record["error"]:
            state = "preparation failed"
        if self.status.get("project_id") == record["id"] and self.status["state"] == "preparing":
            state = "preparing"
        return {
            **record,
            "name": configuration["name"],
            "status": state,
            "samples": len({item["sample"] for item in configuration["acquisitions"]}),
            "fractions": len(configuration["acquisitions"]),
            "has_cache": has_cache,
            "cache_directory": directory,
        }

    def close_project(self, identifier: str) -> None:
        """Release a selected workspace so its cache can be cleared without restarting."""
        self.registry.get(identifier)
        with self.signal_lock, self.search_lock, self.metadata_lock, self.lock:
            if self.status["state"] == "preparing":
                raise ValueError("Wait for preparation to finish before closing a project")
            if self.active is None or self.active[0].id != identifier:
                return
            self.active = None
            self.signal = None
            self.search = None
            self.token = None
            self.status = {
                "state": "empty",
                "message": "Select a project",
                "progress": 0,
                "project_id": None,
            }
            cache = self.caches.pop(identifier, None)
            if cache is not None:
                try:
                    cache.prune()
                finally:
                    cache.release()

    def clear_cache(self, identifier: str) -> None:
        """Clear derived artifacts while retaining the saved definition and original files."""
        with self.lock:
            if self.status.get("project_id") == identifier and self.status["state"] == "preparing":
                raise ValueError("Wait for preparation to finish before clearing this cache")
            if self.active is not None and self.active[0].id == identifier:
                raise ValueError("Close the project before clearing its cache")
            cache = self.cache_for(identifier)
            try:
                shutil.rmtree(cache.root)
            except FileNotFoundError:
                pass
            cache.release()
            self.caches.pop(identifier, None)
            self.registry.cache_cleared(identifier)

    def snapshot(self, token: str) -> tuple[ProjectInput, ProjectCatalog, Path]:
        """Return the active session only if the caller's project token still matches."""
        with self.lock:
            if not self.active or token != self.token:
                raise ValueError("Project changed or is not ready. Refresh the project.")
            return self.active

    def signal_service(self, token: str) -> SignalService:
        """Reuse signal access for the active workspace while holding signal_lock.

        Validate the token before touching any cached data. A different prepared
        workspace replaces the old reader and results rather than mixing projects.
        """
        _, catalog, workspace = self.snapshot(token)
        if self.signal is None or self.signal.workspace != workspace:
            self.signal = SignalService(catalog, workspace)
        return self.signal

    def search_service(self, token: str) -> PsmSearch:
        """Reuse table indexes while the caller holds search_lock for this request."""
        _, catalog, _ = self.snapshot(token)
        if self.search is None or self.search.catalog is not catalog:
            self.search = PsmSearch(catalog)
        return self.search

    def close(self) -> None:
        """Finish readers before collecting superseded temporary metadata snapshots."""
        self.executor.shutdown(wait=True)
        with self.signal_lock, self.search_lock:
            self.signal = None
            self.search = None
        for cache in self.caches.values():
            try:
                cache.prune()
            finally:
                cache.release()
