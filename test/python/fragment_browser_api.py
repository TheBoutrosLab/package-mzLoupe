"""Expose a prepared conventional DIA project to browser tests over pipes."""

from pathlib import Path
from tempfile import TemporaryDirectory

from fastapi.testclient import TestClient
from browser_api import serve_requests
from dia_fixtures import write_dia_project
from psm_fixtures import wait_for_project

from mzloupe.app import create_app


def main() -> None:
    """Serve disposable DIA data with no listening port or persistent server."""
    with TemporaryDirectory(prefix="mzloupe-fragment-test-") as directory:
        root = Path(directory)
        manifest = write_dia_project(root / "data")
        app = create_app(root / "cache", manifest, registry=root / "projects.sqlite")
        with TestClient(app) as client:
            wait_for_project(client)
            serve_requests(client)


if __name__ == "__main__":
    main()
