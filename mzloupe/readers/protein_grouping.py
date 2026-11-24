"""Read inference groups and peptide associations through native OpenMS idXML."""

from dataclasses import dataclass
from pathlib import Path
from typing import cast

import pyopenms as oms

from mzloupe.readers.idxml import IdentificationRecord, IdXMLLoader, IdXMLReader


@dataclass(frozen=True)
class ProteinGroup:
    """One source-ordered group, including its run identity and stored score."""

    id: str
    members: tuple[str, ...]
    probability: float | None
    stored_probability: float

    def payload(self) -> dict:
        """Expose original accession order and distinguish absent probability semantics."""
        return {
            "id": self.id,
            "members": list(self.members),
            "probability": self.probability,
            "stored_probability": self.stored_probability,
        }


class ProteinGroupingFile:
    """Retain both native group collections and adapted peptide evidence in memory.

    Native objects are released after adaptation. This small inference index is
    session metadata; raw spectra and the prepared project catalog are untouched.
    """

    collections = ("protein_groups", "indistinguishable_proteins")

    def __init__(self, path: str | Path) -> None:
        """Load an idXML once and preserve run boundaries and accession ordering."""
        self.groups: dict[str, list[ProteinGroup]] = {key: [] for key in self.collections}
        self.peptides: list[tuple[str, IdentificationRecord]] = []
        proteins: list[oms.ProteinIdentification] = []
        peptides = oms.PeptideIdentificationList()
        cast(IdXMLLoader, oms.IdXMLFile()).load(str(path), proteins, peptides)
        self.run_ids = {run.getIdentifier(): str(index) for index, run in enumerate(proteins)}
        self.read_groups(proteins, path)
        self.read_peptides(proteins, peptides, path)

    def read_groups(self, runs: list[oms.ProteinIdentification], path: str | Path) -> None:
        """Preserve both group collections, source order, and score semantics."""
        for run in runs:
            prophet = "proteinprophet" in (run.getSearchEngine() + run.getScoreType()).lower()
            native_groups = {
                "protein_groups": run.getProteinGroups(),
                "indistinguishable_proteins": run.getIndistinguishableProteins(),
            }
            for collection, groups in native_groups.items():
                for ordinal, group in enumerate(groups):
                    members = tuple(dict.fromkeys(member for member in group.accessions if member))
                    if not members:
                        raise ValueError(f"Empty protein group in {path}")
                    probability = float(group.probability)
                    # ProteinProphet conversion leaves unset subgroup probabilities
                    # at zero; retain any meaningful nonzero probability from the file.
                    unset = (
                        prophet and collection == "indistinguishable_proteins" and probability == 0
                    )
                    self.groups[collection].append(
                        ProteinGroup(
                            id=f"{self.run_ids[run.getIdentifier()]}:{ordinal}",
                            members=members,
                            probability=None if unset else probability,
                            stored_probability=probability,
                        )
                    )

    def read_peptides(
        self,
        proteins: list[oms.ProteinIdentification],
        peptides: oms.PeptideIdentificationList,
        path: str | Path,
    ) -> None:
        """Adapt inference peptide evidence while preserving its identification run."""
        runs = {run.getIdentifier(): run for run in proteins}
        reader = IdXMLReader(path)
        for peptide in peptides:
            identifier = peptide.getIdentifier()
            if identifier not in runs:
                raise ValueError(f"Peptide references an unknown inference run in {path}")
            paths = list(runs[identifier].getPrimaryMSRunPath())
            for record in reader.identification_records(peptide, paths):
                self.peptides.append((identifier, record))

    def summary(self) -> dict[str, int]:
        """Count populated collections for the loader's explicit selection control."""
        return {key: len(groups) for key, groups in self.groups.items()}
