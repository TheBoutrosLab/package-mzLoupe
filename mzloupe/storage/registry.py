"""Persist the project library independently of disposable preparation caches."""

from contextlib import contextmanager
from collections.abc import Iterator
from datetime import datetime, timezone
from importlib.resources import files
import json
from pathlib import Path
import sqlite3
from typing import Any
from uuid import uuid4

from mzloupe.models import ProjectInput


class ProjectRegistry:
    """Own saved configurations, stable identities, and project library metadata."""

    def __init__(self, path: str | Path) -> None:
        """Create the small registry database without opening any scientific inputs."""
        self.path = Path(path).expanduser().resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        schema = files("mzloupe").joinpath("storage", "registry.sql").read_text()
        with self.connect() as connection:
            connection.executescript(schema)

    @staticmethod
    def default_path() -> Path:
        """Store durable project definitions outside the application's cache root."""
        return Path.home() / ".local/share/mzloupe/projects.sqlite"

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        """Open a short-lived connection with named rows and bounded write waiting."""
        connection = sqlite3.connect(self.path, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def get(self, identifier: str) -> dict[str, Any]:
        """Return one registered project or reject an unknown identity."""
        with self.connect() as connection:
            row = connection.execute("SELECT * FROM projects WHERE id=?", (identifier,)).fetchone()
        if row is None:
            raise ValueError("Unknown project")
        return self.decode(row)

    def list(self, include_archived: bool = False) -> list[dict[str, Any]]:
        """List saved definitions without inspecting source files or their caches."""
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM projects WHERE archived=0 OR ? "
                "ORDER BY COALESCE(opened_at, modified_at) DESC",
                (include_archived,),
            ).fetchall()
        return [self.decode(row) for row in rows]

    @staticmethod
    def decode(row: sqlite3.Row) -> dict[str, Any]:
        """Decode configuration snapshots without opening any scientific or cache files."""
        return {
            **dict(row),
            "archived": bool(row["archived"]),
            "configuration": json.loads(row["configuration"]),
            "prepared_configuration": (
                json.loads(row["prepared_configuration"]) if row["prepared_configuration"] else None
            ),
        }

    def save(self, project: ProjectInput, source_path: Path | None = None) -> dict[str, Any]:
        """Save changes under the same ID; an imported path remembers its registered identity."""
        now = datetime.now(timezone.utc).isoformat()
        with self.connect() as connection:
            if source_path is not None:
                existing = connection.execute(
                    "SELECT project_id AS id FROM project_sources WHERE path=?", (str(source_path),)
                ).fetchone()
                if existing is not None:
                    if "id" not in project.model_fields_set:
                        project.id = existing["id"]
                    elif existing["id"] != project.id:
                        connection.execute(
                            "UPDATE projects SET source_path=NULL WHERE id=?", (existing["id"],)
                        )
            previous = connection.execute(
                "SELECT configuration, revision FROM projects WHERE id=?", (project.id,)
            ).fetchone()
            configuration = project.model_dump_json()
            revision = 1 if previous is None else previous["revision"]
            if previous is not None and previous["configuration"] != configuration:
                revision += 1
            connection.execute(
                "INSERT INTO projects (id, configuration, revision, created_at, modified_at, "
                "source_path) VALUES (?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET "
                "configuration=excluded.configuration, revision=excluded.revision, "
                "modified_at=CASE WHEN projects.configuration!=excluded.configuration "
                "THEN excluded.modified_at ELSE projects.modified_at END, "
                "source_path=COALESCE(excluded.source_path, projects.source_path)",
                (
                    project.id,
                    configuration,
                    revision,
                    now,
                    now,
                    str(source_path) if source_path else None,
                ),
            )
            if source_path is not None:
                connection.execute(
                    "INSERT INTO project_sources (path, project_id) VALUES (?,?) "
                    "ON CONFLICT(path) DO UPDATE SET project_id=excluded.project_id",
                    (str(source_path), project.id),
                )
        return self.get(project.id)

    def opened(self, identifier: str) -> None:
        """Record recent use without treating an open as a configuration edit."""
        self.get(identifier)
        with self.connect() as connection:
            connection.execute(
                "UPDATE projects SET opened_at=? WHERE id=?",
                (datetime.now(timezone.utc).isoformat(), identifier),
            )

    def archive(self, identifier: str, archived: bool) -> None:
        """Hide or restore a project without removing its configuration or data."""
        self.get(identifier)
        with self.connect() as connection:
            connection.execute("UPDATE projects SET archived=? WHERE id=?", (archived, identifier))

    def duplicate(self, identifier: str) -> dict[str, Any]:
        """Create an independent project definition with fresh identity and no shared cache."""
        project = ProjectInput.model_validate(self.get(identifier)["configuration"])
        project.id = str(uuid4())
        project.name += " (copy)"
        return self.save(project)

    def delete(self, identifier: str) -> None:
        """Remove the saved definition; cache and source deletion are separate operations."""
        self.get(identifier)
        with self.connect() as connection:
            connection.execute("DELETE FROM projects WHERE id=?", (identifier,))

    def set_cache(self, identifier: str, directory: Path) -> None:
        """Remember this project's cache location independently of its portable manifest."""
        self.get(identifier)
        with self.connect() as connection:
            connection.execute(
                "UPDATE projects SET cache_directory=? WHERE id=?", (str(directory), identifier)
            )

    def report_error(self, identifier: str, message: str) -> None:
        """Remember a preparation problem so it remains visible in the project library."""
        with self.connect() as connection:
            connection.execute("UPDATE projects SET error=? WHERE id=?", (message, identifier))

    def prepared(self, project: ProjectInput, version: int) -> None:
        """Record the last successfully published configuration for cheap library summaries."""
        with self.connect() as connection:
            connection.execute(
                "UPDATE projects SET prepared_configuration=?, prepared_version=?, error='' "
                "WHERE id=?",
                (project.model_dump_json(), version, project.id),
            )

    def cache_cleared(self, identifier: str) -> None:
        """Forget prepared state while retaining all saved configuration and history metadata."""
        with self.connect() as connection:
            connection.execute(
                "UPDATE projects SET prepared_configuration=NULL, prepared_version=NULL, error='' "
                "WHERE id=?",
                (identifier,),
            )
