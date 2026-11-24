"""Serve in-process ASGI test responses over stdin/stdout, without an HTTP server."""

import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import time

from fastapi.testclient import TestClient

from mzloupe.app import create_app
from mzloupe.demo import DemoProject
from psm_fixtures import seed_psm_rows


def main() -> None:
    """Keep a test project alive until the browser closes the input pipe."""
    with TemporaryDirectory(prefix="mzloupe-table-test-") as directory:
        root = Path(directory)
        manifest = DemoProject().write(root / "data")
        app = create_app(root / "cache", manifest)
        with TestClient(app) as client:
            for _ in range(100):
                state = client.get("/api/status").json()
                if state["state"] != "preparing":
                    break
                time.sleep(0.02)
            if state["state"] != "ready":
                raise RuntimeError(state)
            seed_psm_rows(app.state.runtime.active[1])
            print("MZLOUPE_READY", flush=True)
            for line in sys.stdin:
                request = json.loads(line)
                response = client.request(
                    request["method"],
                    request["url"],
                    json=request.get("body"),
                )
                result = {
                    "id": request["id"],
                    "status": response.status_code,
                    "body": response.json(),
                }
                print("MZLOUPE_RESPONSE " + json.dumps(result), flush=True)


if __name__ == "__main__":
    main()
