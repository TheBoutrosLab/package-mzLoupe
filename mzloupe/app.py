"""Compose the local project library, preparation runtime, and inspection API."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI

from mzloupe.routers.dashboard import DashboardRoutes
from mzloupe.routers.errors import ErrorHandlers
from mzloupe.routers.inspection import InspectionRoutes
from mzloupe.routers.library import LibraryRoutes
from mzloupe.routers.sources import SourceRoutes
from mzloupe.services.assets import DashboardAssets
from mzloupe.services.project_runtime import ProjectRuntime


def create_app(
    cache: str | Path | None = None,
    project_path: str | Path | None = None,
    registry: str | Path | None = None,
) -> FastAPI:
    """Build an API with a durable registry and one consistent dashboard snapshot."""
    runtime = ProjectRuntime(cache or Path.home() / ".cache/mzloupe", registry)
    assets = DashboardAssets(Path(__file__).parent / "static")

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        """Open an optional startup project and always release workers, leases, and assets."""
        try:
            if project_path:
                runtime.open(project_path)
            yield
        finally:
            try:
                runtime.close()
            finally:
                assets.close()

    app = FastAPI(title="mzLoupe", lifespan=lifespan)
    app.state.runtime = runtime
    ErrorHandlers.register(app)
    SourceRoutes(runtime).register(app)
    LibraryRoutes(runtime).register(app)
    InspectionRoutes(runtime).register(app)
    DashboardRoutes(assets).register(app)
    return app
