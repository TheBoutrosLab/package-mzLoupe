"""Expose an in-process test client to isolated browser tests over standard pipes."""

import json
import sys

from fastapi.testclient import TestClient


def serve_requests(client: TestClient) -> None:
    """Serve requests until the browser closes stdin; never start an HTTP server."""
    print("MZLOUPE_READY", flush=True)
    for line in sys.stdin:
        request = json.loads(line)
        response = client.request(request["method"], request["url"], json=request.get("body"))
        result = {"id": request["id"], "status": response.status_code, "body": response.json()}
        print("MZLOUPE_RESPONSE " + json.dumps(result), flush=True)
