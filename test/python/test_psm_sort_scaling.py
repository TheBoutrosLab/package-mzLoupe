"""Guard against quadratic protein sorting and unrelated-sample indexing."""

from collections.abc import Iterator
from contextlib import contextmanager
import json
from pathlib import Path
import sqlite3

from mzloupe.psm_models import PsmFilters, PsmQuery
from mzloupe.services.psm_search import PsmSearch
from mzloupe.storage.catalog import ProjectCatalog


class QueryBudgetCatalog(ProjectCatalog):
    """Interrupt excessive SQLite work using VM instructions, not wall-clock timing."""

    def __init__(self, path: Path) -> None:
        """Leave setup unrestricted and enable the budget only around table queries."""
        super().__init__(path)
        self.steps = 0
        self.limit: int | None = None

    def progress(self) -> int:
        """Count deterministic query work and stop an accidental nested full scan."""
        self.steps += 1000
        return int(self.limit is not None and self.steps > self.limit)

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        """Apply the same budget to index selection, counts, rows, and facets."""
        with super().connect() as connection:
            connection.set_progress_handler(self.progress, 1000)
            yield connection


def large_catalog(path: Path, count: int = 45000) -> QueryBudgetCatalog:
    """Populate metadata comparable to the reported fraction, without creating mzML."""
    catalog = QueryBudgetCatalog(path)
    catalog.create()
    alphabet = "ACDEFGHIKLMNPQRSTVWY"
    with catalog.connect() as connection:
        connection.executemany(
            "INSERT INTO acquisitions (id,sample,fraction,path,mode) VALUES (?,?,?,?, 'Unknown')",
            [("run", "Sample", "F01", "unused.mzML"), ("other", "Other", "F01", "unused.mzML")],
        )
        connection.executemany(
            "INSERT INTO scans (source,ordinal,native,rt,level,mz,charge) VALUES (?,?,?,?,?,?,?)",
            (("run", index, f"scan={index}", float(index), 2, 500, 2) for index in range(count)),
        )
        candidates = []
        for index in range(count):
            sequence = "PEP" + "".join(
                alphabet[index // 20**position % 20] for position in range(4)
            )
            candidates.append(
                (
                    "Sample",
                    "run",
                    "Validated",
                    f"scan={index}",
                    sequence,
                    sequence,
                    index / count,
                    "q-value",
                    json.dumps([f"sp|P{count-index:05d}|TEST"]),
                )
            )
        candidates.append(
            (
                "Other",
                "other",
                "Validated",
                "scan=other",
                "PEPTIDE",
                "PEPTIDE",
                0.1,
                "q-value",
                '["other_protein"]',
            )
        )
        connection.executemany(
            "INSERT INTO psms(sample,source,layer,native,sequence,peptide,score,score_type,"
            "protein_accessions) VALUES (?,?,?,?,?,?,?,?,?)",
            candidates,
        )
    return catalog


def test_protein_sort_work_scales_with_candidates(tmp_path: Path) -> None:
    """Order 45,000 candidates under a budget that rejects the former quadratic join."""
    catalog = large_catalog(tmp_path / "catalog.sqlite")
    catalog.steps = 0
    catalog.limit = 12000000
    service = PsmSearch(catalog)
    result = service.page(PsmQuery(sample="Sample", source="run", sort_by="proteins"))
    assert result["total"] == 45000
    assert result["peptides"] == 45000
    assert [row["id"] for row in result["rows"]] == list(range(45000, 44950, -1))
    assert catalog.steps < catalog.limit
    index = service.protein_indexes[""]
    assert len(index.values) == 45000
    assert index.scope.sample == "Sample"
    assert index.scope.source == "run"
    catalog.steps = 0
    descending = service.page(
        PsmQuery(
            sample="Sample",
            source="run",
            sort_by="proteins",
            sort_direction="desc",
            page=1,
        )
    )
    assert [row["id"] for row in descending["rows"]] == list(range(51, 101))
    assert service.protein_indexes[""] is index
    assert catalog.steps < catalog.limit


def test_protein_index_replaces_its_scope_when_sample_changes(tmp_path: Path) -> None:
    """A view keeps one active scope and never leaks another sample's candidates."""
    catalog = large_catalog(tmp_path / "catalog.sqlite", count=50)
    service = PsmSearch(catalog)
    service.page(PsmQuery(sample="Sample", source="run", sort_by="proteins"))
    first = service.protein_indexes[""]
    result = service.page(PsmQuery(sample="Other", source="other", sort_by="proteins"))
    assert result["total"] == 1
    assert result["rows"][0]["protein_accessions"] == ["other_protein"]
    assert service.protein_indexes[""] is not first
    assert len(service.protein_indexes[""].values) == 1


def test_protein_index_excludes_unselected_layers(tmp_path: Path) -> None:
    """A validated-layer sort must not index unrelated search-layer candidates."""
    catalog = large_catalog(tmp_path / "catalog.sqlite", count=10)
    with catalog.connect() as connection:
        connection.execute(
            "INSERT INTO psms(sample,source,layer,native,sequence,peptide,score,score_type,"
            "protein_accessions) VALUES (?,?,?,?,?,?,?,?,?)",
            (
                "Sample",
                "run",
                "Search",
                "scan=0",
                "PEPTIDE",
                "PEPTIDE",
                0.1,
                "q-value",
                '["search_only"]',
            ),
        )
    service = PsmSearch(catalog)
    query = PsmQuery(
        sample="Sample", source="run", sort_by="proteins", filters=PsmFilters(layers=["Validated"])
    )
    assert service.page(query)["total"] == 10
    first = service.protein_indexes[""]
    assert len(first.values) == 10
    query.filters.layers = ["Search"]
    assert service.page(query)["total"] == 1
    assert service.protein_indexes[""] is not first
    assert len(service.protein_indexes[""].values) == 1
