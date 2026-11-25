"""Own a compiled dashboard snapshot for the lifetime of its paired API."""

from contextlib import ExitStack
from pathlib import Path
import shutil
from tempfile import TemporaryDirectory

from fastapi import HTTPException
from fastapi.responses import FileResponse


class DashboardAssets:
    """Keep a running API paired with the frontend build it started with."""

    def __init__(self, source: Path) -> None:
        """Snapshot available assets without requiring a frontend build for API-only use."""
        self.resources = ExitStack()
        directory = self.resources.enter_context(TemporaryDirectory(prefix="mzloupe-assets-"))
        self.path = Path(directory) / "static"
        if source.is_dir():
            shutil.copytree(source, self.path)

    def index(self) -> FileResponse:
        """Serve the matching dashboard or explain how to build missing assets."""
        if not (self.path / "index.html").is_file():
            raise HTTPException(503, "Build client assets with npm run build in web/")
        return FileResponse(self.path / "index.html")

    def close(self) -> None:
        """Remove the snapshot after API requests and background preparation have finished."""
        self.resources.close()
