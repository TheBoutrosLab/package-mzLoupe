"""Plan incremental preparation inside one stable cache directory per project."""

import hashlib
import json
from pathlib import Path
import shutil
from tempfile import mkdtemp
from typing import Any
from uuid import UUID

from filelock import FileLock, Timeout

from mzloupe.models import ProjectInput


class ProjectCache:
    """Track source validity separately from project identity and published revisions."""

    def __init__(self, cache_root: Path, identifier: str, version: int) -> None:
        """Derive one project's directory exclusively from the configured root and UUID."""
        if str(UUID(identifier)) != identifier:
            raise ValueError("Invalid project ID")
        self.cache_root = cache_root.expanduser().resolve()
        self.root = self.cache_root / "projects" / identifier
        self.version = version
        self.lease: FileLock | None = None

    def validate_path(self, path: Path) -> Path:
        """Reject traversal and symlinks before accessing this project's cache artifacts.

        Keep the original path instead of following a link into another project or
        outside the configured root. Check again for each operation, since directory
        entries may change after this object is constructed.
        """
        if not path.is_relative_to(self.root) or path.resolve() != path:
            raise ValueError("Cache path must stay inside its project directory without symlinks")
        return path

    def workspace(self, path: Path) -> Path:
        """Accept only a direct revision directory owned by this project."""
        if path.parent != self.root or not path.name.startswith("revision-"):
            raise ValueError("Invalid project cache revision directory")
        return self.validate_path(path)

    def stage(self) -> Path:
        """Create a temporary revision only within the checked project directory."""
        self.validate_path(self.root).mkdir(parents=True, exist_ok=True)
        return Path(mkdtemp(prefix="revision-", dir=self.validate_path(self.root)))

    def discard(self, workspace: Path) -> None:
        """Delete one checked revision after failed or superseded preparation."""
        shutil.rmtree(self.workspace(workspace))

    def clear(self) -> None:
        """Delete only this project's checked directory; a missing cache is harmless."""
        directory = self.validate_path(self.root)
        try:
            shutil.rmtree(directory)
        except FileNotFoundError:
            pass

    def acquire(self) -> None:
        """Keep a second server from writing or collecting this project's active artifacts."""
        self.validate_path(self.root)
        self.root.parent.mkdir(parents=True, exist_ok=True)
        lock_path = self.root.parent / ("." + self.root.name + ".lock")
        if lock_path.resolve() != lock_path:
            raise ValueError("Project cache lock must not follow symlinks")
        lease = FileLock(lock_path, thread_local=False)
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
        return {"version": self.version, **self.inputs(project)}

    @staticmethod
    def inputs(project: ProjectInput) -> dict[str, Any]:
        """Describe scientific inputs without requiring or creating a cache directory."""
        acquisitions = {item.id: ProjectCache.signature(item.mzml) for item in project.acquisitions}
        identifications = {}
        for (sample, layer, path), sources in project.identification_sources().items():
            key = json.dumps([sample, layer, path])
            scope = [
                [item.id, item.mzml, item.aliases, acquisitions[item.id]]
                for item in project.acquisitions
                if item.id in sources
            ]
            identifications[key] = [ProjectCache.signature(path), scope]
        return {
            "configuration": project.model_dump(),
            "acquisitions": acquisitions,
            "identifications": identifications,
            "groupings": [ProjectCache.signature(item.path) for item in project.protein_groupings],
        }

    @staticmethod
    def fingerprint(description: dict[str, Any]) -> str:
        """Produce a validity stamp without using it as the project's identity."""
        return hashlib.sha256(json.dumps(description, sort_keys=True).encode()).hexdigest()

    def current(self) -> Path | None:
        """Return the published metadata snapshot, if the project has a usable cache."""
        try:
            marker = self.validate_path(self.root / "current.json")
            record = json.loads(marker.read_text())
            name = record["workspace"]
            if (
                not isinstance(name, str)
                or not name.startswith("revision-")
                or Path(name).name != name
            ):
                return None
            workspace = self.workspace(self.root / name)
            if not all(
                Path(filename).name == filename
                and self.validate_path(workspace / filename).is_file()
                for filename in record["outputs"]
            ):
                return None
            if not self.validate_path(workspace / "catalog.sqlite").is_file():
                return None
            self.validate_path(workspace / "prepared.json")
            description = self.description(workspace)
            if not all(
                self.validate_path(workspace / (identifier + ".npz")).is_file()
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
            record = json.loads((workspace / "prepared.json").read_text())
            return record if isinstance(record, dict) else {}
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
        self.workspace(workspace)
        prepared = self.validate_path(workspace / "prepared.pending")
        prepared.write_text(json.dumps(description))
        prepared.replace(self.validate_path(workspace / "prepared.json"))
        pending = self.validate_path(self.root / "current.pending")
        outputs = ["catalog.sqlite", "prepared.json"]
        outputs.extend(self.validate_path(path).name for path in workspace.glob("*.npz"))
        outputs.extend(self.validate_path(path).name for path in workspace.glob("*.mzML"))
        pending.write_text(json.dumps({"workspace": workspace.name, "outputs": outputs}))
        pending.replace(self.validate_path(self.root / "current.json"))

    def prune(self) -> None:
        """Remove superseded snapshots only after this server has finished its readers."""
        self.validate_path(self.root)
        current = self.current()
        if not self.root.is_dir():
            return
        for workspace in self.root.glob("revision-*"):
            if workspace != current:
                self.discard(workspace)
