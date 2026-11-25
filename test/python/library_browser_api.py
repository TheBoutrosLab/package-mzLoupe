"""Start a saved synthetic project library without activating scientific preparation."""

from pathlib import Path
from tempfile import TemporaryDirectory

from fastapi.testclient import TestClient
from browser_api import serve_requests

from mzloupe.app import create_app
from mzloupe.demo import DemoProject
from mzloupe.models import ProjectInput


def main() -> None:
    """Serve the real project library API with disposable data, registry, and cache."""
    with TemporaryDirectory(prefix="mzloupe-library-test-") as directory:
        root = Path(directory)
        manifest = DemoProject().write(root / "data")
        app = create_app(root / "cache", registry=root / "projects.sqlite")
        app.state.runtime.registry.save(ProjectInput.load(manifest), source_path=manifest)
        with TestClient(app) as client:
            serve_requests(client)


if __name__ == "__main__":
    main()
