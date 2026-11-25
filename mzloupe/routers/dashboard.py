"""Routes for the compiled dashboard and its matching static assets."""

from fastapi import APIRouter, FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from mzloupe.services.assets import DashboardAssets


class DashboardRoutes:
    """Serve the dashboard snapshot paired with this application instance."""

    def __init__(self, assets: DashboardAssets) -> None:
        """Use the asset snapshot whose lifetime is managed by the application."""
        self.assets = assets
        self.router = APIRouter()

    def register(self, app: FastAPI) -> None:
        """Mount static files and connect the dashboard entry point."""
        if self.assets.path.is_dir():
            app.mount(
                "/assets",
                StaticFiles(directory=self.assets.path / "assets"),
                name="assets",
            )
        self.router.add_api_route(
            "/",
            self.index,
            methods=["GET"],
        )
        app.include_router(self.router)

    def index(self) -> FileResponse:
        """Serve the matching dashboard or explain how to build missing assets."""
        return self.assets.index()
