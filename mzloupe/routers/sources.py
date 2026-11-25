"""Configuration import/export, source inspection, and preparation entry points."""

from pathlib import Path
from typing import Any

from fastapi import APIRouter, FastAPI, HTTPException
from pydantic import BaseModel, Field

from mzloupe.models import ProjectInput
from mzloupe.readers.protein_grouping import ProteinGroupingFile
from mzloupe.services.files import FileBrowser
from mzloupe.services.project_files import ProjectFiles
from mzloupe.services.project_runtime import ProjectRuntime


class OpenRequest(BaseModel):
    """Identify a local manifest file to import or open."""

    path: str


class SaveProjectRequest(BaseModel):
    """Choose a server destination and explicitly allow replacement when requested."""

    directory: str = Field(min_length=1)
    filename: str = Field(min_length=1)
    project: ProjectInput
    overwrite: bool = False


class SourceRoutes:
    """Own source editing, file inspection, and preparation entry points."""

    def __init__(self, runtime: ProjectRuntime) -> None:
        """Keep the application runtime explicit and give this route group its own router."""
        self.runtime = runtime
        self.router = APIRouter(prefix="/api")

    def register(self, app: FastAPI) -> None:
        """Connect public handler methods to their existing HTTP endpoints."""
        self.router.add_api_route(
            "/status",
            self.status,
            methods=["GET"],
        )
        self.router.add_api_route(
            "/open",
            self.open_project,
            methods=["POST"],
            status_code=202,
        )
        self.router.add_api_route(
            "/import-project",
            self.import_project,
            methods=["POST"],
        )
        self.router.add_api_route(
            "/protein-groupings/inspect",
            self.inspect_grouping,
            methods=["POST"],
        )
        self.router.add_api_route(
            "/configuration",
            self.configuration,
            methods=["GET"],
        )
        self.router.add_api_route(
            "/save-project",
            self.save_project,
            methods=["POST"],
        )
        self.router.add_api_route(
            "/validate-project",
            self.validate_project,
            methods=["POST"],
        )
        self.router.add_api_route(
            "/open-configuration",
            self.open_configuration,
            methods=["POST"],
            status_code=202,
        )
        self.router.add_api_route(
            "/files",
            self.files,
            methods=["GET"],
        )
        app.include_router(self.router)

    def status(self) -> dict[str, Any]:
        """Report preparation state and the active session token."""
        with self.runtime.lock:
            return {
                **self.runtime.status,
                "token": self.runtime.token,
                "active_project_id": self.runtime.active[0].id if self.runtime.active else None,
            }

    def open_project(self, request: OpenRequest) -> dict[str, bool]:
        """Queue a validated local manifest for background preparation."""
        self.runtime.open(request.path)
        return {"accepted": True}

    @staticmethod
    def import_project(request: OpenRequest) -> dict[str, Any]:
        """Read a manifest into the editor without requiring all sources to exist."""
        return ProjectInput.load(
            Path(request.path).expanduser().resolve(),
            validate_files=False,
        ).model_dump()

    @staticmethod
    def inspect_grouping(request: OpenRequest) -> dict[str, int]:
        """Inspect both idXML group collections without opening or preparing a project."""
        path = Path(request.path).expanduser().resolve()
        try:
            return ProteinGroupingFile(path).summary()
        except (RuntimeError, OSError) as error:
            raise ValueError(f"Cannot read protein grouping idXML: {error}") from error

    def configuration(self) -> dict[str, Any] | None:
        """Return the active project configuration, if a prepared project exists."""
        with self.runtime.lock:
            if not self.runtime.active:
                return None
            return self.runtime.active[0].model_dump()

    @staticmethod
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

    @staticmethod
    def validate_project(project: ProjectInput) -> dict[str, list[dict[str, str]]]:
        """Check source paths without changing the active session."""
        return {"issues": project.file_issues()}

    def open_configuration(self, project: ProjectInput) -> dict[str, bool]:
        """Queue the editor's validated configuration without requiring a JSON file."""
        self.runtime.open_configuration(project)
        return {"accepted": True}

    @staticmethod
    def files(path: str | None = None, kind: str = "mzml") -> dict[str, Any]:
        """List local source files and directories for the project editor."""
        return FileBrowser().list_directory(path, kind)
