"""Serve in-process ASGI test responses over stdin/stdout, without an HTTP server."""

from pathlib import Path
from tempfile import TemporaryDirectory

from fastapi.testclient import TestClient
from browser_api import serve_requests
from psm_fixtures import seed_psm_rows, wait_for_project

from mzloupe.app import create_app
from mzloupe.demo import DemoProject


def main() -> None:
    """Keep a test project alive until the browser closes the input pipe."""
    with TemporaryDirectory(prefix="mzloupe-table-test-") as directory:
        root = Path(directory)
        manifest = DemoProject().write(root / "data")
        app = create_app(root / "cache", manifest, registry=root / "projects.sqlite")
        with TestClient(app) as client:
            wait_for_project(client)
            seed_psm_rows(app.state.runtime.active[1])
            serve_requests(client)


if __name__ == "__main__":
    main()
