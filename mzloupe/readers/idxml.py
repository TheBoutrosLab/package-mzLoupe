"""Load native OpenMS identifications and adapt them for catalog import."""

from __future__ import annotations

from abc import abstractmethod
from collections.abc import Iterator
from pathlib import Path
from typing import Protocol, TypedDict, cast

import pyopenms as oms


class IdentificationRecord(TypedDict):
    """Describe one candidate and the provenance needed to resolve its source.

    The source-path list belongs to the identification run and preserves its
    original ordering. The importer stores the candidate's selected values in
    SQLite after resolving these hints against the registered acquisitions.
    """

    native: str
    precursor_mz: float | None
    sequence: str
    charge: int
    score: float
    score_type: str
    higher_better: bool
    rank: int
    base_name: str
    file_origin: str
    id_merge_index: str
    spectra_data: list[str]
    protein_accessions: list[str]


class IdXMLLoader(Protocol):
    """Describe the public loader omitted from pyOpenMS 3.6's generated stubs.

    OpenMS adds this method at runtime. Keep its argument contract explicit so
    type checkers can validate calls without treating the loader as untyped.
    """

    @abstractmethod
    def load(
        self,
        filename: str,
        protein_ids: list[oms.ProteinIdentification],
        peptide_ids: oms.PeptideIdentificationList,
    ) -> None:
        """Fill the native identification collections from the supplied file."""
        ...


class IdXMLWriter(Protocol):
    """Describe the native writer omitted from pyOpenMS's generated stubs."""

    @abstractmethod
    def store(
        self,
        filename: str,
        protein_ids: list[oms.ProteinIdentification],
        peptide_ids: oms.PeptideIdentificationList,
    ) -> None:
        """Write native protein and peptide identification collections as idXML."""
        ...


class IdXMLReader:
    """Read a complete idXML through OpenMS and expose its candidate records.

    OpenMS owns XML parsing, modification handling, and run associations. This
    adapter selects the fields consumed by the resolver and SQLite importer.
    """

    def __init__(self, path: str | Path) -> None:
        """Remember the input path; defer loading until records are requested."""
        self.path = Path(path)

    def records(self) -> Iterator[IdentificationRecord]:
        """Load one file and yield its candidates with run-specific source paths.

        The native protein and peptide collections remain in memory while this
        iterator is consumed and are released when iteration finishes.
        """
        protein_ids: list[oms.ProteinIdentification] = []
        peptide_ids = oms.PeptideIdentificationList()
        loader = cast(IdXMLLoader, oms.IdXMLFile())
        loader.load(
            str(self.path),
            protein_ids,
            peptide_ids,
        )

        # A merged file can contain several runs with different source ordering.
        # OpenMS links each peptide to its protein identification by identifier.
        paths_by_run = {
            protein.getIdentifier(): protein.getPrimaryMSRunPath() for protein in protein_ids
        }

        for peptide in peptide_ids:
            source_paths = paths_by_run.get(peptide.getIdentifier(), [])
            yield from self.identification_records(
                peptide=peptide,
                source_paths=source_paths,
            )

    def identification_records(
        self,
        peptide: oms.PeptideIdentification,
        source_paths: list[str],
    ) -> Iterator[IdentificationRecord]:
        """Yield one row per hit while retaining native scientific values.

        Preserve the modified sequence and reported score semantics. An unset
        precursor m/z becomes None; an unset hit rank falls back to hit order.
        """
        precursor_mz = peptide.getMZ() if peptide.hasMZ() else None

        for position, hit in enumerate(peptide.getHits(), start=1):
            yield {
                "native": peptide.getSpectrumReference(),
                "precursor_mz": precursor_mz,
                "sequence": hit.getSequence().toString(),
                "charge": hit.getCharge(),
                "score": hit.getScore(),
                "score_type": peptide.getScoreType() or "score",
                "higher_better": peptide.isHigherScoreBetter(),
                "rank": hit.getRank() or position,
                "base_name": self.metadata_text(
                    peptide=peptide,
                    hit=hit,
                    key="base_name",
                ),
                "file_origin": self.metadata_text(
                    peptide=peptide,
                    hit=hit,
                    key="file_origin",
                ),
                "id_merge_index": self.metadata_text(
                    peptide=peptide,
                    hit=hit,
                    key="id_merge_index",
                ),
                "spectra_data": list(source_paths),
                # Several peptide evidences may refer to different positions in
                # the same protein. Keep each accession once, without rewriting it.
                "protein_accessions": sorted(
                    {
                        evidence.getProteinAccession()
                        for evidence in hit.getPeptideEvidences()
                        if evidence.getProteinAccession()
                    }
                ),
            }

    @staticmethod
    def metadata_text(peptide: oms.PeptideIdentification, hit: oms.PeptideHit, key: str) -> str:
        """Read a source hint with identification metadata taking precedence.

        An explicitly empty identification value still overrides the hit value.
        Convert native strings, byte strings, and merge-index numbers to the
        text representation expected by the resolver. Missing hints are empty.
        """
        for record in (peptide, hit):
            if record.metaValueExists(key):
                value = record.getMetaValue(key)
                if isinstance(value, bytes):
                    return value.decode("utf-8")
                return str(value)
        return ""
