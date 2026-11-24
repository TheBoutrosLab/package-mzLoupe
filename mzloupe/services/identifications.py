"""Resolve identification provenance and import candidate records into SQLite."""

from __future__ import annotations

from collections.abc import Sequence
import json
import math
from pathlib import Path
import sqlite3
from urllib.parse import unquote

import pyopenms as oms

from mzloupe.models import AcquisitionInput, ProjectInput
from mzloupe.readers.idxml import IdentificationRecord, IdXMLReader
from mzloupe.storage.catalog import ProjectCatalog


class SpectrumResolver:
    """Match PSM references to MS2 scans within their eligible acquisitions.

    Source hints constrain the eligible acquisitions before native spectrum IDs
    are matched. Ambiguous or contradictory references remain unresolved.
    """

    def __init__(
        self,
        acquisitions: Sequence[AcquisitionInput],
        connection: sqlite3.Connection,
    ) -> None:
        """Use the registered acquisitions and the import transaction's catalog."""
        self.acquisitions = {item.id: item for item in acquisitions}
        self.connection = connection

    @staticmethod
    def source_name(value: str) -> str:
        """Normalize source basenames across paths, URLs, case, and compression."""
        normalized = unquote(value).replace("\\", "/")
        name = normalized.rsplit("/", 1)[-1]
        if name.lower().endswith(".gz"):
            name = name[:-3]
        return Path(name).stem.casefold()

    def sources_for_hint(self, hint: str) -> set[str]:
        """Find acquisitions matching a filename hint or a registered alias."""
        name = self.source_name(hint)
        matches = set()
        for source, acquisition in self.acquisitions.items():
            names = [acquisition.mzml, *acquisition.aliases]
            if name in {self.source_name(value) for value in names}:
                matches.add(source)
        return matches

    def provenance(self, record: IdentificationRecord) -> tuple[set[str], str]:
        """Return eligible acquisition IDs and an explanation for invalid hints.

        Merge indices refer to the identification run's source list, whose order
        can differ from the project's fraction order.
        """
        constraints = []
        for hint in (record["base_name"], record["file_origin"]):
            if hint:
                matches = self.sources_for_hint(hint)
                # IDMerger may record an idXML filename rather than an mzML.
                # Only matching acquisition hints constrain the source set.
                if matches:
                    constraints.append(matches)

        paths = record["spectra_data"]
        index = record["id_merge_index"]
        if index != "":
            try:
                position = int(index)
            except ValueError:
                return set(), "Invalid id_merge_index"
            if position < 0 or position >= len(paths):
                return set(), "id_merge_index is outside this run's spectra_data"
            constraints.append(self.sources_for_hint(paths[position]))
        elif len(paths) == 1:
            constraints.append(self.sources_for_hint(paths[0]))

        if constraints:
            sources = set(self.acquisitions).intersection(*constraints)
            reason = "" if sources else "Source metadata does not match a registered acquisition"
            return sources, reason

        explicit = record["base_name"] or record["file_origin"]
        if explicit and not paths:
            return set(), "Source metadata does not match a registered acquisition"
        return set(self.acquisitions), ""

    def resolve(self, record: IdentificationRecord) -> tuple[str | None, str]:
        """Resolve exactly one source or return the reason it remains ambiguous."""
        eligible, reason = self.provenance(record)
        unresolved_reason = reason or (
            "Spectrum reference was not found in the associated acquisitions"
        )
        if not eligible:
            return None, unresolved_reason

        # Source hints also let SQLite use its existing (source, native) index.
        # Searching by native ID alone scans the entire catalog for every PSM.
        placeholders = ", ".join("?" for _ in eligible)
        rows = self.connection.execute(
            "SELECT source FROM scans WHERE native=? AND level=2 "
            f"AND source IN ({placeholders})",
            (record["native"], *sorted(eligible)),
        ).fetchall()
        matches = {row["source"] for row in rows}
        if len(matches) == 1:
            return matches.pop(), ""
        if len(matches) > 1:
            return None, "Spectrum reference occurs in multiple fractions"

        return None, unresolved_reason


class IdentificationImporter:
    """Import each sample/layer file once while preserving its source links.

    Each file is handled in one transaction: register its layers, resolve each
    candidate's acquisition, and insert its scientific values into the catalog.
    """

    insert_psm_sql = """
        INSERT INTO psms (
            sample,
            source,
            layer,
            native,
            sequence,
            peptide,
            charge,
            score,
            score_type,
            higher_better,
            rank,
            resolved,
            link_reason,
            source_path,
            precursor_mz,
            precursor_mz_origin,
            protein_accessions
        ) VALUES (
            :sample,
            :source,
            :layer,
            :native,
            :sequence,
            :peptide,
            :charge,
            :score,
            :score_type,
            :higher_better,
            :rank,
            :resolved,
            :link_reason,
            :source_path,
            :precursor_mz,
            :precursor_mz_origin,
            :protein_accessions
        )
    """

    def __init__(self, catalog: ProjectCatalog, project: ProjectInput) -> None:
        """Use the prepared scan catalog and the project's file associations."""
        self.catalog = catalog
        self.project = project

    def import_sources(self) -> None:
        """Import the grouped identification sources declared by the project."""
        identification_sources = self.project.identification_sources()
        for (sample, layer, path), source_ids in identification_sources.items():
            self.import_source(
                sample=sample,
                layer=layer,
                path=path,
                source_ids=source_ids,
            )

    def import_source(
        self,
        *,
        sample: str,
        layer: str,
        path: str | Path,
        source_ids: set[str],
    ) -> None:
        """Import one idXML against its eligible acquisitions in one transaction."""
        acquisitions = [item for item in self.project.acquisitions if item.id in source_ids]
        with self.catalog.connect() as connection:
            resolver = SpectrumResolver(
                acquisitions=acquisitions,
                connection=connection,
            )
            self.register_layers(
                connection=connection,
                source_ids=source_ids,
                layer=layer,
            )
            for record in IdXMLReader(path).records():
                source, link_reason = resolver.resolve(record)
                row = {
                    **self.candidate_values(record),
                    "sample": sample,
                    "source": source,
                    "layer": layer,
                    "resolved": int(source is not None),
                    "link_reason": link_reason,
                    "source_path": str(path),
                    "protein_accessions": json.dumps(record["protein_accessions"]),
                }
                connection.execute(self.insert_psm_sql, row)

    @staticmethod
    def register_layers(
        *,
        connection: sqlite3.Connection,
        source_ids: set[str],
        layer: str,
    ) -> None:
        """Expose the layer for each acquisition even when it has no resolved PSMs."""
        for source in source_ids:
            connection.execute(
                "INSERT OR IGNORE INTO layers VALUES (?,?)",
                (source, layer),
            )

    @classmethod
    def candidate_values(cls, record: IdentificationRecord) -> dict[str, str | int | float | None]:
        """Prepare candidate values separately from source resolution and storage."""
        peptide = oms.AASequence.fromString(record["sequence"])
        precursor_mz, origin = cls.precursor_values(
            record=record,
            peptide=peptide,
        )
        return {
            "native": record["native"],
            "sequence": record["sequence"],
            "peptide": peptide.toUnmodifiedString(),
            "charge": record["charge"],
            "score": record["score"],
            "score_type": record["score_type"],
            "higher_better": record["higher_better"],
            "rank": record["rank"],
            "precursor_mz": precursor_mz,
            "precursor_mz_origin": origin,
        }

    @staticmethod
    def precursor_values(
        *,
        record: IdentificationRecord,
        peptide: oms.AASequence,
    ) -> tuple[float | None, str | None]:
        """Use a valid reported m/z or calculate it from sequence and charge.

        An identification without either a valid m/z or positive charge retains
        no precursor target. The origin records which calculation was used.
        """
        reported_mz = record["precursor_mz"]
        if reported_mz is not None and math.isfinite(reported_mz) and reported_mz > 0:
            return reported_mz, "idXML"
        if record["charge"] <= 0:
            return None, None

        calculated_mz = peptide.getMZ(record["charge"])
        origin = "calculated" if calculated_mz else None
        return calculated_mz, origin
