"""Project library endpoints, separate from scientific inspection routes."""

from pathlib import Path
from typing import Any

from fastapi import APIRouter, FastAPI
from pydantic import BaseModel

from mzloupe.models import ProjectInput
from mzloupe.services.project_runtime import ProjectRuntime


class ArchiveRequest(BaseModel):
    """Choose whether a saved project is hidden from the default library."""

    archived: bool


class LibraryRoutes:
    """Own saved-project management without loading scientific data."""

    def __init__(self, runtime: ProjectRuntime) -> None:
        """Keep the application runtime explicit and give this route group its own router."""
        self.runtime = runtime
        self.router = APIRouter(prefix="/api")

    def register(self, app: FastAPI) -> None:
        """Connect public handler methods to their existing HTTP endpoints."""
        self.router.add_api_route(
            "/library",
            self.projects,
            methods=["GET"],
        )
        self.router.add_api_route(
            "/library",
            self.save,
            methods=["POST"],
        )
        self.router.add_api_route(
            "/library/{identifier}",
            self.project,
            methods=["GET"],
        )
        self.router.add_api_route(
            "/library/{identifier}/open",
            self.open_project,
            methods=["POST"],
            status_code=202,
        )
        self.router.add_api_route(
            "/library/{identifier}/close",
            self.close_project,
            methods=["POST"],
        )
        self.router.add_api_route(
            "/library/{identifier}/duplicate",
            self.duplicate,
            methods=["POST"],
        )
        self.router.add_api_route(
            "/library/{identifier}",
            self.archive,
            methods=["PATCH"],
        )
        self.router.add_api_route(
            "/library/{identifier}/cache",
            self.clear_cache,
            methods=["DELETE"],
        )
        self.router.add_api_route(
            "/library/{identifier}",
            self.delete,
            methods=["DELETE"],
        )
        self.router.add_api_route(
            "/preparation-plan",
            self.plan,
            methods=["POST"],
        )
        app.include_router(self.router)

    def projects(self, include_archived: bool = False) -> list[dict[str, Any]]:
        """List saved projects without loading their source data."""
        return [
            self.runtime.library_record(row) for row in self.runtime.registry.list(include_archived)
        ]

    def save(self, project: ProjectInput) -> dict[str, Any]:
        """Create or update a saved project, allowing empty drafts and missing source files."""
        return self.runtime.library_record(self.runtime.save_configuration(project))

    def project(self, identifier: str) -> dict[str, Any]:
        """Read a saved configuration immediately, without preparing it."""
        return self.runtime.library_record(self.runtime.registry.get(identifier))

    def open_project(self, identifier: str) -> dict[str, bool]:
        """Prepare or reuse the selected project's current saved definition."""
        self.runtime.open_project(identifier)
        return {"accepted": True}

    def close_project(self, identifier: str) -> dict[str, bool]:
        """Close the active scientific workspace while retaining its saved project and cache."""
        self.runtime.close_project(identifier)
        return {"closed": True}

    def duplicate(self, identifier: str) -> dict[str, Any]:
        """Register a copy with a new identity, leaving the original cache independent."""
        return self.runtime.library_record(self.runtime.registry.duplicate(identifier))

    def archive(self, identifier: str, request: ArchiveRequest) -> dict[str, Any]:
        """Archive or restore a project without deleting configuration or source data."""
        self.runtime.registry.archive(identifier, request.archived)
        return self.runtime.library_record(self.runtime.registry.get(identifier))

    def clear_cache(self, identifier: str) -> dict[str, bool]:
        """Remove only derived cache data for an inactive project."""
        self.runtime.clear_cache(identifier)
        return {"cleared": True}

    def delete(self, identifier: str) -> dict[str, bool]:
        """Remove an inactive project's saved definition and cache, preserving original inputs."""
        self.runtime.delete_project(identifier)
        return {"deleted": True}

    def plan(self, project: ProjectInput) -> dict[str, int]:
        """Preview how many acquisition preparations can be reused before saving edits."""
        project.resolve_paths(Path.cwd())
        return self.runtime.preparation_plan(project)
