"""Coordinate the durable project registry and atomically published preparation snapshots."""

from concurrent.futures import Future, ThreadPoolExecutor
from pathlib import Path
import sqlite3
from threading import Lock
from typing import Any

from mzloupe.models import ProjectInput
from mzloupe.services.preparation import ProjectPreparer
from mzloupe.services.project_cache import ProjectCache
from mzloupe.services.project_operations import ProjectOperations
from mzloupe.services.protein_grouping import ProteinGroupings
from mzloupe.services.psm_search import PsmSearch
from mzloupe.services.signal import SignalService
from mzloupe.storage.catalog import ProjectCatalog
from mzloupe.storage.registry import ProjectRegistry


class ProjectRuntime:
    """Keep saved projects independent of cache validity and active browser sessions."""

    cache_version = 7

    def __init__(self, cache: str | Path, registry: str | Path | None = None) -> None:
        """Create the registry and one preparation worker without reading source files."""
        self.cache = Path(cache).expanduser().resolve()
        self.cache.mkdir(parents=True, exist_ok=True)
        self.registry = ProjectRegistry(registry or ProjectRegistry.default_path())
        self.executor = ThreadPoolExecutor(max_workers=1)
        self.lock = Lock()
        self.operations = ProjectOperations()
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
        """Acquire a lease outside the state lock for a reserved project operation.

        Callers reserve the project before requesting a new lease, so another
        operation cannot create or detach its cache during this filesystem work.
        """
        with self.lock:
            existing = self.caches.get(identifier)
        if existing is not None:
            return existing
        self.registry.get(identifier)
        cache = ProjectCache(self.cache, identifier, self.cache_version)
        cache.acquire()
        with self.lock:
            self.caches[identifier] = cache
        return cache

    def save_configuration(self, project: ProjectInput) -> dict[str, Any]:
        """Save an edited definition without racing project deletion or preparing data."""
        with self.lock:
            self.operations.reserve(project.id, "saving")
        try:
            project.resolve_paths(Path.cwd(), validate_files=False)
            return self.registry.save(project)
        finally:
            with self.lock:
                self.operations.release(project.id)

    def preparation_plan(self, project: ProjectInput) -> dict[str, int]:
        """Preview reuse without locking a project merely because its editor is open."""
        self.registry.get(project.id)
        return ProjectCache(self.cache, project.id, self.cache_version).plan(project)

    def open(self, path: str | Path) -> None:
        """Register a manifest once and prepare its saved project identity."""
        path = Path(path).expanduser().resolve()
        project = ProjectInput.load(path, validate_files=False)
        self.open_configuration(project, source_path=path)

    def open_configuration(self, project: ProjectInput, *, source_path: Path | None = None) -> None:
        """Reserve an edited project before doing validation, registry, or cache disk work."""
        identifier = project.id
        with self.lock:
            self.operations.reserve(identifier, "preparing")
        queued = False
        try:
            if source_path is not None and "id" not in project.model_fields_set:
                registered = self.registry.source_identifier(source_path)
                if registered is not None:
                    with self.lock:
                        self.operations.reassign(identifier, registered)
                    identifier = registered
                project.id = identifier
            self.queue_preparation(project, source_path=source_path)
            queued = True
        finally:
            if not queued:
                with self.lock:
                    self.operations.release(identifier)

    def open_project(self, identifier: str) -> None:
        """Reserve a saved identity before loading its definition, preventing delete/open races."""
        with self.lock:
            self.operations.reserve(identifier, "preparing")
        queued = False
        try:
            project = ProjectInput.model_validate(self.registry.get(identifier)["configuration"])
            self.queue_preparation(project)
            queued = True
        finally:
            if not queued:
                with self.lock:
                    self.operations.release(identifier)

    def queue_preparation(self, project: ProjectInput, *, source_path: Path | None = None) -> None:
        """Validate and queue a reserved project without holding the runtime state lock."""
        if not project.acquisitions:
            raise ValueError("Add at least one mzML acquisition before exploring")
        project.resolve_paths(Path.cwd(), validate_files=False)
        self.registry.save(project, source_path=source_path)
        try:
            project.resolve_paths(Path.cwd())
        except ValueError as error:
            self.registry.report_error(project.id, str(error))
            raise
        self.cache_for(project.id)
        self.registry.opened(project.id)
        with self.lock:
            self.status = {
                "state": "preparing",
                "message": "Reading sources",
                "progress": 0,
                "project_id": project.id,
            }
        task = self.executor.submit(self.prepare, project)
        task.add_done_callback(lambda completed: self.preparation_finished(project, completed))

    def preparation_finished(self, project: ProjectInput, task: Future[None]) -> None:
        """Surface worker failures and release preparation's reservation on every exit."""
        try:
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
        finally:
            with self.lock:
                self.operations.release(project.id)

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
        cache: ProjectCache | None = None
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
                self.registry.report_error(project.id, "")
                self.publish_ready(project, catalog, previous, stamp)
                return
            if old.get("version") != self.cache_version:
                previous = None
            workspace = cache.stage()
            catalog = ProjectPreparer(workspace).prepare(
                project, self.progress, previous, description
            )
            catalog.groupings = ProteinGroupings(project, catalog)
            if cache.describe(project) != description:
                raise ValueError("A source changed during preparation. Open the project again.")
            cache.publish(workspace, description)
            published = True
            self.registry.report_error(project.id, "")
            self.publish_ready(project, catalog, workspace, stamp)
        except (OSError, ValueError, RuntimeError, TypeError, sqlite3.Error) as error:
            if workspace is not None and not published and cache is not None:
                cache.discard(workspace)
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
        cache = ProjectCache(self.cache, record["id"], self.cache_version)
        directory = str(cache.root)
        prepared = cache.description(cache.current())
        has_cache = bool(prepared)
        state = (
            "ready"
            if has_cache
            and prepared.get("configuration") == configuration
            and prepared.get("version") == self.cache_version
            else "needs preparation"
        )
        if not configuration["acquisitions"]:
            state = "draft"
        if record["error"]:
            state = "preparation failed"
        with self.lock:
            action = self.operations.action(record["id"])
        if action is not None:
            state = action
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
        """Detach readers under their locks, then prune outside every runtime access lock."""
        with self.lock:
            self.operations.reserve(identifier, "closing")
        cache = None
        try:
            self.registry.get(identifier)
            with self.signal_lock, self.search_lock, self.metadata_lock, self.lock:
                if self.active is not None and self.active[0].id == identifier:
                    self.active = None
                    self.signal = None
                    self.search = None
                    self.token = None
                    if self.status.get("project_id") == identifier:
                        self.status = {
                            "state": "empty",
                            "message": "Select a project",
                            "progress": 0,
                            "project_id": None,
                        }
                cache = self.caches.pop(identifier, None)
            if cache is not None:
                cache.prune()
        finally:
            if cache is not None:
                cache.release()
            with self.lock:
                self.operations.release(identifier)

    def clear_cache(self, identifier: str) -> None:
        """Clear derived artifacts while retaining the saved definition and original files."""
        self.remove_project_cache(identifier, delete_project=False)

    def delete_project(self, identifier: str) -> None:
        """Reserve a project until its cache and saved registry entry have both been removed."""
        self.remove_project_cache(identifier, delete_project=True)

    def remove_project_cache(self, identifier: str, *, delete_project: bool) -> None:
        """Keep the file lease through disk cleanup while releasing the runtime state lock."""
        with self.lock:
            self.operations.reserve(
                identifier,
                "deleting" if delete_project else "clearing",
                active=self.active[0].id if self.active else None,
            )
        cache = None
        try:
            self.registry.get(identifier)
            with self.lock:
                cache = self.caches.pop(identifier, None)
            if cache is None:
                cache = ProjectCache(self.cache, identifier, self.cache_version)
                cache.acquire()
            cache.clear()
            if delete_project:
                self.registry.delete(identifier)
            else:
                self.registry.report_error(identifier, "")
        finally:
            if cache is not None:
                cache.release()
            with self.lock:
                self.operations.release(identifier)

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
        with self.lock:
            self.operations.stop()
        self.executor.shutdown(wait=True)
        with self.signal_lock, self.search_lock:
            self.signal = None
            self.search = None
        try:
            for cache in self.caches.values():
                cache.prune()
        finally:
            for cache in self.caches.values():
                cache.release()
