"""SQLite connections, schema initialization, and catalog queries."""

import json
import sqlite3
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from importlib.resources import files
from pathlib import Path
from typing import Any, Protocol


class GroupingAnnotations(Protocol):
    """Describe session metadata that can annotate catalog PSM payloads."""

    def enrich(self, rows: list[dict[str, Any]]) -> None:
        """Attach available inference assignments to the supplied PSM dictionaries."""
        ...

    def summaries(self) -> list[dict[str, Any]]:
        """Describe grouping inputs and their sample/layer applicability."""
        ...


class ProjectCatalog:
    """Own short-lived SQLite connections and queries for a prepared project."""

    def __init__(self, path: str | Path) -> None:
        """Remember the database path without creating or opening the database."""
        self.path = path
        self.groupings: GroupingAnnotations | None = None

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        """Yield a row-aware connection, commit on success, and always close it."""
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def create(self) -> None:
        """Create the tables and indexes defined by the packaged SQL schema."""
        schema_path = files("mzloupe").joinpath("storage", "schema.sql")
        schema = schema_path.read_text(encoding="utf-8")

        with self.connect() as connection:
            connection.executescript(schema)

    def rows(self, sql: str, parameters: Sequence[Any] = ()) -> list[dict[str, Any]]:
        """Execute a parameterized query and return ordinary dictionaries."""
        with self.connect() as db:
            return [dict(row) for row in db.execute(sql, parameters)]

    def psm_rows(self, sql: str, parameters: Sequence[Any] = ()) -> list[dict[str, Any]]:
        """Decode accession arrays in PSM payloads without extra database queries."""
        rows = self.rows(sql, parameters)
        for row in rows:
            row["protein_accessions"] = json.loads(row["protein_accessions"])
        if self.groupings is not None:
            self.groupings.enrich(rows)
        return rows

    def scan(self, source: str, ordinal: int) -> dict[str, Any]:
        """Look up one zero-based scan ordinal within a specific acquisition."""
        rows = self.rows("SELECT * FROM scans WHERE source=? AND ordinal=?", (source, ordinal))
        if not rows:
            raise ValueError("Unknown source or spectrum")
        return rows[0]

    def candidates(self, source: str, native: str) -> list[dict[str, Any]]:
        """List candidates for a native scan ID, keeping fractions independent."""
        return self.psm_rows(
            "SELECT * FROM psms WHERE source=? AND native=? ORDER BY layer, rank",
            (source, native),
        )

    def precursor_psms(
        self,
        *,
        source: str,
        start: float,
        stop: float,
        mz_min: float,
        mz_max: float,
    ) -> list[dict[str, Any]]:
        """Find resolved MS2 candidates within one fraction's RT and precursor window.

        Retention times are in seconds. Match peptide precursor m/z rather than
        the scan's isolation center. Include every layer and rank without table
        search filters or pagination so other elution peaks retain their evidence.
        """
        return self.psm_rows(
            "SELECT p.*, a.fraction, s.ordinal, s.rt "
            "FROM psms p "
            "JOIN acquisitions a ON p.source=a.id "
            "JOIN scans s ON p.source=s.source AND p.native=s.native "
            "WHERE p.source=? AND p.resolved=1 AND s.level=2 "
            "AND s.rt BETWEEN ? AND ? AND p.precursor_mz BETWEEN ? AND ? "
            "ORDER BY s.rt, s.ordinal, p.rank, p.layer, p.id",
            (source, start, stop, mz_min, mz_max),
        )

    def acquisitions(self, layer: str | None = None) -> list[dict[str, Any]]:
        """Summarize each fraction's scan count, layers, and identified MS2 count."""
        rows = self.rows("SELECT * FROM acquisitions ORDER BY sample, fraction")
        for row in rows:
            row.pop("path")
            source = row["id"]
            layers = self.rows("SELECT name FROM layers WHERE source=?", (source,))
            row["layers"] = [item["name"] for item in layers]
            scans = self.rows(
                "SELECT count(*) AS n FROM scans WHERE source=? AND level=2",
                (source,),
            )
            row["ms2"] = scans[0]["n"]
            row["identified"] = None
            if layer in row["layers"]:
                row["identified"] = self.rows(
                    "SELECT count(DISTINCT native) AS n FROM psms "
                    "WHERE source=? AND layer=? AND resolved=1",
                    (source, layer),
                )[0]["n"]
        return rows
