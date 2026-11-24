"""Local API, project lifecycle, and compiled dashboard serving."""

from __future__ import annotations

from collections.abc import AsyncIterator
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
import hashlib
import json
from pathlib import Path
import shutil
from tempfile import mkdtemp, TemporaryDirectory
from threading import Lock
from typing import Any
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from mzloupe.models import ProjectInput, XicRequest, MapTargetRequest
from mzloupe.psm_models import PsmFilters, PsmQuery
from mzloupe.services.psm_search import PsmSearch
from mzloupe.services.files import FileBrowser
from mzloupe.services.preparation import ProjectPreparer
from mzloupe.services.protein_grouping import ProteinGroupings
from mzloupe.readers.protein_grouping import ProteinGroupingFile
from mzloupe.services.project_files import ProjectFiles
from mzloupe.services.signal import SignalService, FragmentAnnotator
from mzloupe.storage.catalog import ProjectCatalog


class OpenRequest(BaseModel):
    """Identify a local manifest file to import or open."""

    path: str


class SaveProjectRequest(BaseModel):
    """Choose a server destination and explicitly allow replacement when requested."""

    directory: str = Field(min_length=1)
    filename: str = Field(min_length=1)
    project: ProjectInput
    overwrite: bool = False


class ProjectRuntime:
    """Prepare projects in the background and publish one complete active session."""

    # Rebuild catalogs whenever the stored schema or interpretation changes.
    cache_version = 5

    def __init__(self, cache: str | Path) -> None:
        """Create cache storage, a preparation worker, and session synchronization."""
        self.cache = Path(cache)
        self.cache.mkdir(parents=True, exist_ok=True)
        self.executor = ThreadPoolExecutor(max_workers=1)
        self.lock = Lock()
        self.signal_lock = Lock()
        self.search_lock = Lock()
        self.search: PsmSearch | None = None
        self.active: tuple[ProjectInput, ProjectCatalog, Path] | None = None
        self.signal: SignalService | None = None
        self.status: dict[str, Any] = {
            "state": "empty",
            "message": "Open a local project",
            "progress": 0,
        }
        self.token: str | None = None

    def open(self, path: str | Path) -> None:
        """Validate a local project manifest and enqueue its preparation."""
        project = ProjectInput.load(Path(path).expanduser().resolve())
        self.open_configuration(project)

    def open_configuration(self, project: ProjectInput) -> None:
        """Validate edited paths before replacing the current session and queuing work."""
        project.resolve_paths(Path.cwd())
        with self.lock:
            if self.status["state"] == "preparing":
                raise ValueError("Project preparation is already running")
            self.status = {"state": "preparing", "message": "Reading sources", "progress": 0}
            self.active = None
            self.token = None
        self.executor.submit(self.prepare, project)

    def progress(self, message: str, progress: float) -> None:
        """Publish a preparation message and fractional completion under the lock."""
        with self.lock:
            self.status = {"state": "preparing", "message": message, "progress": progress}

    def fingerprint(self, project: ProjectInput) -> str:
        """Hash the configuration, cache format, and source sizes/modification times."""
        paths = [Path(item.mzml) for item in project.acquisitions]
        paths.extend(Path(path) for _, _, path in project.identification_sources())
        records = [(str(path), path.stat().st_size, path.stat().st_mtime_ns) for path in paths]
        content = json.dumps(
            [self.cache_version, project.model_dump(exclude={"protein_groupings"}), records],
            sort_keys=True,
        ).encode()
        return hashlib.sha256(content).hexdigest()

    def prepare(self, project: ProjectInput) -> None:
        """Reuse a complete cache or build a new workspace before publishing it.

        Preparation runs in the worker. Failures become session status messages
        and incomplete workspaces are removed rather than exposed to the API.
        """
        try:
            key = self.fingerprint(project)
        except OSError as error:
            with self.lock:
                self.status = {"state": "error", "message": str(error), "progress": 0}
            return
        marker = self.cache / f"{key}.json"
        if marker.is_file():
            workspace = self.cache / json.loads(marker.read_text())["workspace"]
            if (workspace / "catalog.sqlite").is_file():
                catalog = ProjectCatalog(workspace / "catalog.sqlite")
                try:
                    catalog.groupings = ProteinGroupings(project, catalog)
                except Exception as error:
                    with self.lock:
                        self.status = {"state": "error", "message": str(error), "progress": 0}
                    return
                with self.signal_lock:
                    self.signal = None
                with self.lock:
                    self.active = (project, catalog, workspace)
                    self.token = workspace.name + (
                        "-" + uuid4().hex if project.protein_groupings else ""
                    )
                    self.status = {"state": "ready", "message": project.name, "progress": 1}
                return
        workspace = Path(mkdtemp(prefix="project-", dir=self.cache))
        try:
            catalog = ProjectPreparer(workspace).prepare(project, self.progress)
            catalog.groupings = ProteinGroupings(project, catalog)
            if self.fingerprint(project) != key:
                raise ValueError("A source changed during preparation. Open the project again.")
            pending_marker = workspace / "complete.json"
            pending_marker.write_text(json.dumps({"workspace": workspace.name}))
            pending_marker.replace(marker)
            with self.lock:
                self.active = (project, catalog, workspace)
                self.token = workspace.name + (
                    "-" + uuid4().hex if project.protein_groupings else ""
                )
                self.status = {"state": "ready", "message": project.name, "progress": 1}
        except Exception as error:
            shutil.rmtree(workspace)
            with self.lock:
                self.status = {"state": "error", "message": str(error), "progress": 0}

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
        """Finish preparation and release the cached native reader and signal results."""
        self.executor.shutdown(wait=True)
        with self.signal_lock:
            self.signal = None
        with self.search_lock:
            self.search = None


def create_app(cache: str | Path | None = None, project_path: str | Path | None = None) -> FastAPI:
    """Build a local API with project lifecycle hooks and a matching dashboard copy."""
    runtime = ProjectRuntime(cache or Path.home() / ".cache/mzloupe")
    # Keep the loaded dashboard and Python API together across package upgrades.
    asset_snapshot = TemporaryDirectory(prefix="mzloupe-assets-")
    assets = Path(asset_snapshot.name) / "static"
    packaged_assets = Path(__file__).parent / "static"
    if packaged_assets.is_dir():
        shutil.copytree(packaged_assets, assets)

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        """Open an optional startup project and release worker/assets on shutdown."""
        if project_path:
            runtime.open(project_path)
        yield
        runtime.close()
        asset_snapshot.cleanup()

    app = FastAPI(title="mzLoupe", lifespan=lifespan)
    app.state.runtime = runtime

    @app.exception_handler(ValueError)
    async def value_error(_request: Request, error: ValueError) -> JSONResponse:
        """Expose expected input and project errors as readable HTTP 400 responses."""
        return JSONResponse({"detail": str(error)}, status_code=400)

    @app.get("/api/status")
    def status() -> dict[str, Any]:
        """Report preparation state and the active session token."""
        with runtime.lock:
            return {**runtime.status, "token": runtime.token}

    @app.post("/api/open", status_code=202)
    def open_project(request: OpenRequest) -> dict[str, bool]:
        """Queue a validated local manifest for background preparation."""
        runtime.open(request.path)
        return {"accepted": True}

    @app.post("/api/import-project")
    def import_project(request: OpenRequest) -> dict[str, Any]:
        """Read a manifest into the editor without requiring all sources to exist."""
        return ProjectInput.load(
            Path(request.path).expanduser().resolve(),
            validate_files=False,
        ).model_dump()

    @app.post("/api/protein-groupings/inspect")
    def inspect_grouping(request: OpenRequest) -> dict[str, int]:
        """Inspect both idXML group collections without opening or preparing a project."""
        path = Path(request.path).expanduser().resolve()
        try:
            return ProteinGroupingFile(path).summary()
        except (RuntimeError, OSError) as error:
            raise ValueError(f"Cannot read protein grouping idXML: {error}") from error

    @app.get("/api/configuration")
    def configuration() -> dict[str, Any] | None:
        """Return the active project configuration, if a prepared project exists."""
        with runtime.lock:
            if not runtime.active:
                return None
            return runtime.active[0].model_dump()

    @app.post("/api/save-project")
    def save_project(request: SaveProjectRequest) -> dict[str, str]:
        """Save the editor's configuration on the server without changing its session."""
        try:
            path = ProjectFiles.save(
                request.project,
                directory=request.directory,
                filename=request.filename,
                overwrite=request.overwrite,
            )
        except FileExistsError as error:
            raise HTTPException(
                status_code=409,
                detail="A file with this name already exists in the server directory.",
            ) from error
        return {"path": str(path)}

    @app.post("/api/validate-project")
    def validate_project(project: ProjectInput) -> dict[str, list[dict[str, str]]]:
        """Check source paths without changing the active session."""
        return {"issues": project.file_issues()}

    @app.post("/api/open-configuration", status_code=202)
    def open_configuration(project: ProjectInput) -> dict[str, bool]:
        """Queue the editor's validated configuration without requiring a JSON file."""
        runtime.open_configuration(project)
        return {"accepted": True}

    @app.get("/api/files")
    def files(path: str | None = None, kind: str = "mzml") -> dict[str, Any]:
        """List local source files and directories for the project editor."""
        return FileBrowser().list_directory(path, kind)

    @app.get("/api/projects/{token}")
    def project(token: str, layer: str | None = None) -> dict[str, Any]:
        """Return the project name and per-fraction identification summaries."""
        project, catalog, _ = runtime.snapshot(token)
        return {
            "name": project.name,
            "acquisitions": catalog.acquisitions(layer),
            "protein_groupings": catalog.groupings.summaries() if catalog.groupings else [],
        }

    @app.get("/api/projects/{token}/psms")
    def psms(
        token: str,
        sample: str,
        source: str | None = None,
        page: int = Query(0, ge=0),
        page_size: int = Query(50, ge=10, le=200),
        filters: str = "{}",
        grouping: str = "",
        sort_by: str = "",
        sort_direction: str = "asc",
    ) -> dict[str, Any]:
        """Filter and sort complete PSM results before paginating the table response."""
        query = PsmQuery.model_validate(
            {
                "sample": sample,
                "source": source,
                "filters": PsmFilters.model_validate_json(filters),
                "grouping": grouping,
                "sort_by": sort_by,
                "sort_direction": sort_direction,
                "page": page,
                "page_size": page_size,
            }
        )
        with runtime.search_lock:
            return runtime.search_service(token).page(query)

    @app.get("/api/projects/{token}/sources/{source}/map")
    def map_data(token: str, source: str) -> dict[str, Any]:
        """Load the prepared MS1 map for one fraction."""
        _, catalog, workspace = runtime.snapshot(token)
        return SignalService(catalog, workspace).map(source)

    @app.get("/api/projects/{token}/sources/{source}/spectra/{ordinal}")
    def spectrum(token: str, source: str, ordinal: int) -> dict[str, Any]:
        """Read a single spectrum while serializing native signal access."""
        with runtime.signal_lock:
            return runtime.signal_service(token).spectrum(source, ordinal)

    @app.post("/api/projects/{token}/map-target")
    def map_target(token: str, request: MapTargetRequest) -> dict[str, Any]:
        """Resolve a selected map cell to a measured precursor target."""
        with runtime.signal_lock:
            return runtime.signal_service(token).map_target(request)

    @app.post("/api/projects/{token}/xic")
    def xic(token: str, request: XicRequest) -> dict[str, Any]:
        """Extract the requested MS1 trace from disk-backed spectra."""
        with runtime.signal_lock:
            return runtime.signal_service(token).xic(request)

    @app.get("/api/projects/{token}/psms/{psm_id}/annotations")
    def annotations(
        token: str,
        psm_id: int,
        ppm: float = Query(20, gt=0, le=1000),
    ) -> list[dict[str, int | str | float]]:
        """Annotate a resolved PSM's measured spectrum with theoretical fragments."""
        _, catalog, _ = runtime.snapshot(token)
        rows = catalog.rows("SELECT * FROM psms WHERE id=?", (psm_id,))
        if not rows or not rows[0]["resolved"]:
            raise ValueError("PSM has no resolved spectrum")
        psm = rows[0]
        scan = catalog.rows(
            "SELECT ordinal FROM scans WHERE source=? AND native=?",
            (psm["source"], psm["native"]),
        )[0]
        with runtime.signal_lock:
            peaks = runtime.signal_service(token).spectrum(psm["source"], scan["ordinal"])
        return FragmentAnnotator().annotate(peaks, psm["sequence"], ppm)

    if assets.is_dir():
        app.mount(
            "/assets",
            StaticFiles(directory=assets / "assets"),
            name="assets",
        )

    @app.get("/")
    def dashboard() -> FileResponse:
        """Serve the dashboard snapshot paired with this running API instance."""
        if not (assets / "index.html").is_file():
            raise HTTPException(503, "Build client assets with npm run build in web/")
        return FileResponse(assets / "index.html")

    return app
