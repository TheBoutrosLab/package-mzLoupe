"""Session-local protein search indexes, independent of raw mzML readers."""

from dataclasses import dataclass
import json
import re

from mzloupe.psm_models import TextFilter
from mzloupe.storage.catalog import ProjectCatalog


@dataclass(frozen=True)
class ProteinSearchScope:
    """Limit an index to the sample/acquisition scope of the table."""

    sample: str
    source: str | None = None
    layers: tuple[str, ...] = ()


@dataclass(frozen=True)
class ProteinSearchValue:
    """Retain a display sort key and all searchable accessions for one candidate."""

    label: str | None
    accessions: tuple[str, ...]


class PsmProteinIndex:
    """Build one compact index per grouping view, then reuse it across requests.

    Only PSM metadata is read. Full group memberships are searchable, including
    members hidden by the compact representative cell. Original mappings remain
    the fallback where a grouping does not apply to a sample/layer.
    """

    def __init__(
        self,
        catalog: ProjectCatalog,
        grouping: str,
        scope: ProteinSearchScope,
    ) -> None:
        """Index only eligible metadata, in batches, without reading unrelated samples."""
        self.scope = scope
        self.values: dict[int, ProteinSearchValue] = {}
        sql = "SELECT id,sample,source,layer,native,peptide,protein_accessions FROM psms"
        parameters = []
        sql += " WHERE sample=?"
        parameters.append(scope.sample)
        if scope.source:
            sql += " AND source=?"
            parameters.append(scope.source)
        if scope.layers:
            sql += " AND layer IN (" + ",".join("?" for _ in scope.layers) + ")"
            parameters.extend(scope.layers)
        sql += " ORDER BY id"
        with catalog.connect() as connection:
            cursor = connection.execute(sql, parameters)
            while batch := cursor.fetchmany(1000):
                rows = [dict(row) for row in batch]
                for row in rows:
                    row["protein_accessions"] = json.loads(row["protein_accessions"])
                if grouping and catalog.groupings:
                    catalog.groupings.enrich(rows)
                for row in rows:
                    self.values[row["id"]] = self.value(row, grouping)

    @staticmethod
    def compact(accession: str) -> str:
        """Recognize a UniProt display ID without stripping decoy/contaminant prefixes."""
        match = re.fullmatch(r"(?:sp|tr)\|([^|]+)\|[^|]+", accession)
        return match[1] if match else accession

    @classmethod
    def group_label(cls, group: dict) -> str:
        """Match the UI's representative/count label for one possible protein group."""
        representative = cls.compact(group["members"][0])
        additional = len(group["members"]) - 1
        return f"{representative} (+{additional})" if additional else representative

    @classmethod
    def value(cls, row: dict, grouping: str) -> ProteinSearchValue:
        """Use the same representative and ambiguity labels as the rendered table."""
        annotation = next(
            (item for item in row.get("protein_groupings", []) if item["name"] == grouping), None
        )
        members = sorted(set(row["protein_accessions"]))
        label = cls.compact(members[0]) if members else None
        if annotation is not None:
            members = list(
                dict.fromkeys(
                    member for group in annotation["groups"] for member in group["members"]
                )
            )
            if annotation["status"] == "assigned":
                label = cls.compact(members[0]) if members else None
            elif annotation["status"] == "ambiguous":
                label = "; ".join(cls.group_label(group) for group in annotation["groups"])
                if not label:
                    label = "Unresolved group"
            else:
                label = "Not assigned"
        # Include compact UniProt IDs for exact searches of displayed accessions.
        accessions = {
            value.casefold() for member in members for value in (member, cls.compact(member))
        }
        return ProteinSearchValue(label.casefold() if label else None, tuple(accessions))

    def matching_ids(self, condition: TextFilter, direction: str | None = None) -> list[int]:
        """Match all protein members and optionally order by the displayed representative.

        Python's stable sort preserves ascending PSM IDs for equal labels. Missing
        proteins remain last in both directions, independently of pagination.
        """
        term = condition.value.casefold()
        ids = [
            identifier
            for identifier, value in self.values.items()
            if not term
            or any(
                accession == term if condition.mode == "exact" else term in accession
                for accession in value.accessions
            )
        ]
        if direction:
            populated = [
                identifier for identifier in ids if self.values[identifier].label is not None
            ]
            missing = [identifier for identifier in ids if self.values[identifier].label is None]
            ids = (
                sorted(
                    populated,
                    key=lambda identifier: self.values[identifier].label or "",
                    reverse=direction == "desc",
                )
                + missing
            )
        return ids
