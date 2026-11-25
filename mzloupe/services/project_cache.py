"""Plan incremental preparation inside one stable cache directory per project."""

import hashlib
import json
from pathlib import Path
import shutil
from typing import Any

from filelock import FileLock, Timeout

from mzloupe.models import ProjectInput


class ProjectCache:
    """Track source validity separately from project identity and published revisions."""

    def __init__(self, root: Path, version: int) -> None:
        """Use a project-specific directory and the current derived-data format version."""
        self.root = root.expanduser().resolve()
        self.version = version
        self.lease: FileLock | None = None

    def acquire(self) -> None:
        """Keep a second server from writing or collecting this project's active artifacts."""
        self.root.parent.mkdir(parents=True, exist_ok=True)
        lease = FileLock(self.root.parent / ("." + self.root.name + ".lock"), thread_local=False)
        try:
            lease.acquire(timeout=0)
        except Timeout as error:
            raise ValueError("This project cache is in use by another mzLoupe server") from error
        self.lease = lease

    def release(self) -> None:
        """Release the project lease after this server finishes all scientific readers."""
        if self.lease is not None:
            self.lease.release()
            self.lease = None

    @staticmethod
    def signature(path: str) -> list[str | int]:
        """Inspect file identity cheaply without hashing or decoding gigabytes of signal."""
        source = Path(path)
        stat = source.stat()
        return [str(source), stat.st_size, stat.st_mtime_ns]

    def describe(self, project: ProjectInput) -> dict[str, Any]:
        """Record raw inputs and resolution scopes needed to invalidate dependent results."""
        acquisitions = {item.id: self.signature(item.mzml) for item in project.acquisitions}
        identifications = {}
        for (sample, layer, path), sources in project.identification_sources().items():
            key = json.dumps([sample, layer, path])
            scope = [
                [item.id, item.mzml, item.aliases, acquisitions[item.id]]
                for item in project.acquisitions
                if item.id in sources
            ]
            identifications[key] = [self.signature(path), scope]
        return {
            "version": self.version,
            "configuration": project.model_dump(),
            "acquisitions": acquisitions,
            "identifications": identifications,
            "groupings": [self.signature(item.path) for item in project.protein_groupings],
        }

    @staticmethod
    def fingerprint(description: dict[str, Any]) -> str:
        """Produce a validity stamp without using it as the project's identity."""
        return hashlib.sha256(json.dumps(description, sort_keys=True).encode()).hexdigest()

    def current(self) -> Path | None:
        """Return the published metadata snapshot, if the project has a usable cache."""
        marker = self.root / "current.json"
        try:
            record = json.loads(marker.read_text())
            name = record["workspace"]
            if not name.startswith("revision-") or Path(name).name != name:
                return None
            workspace = self.root / name
            if not all(
                Path(filename).name == filename and (workspace / filename).is_file()
                for filename in record["outputs"]
            ):
                return None
            if not (workspace / "catalog.sqlite").is_file():
                return None
            description = self.description(workspace)
            if not all(
                (workspace / (identifier + ".npz")).is_file()
                for identifier in description.get("acquisitions", {})
            ):
                return None
            return workspace
        except (OSError, ValueError, KeyError, TypeError):
            return None

    @staticmethod
    def description(workspace: Path | None) -> dict[str, Any]:
        """Read a completed snapshot's preparation manifest."""
        if workspace is None:
            return {}
        try:
            return json.loads((workspace / "prepared.json").read_text())
        except (OSError, ValueError):
            return {}

    def plan(self, project: ProjectInput) -> dict[str, int]:
        """Preview expensive acquisition work before preparation starts."""
        current = self.describe(project)
        previous = self.description(self.current())
        old = previous.get("acquisitions", {}) if previous.get("version") == self.version else {}
        added = sum(source not in old for source in current["acquisitions"])
        changed = sum(
            source in old and old[source] != value
            for source, value in current["acquisitions"].items()
        )
        reused = len(current["acquisitions"]) - added - changed
        return {"added": added, "changed": changed, "reused": reused}

    def publish(self, workspace: Path, description: dict[str, Any]) -> None:
        """Publish complete artifacts before atomically switching the project pointer."""
        prepared = workspace / "prepared.pending"
        prepared.write_text(json.dumps(description))
        prepared.replace(workspace / "prepared.json")
        pending = self.root / "current.pending"
        outputs = ["catalog.sqlite", "prepared.json"]
        outputs.extend(path.name for path in workspace.glob("*.npz"))
        outputs.extend(path.name for path in workspace.glob("*.mzML"))
        pending.write_text(json.dumps({"workspace": workspace.name, "outputs": outputs}))
        pending.replace(self.root / "current.json")

    def prune(self) -> None:
        """Remove superseded snapshots only after this server has finished its readers."""
        current = self.current()
        if not self.root.is_dir():
            return
        for workspace in self.root.glob("revision-*"):
            if workspace != current:
                shutil.rmtree(workspace)
