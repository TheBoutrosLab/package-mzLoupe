"""Join selected inference groups to PSMs without modifying identification evidence."""

from collections import defaultdict
from typing import Any

import pyopenms as oms

from mzloupe.models import ProjectInput, ProteinGroupingInput
from mzloupe.readers.protein_grouping import ProteinGroupingFile
from mzloupe.services.identifications import SpectrumResolver
from mzloupe.storage.catalog import ProjectCatalog


class ProteinGrouping:
    """Index one chosen collection with source-aware, inference-reported assignments."""

    def __init__(
        self,
        configuration: ProteinGroupingInput,
        source: ProteinGroupingFile,
        project: ProjectInput,
        catalog: ProjectCatalog,
    ) -> None:
        """Build accession and peptide indexes once for the active session."""
        self.configuration = configuration
        self.groups = {group.id: group for group in source.groups[configuration.collection]}
        if not self.groups:
            raise ValueError(f"{configuration.name}: the selected group collection is empty")
        self.by_accession: dict[tuple[str, str], set[str]] = defaultdict(set)
        self.by_any_accession: dict[str, set[str]] = defaultdict(set)
        self.by_peptide: dict[tuple[str, str, str], set[str]] = defaultdict(set)
        self.evidence: dict[tuple[str, str, str], set[str]] = defaultdict(set)
        self.unresolved: set[tuple[str, str]] = set()
        self.assignment_mode = "accession_overlap"
        self.index_groups()
        self.index_peptides(source, project, catalog)

    def index_groups(self) -> None:
        """Build direct accession lookups, keeping inference runs independent."""
        for group in self.groups.values():
            run = group.id.split(":", 1)[0]
            for member in group.members:
                self.by_accession[run, member].add(group.id)
                self.by_any_accession[member].add(group.id)

    def index_peptides(
        self,
        source: ProteinGroupingFile,
        project: ProjectInput,
        catalog: ProjectCatalog,
    ) -> None:
        """Resolve spectrum-level evidence without conflating fractions or samples."""
        acquisitions = [
            item
            for item in project.acquisitions
            if not self.configuration.samples or item.sample in self.configuration.samples
        ]
        with catalog.connect() as connection:
            resolver = SpectrumResolver(acquisitions, connection)
            for identifier, record in source.peptides:
                run = source.run_ids[identifier]
                peptide = oms.AASequence.fromString(record["sequence"]).toUnmodifiedString()
                matches = self.match_accessions(run, record["protein_accessions"])
                if record["native"]:
                    self.assignment_mode = "spectrum"
                    acquisition, _ = resolver.resolve(record)
                    if acquisition is None:
                        self.unresolved.add((record["native"], peptide))
                        continue
                    key = (acquisition, record["native"], peptide)
                else:
                    key = ("", "", peptide)
                    if self.assignment_mode != "spectrum":
                        self.assignment_mode = "peptide"
                self.by_peptide[key].update(matches)
                self.evidence[key].update(record["protein_accessions"])

    def match_accessions(self, run: str, accessions: list[str]) -> set[str]:
        """Find all matching groups within a single inference run."""
        matches: set[str] = set()
        for accession in accessions:
            matches.update(self.by_accession.get((run, accession), set()))
        return matches

    def applies(self, row: dict[str, Any]) -> bool:
        """Restrict an inference source to its declared sample and layer scope."""
        return (not self.configuration.samples or row["sample"] in self.configuration.samples) and (
            not self.configuration.layers or row["layer"] in self.configuration.layers
        )

    def assignment(self, row: dict[str, Any]) -> dict[str, Any]:
        """Return every possible group, never resolving a shared peptide arbitrarily.

        When the inference file includes peptide evidence, that evidence is
        authoritative. Missing entries do not fall back to original search links.
        Group-only files use accession overlap and label that association explicitly.
        """
        unresolved = False
        if self.assignment_mode == "spectrum":
            key = (row["source"], row["native"], row["peptide"])
            matches = self.by_peptide.get(key, set())
            unresolved = (row["native"], row["peptide"]) in self.unresolved
        elif self.assignment_mode == "peptide":
            key = ("", "", row["peptide"])
            matches = self.by_peptide.get(key, set())
        else:
            key = ("", "", "")
            matches: set[str] = set()
            for accession in row["protein_accessions"]:
                matches.update(self.by_any_accession.get(accession, set()))
        status = (
            "ambiguous"
            if unresolved or len(matches) > 1
            else ("assigned" if matches else "unassigned")
        )
        return {
            "name": self.configuration.name,
            "collection": self.configuration.collection,
            "basis": self.assignment_mode,
            "status": status,
            "inferred_accessions": sorted(self.evidence.get(key, set())),
            "groups": [self.groups[key].payload() for key in sorted(matches)],
        }


class ProteinGroupings:
    """Own independent grouping views for one prepared project's session metadata."""

    def __init__(self, project: ProjectInput, catalog: ProjectCatalog) -> None:
        """Read each distinct inference file once, even when both collections are used."""
        files: dict[str, ProteinGroupingFile] = {}
        self.views: list[ProteinGrouping] = []
        for configuration in project.protein_groupings:
            if configuration.path not in files:
                files[configuration.path] = ProteinGroupingFile(configuration.path)
            self.views.append(
                ProteinGrouping(
                    configuration=configuration,
                    source=files[configuration.path],
                    project=project,
                    catalog=catalog,
                )
            )

    def enrich(self, rows: list[dict[str, Any]]) -> None:
        """Add grouping annotations while leaving original peptide accessions intact."""
        for row in rows:
            row["protein_groupings"] = [
                view.assignment(row) for view in self.views if view.applies(row)
            ]

    def summaries(self) -> list[dict[str, Any]]:
        """Describe available grouping views for the dashboard selector."""
        return [
            {**view.configuration.model_dump(), "group_count": len(view.groups)}
            for view in self.views
        ]
