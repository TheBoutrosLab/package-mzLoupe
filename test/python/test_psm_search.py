"""PSM filters/order operate across the dataset before pagination."""

from collections.abc import Iterator
import json
from pathlib import Path
from typing import Any
import time

from fastapi.testclient import TestClient
import pytest

from mzloupe.app import create_app
from mzloupe.demo import DemoProject
from mzloupe.readers.mzml import MzMLReader
from mzloupe.storage.catalog import ProjectCatalog
from .psm_fixtures import seed_psm_rows

SearchSession = tuple[TestClient, str, ProjectCatalog]


@pytest.fixture
def table_session(tmp_path: Path) -> Iterator[SearchSession]:
    """Extend native demo evidence beyond one page, without touching raw spectra."""
    manifest = DemoProject().write(tmp_path / "data")
    app = create_app(tmp_path / "cache", manifest)
    with TestClient(app) as client:
        for _ in range(100):
            state = client.get("/api/status").json()
            if state["state"] != "preparing":
                break
            time.sleep(0.02)
        assert state["state"] == "ready", state
        catalog = app.state.runtime.active[1]
        seed_psm_rows(catalog)
        yield client, "/api/projects/" + state["token"], catalog


def query(
    client: TestClient, base: str, filters: dict[str, Any] | None = None, **options: str | int
) -> dict[str, Any]:
    """Request a scoped result page using the public API filter contract."""
    response = client.get(
        base + "/psms",
        params={
            "sample": "Synthetic sample",
            "filters": json.dumps(filters or {}),
            **options,
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_combined_filters_and_numeric_sort(table_session: SearchSession) -> None:
    """Combine column AND predicates and sort real numbers before limiting rows."""
    client, base, _ = table_session
    result = query(
        client,
        base,
        {
            "fractions": ["fraction_02"],
            "layers": ["Search"],
            "sequence": {"value": "peptide", "mode": "exact"},
            "score_min": 0.1,
            "score_max": 0.13,
        },
        sort_by="score",
        sort_direction="desc",
        page_size=10,
    )
    assert [row["score"] for row in result["rows"]] == [0.126, 0.12, 0.114, 0.108, 0.102]
    assert result["total"] == 5
    assert result["peptides"] == 1
    assert {row["fraction"] for row in result["rows"]} == {"F02"}
    zero = query(client, base, {"layers": ["Search"], "score_min": 0, "score_max": 0})
    assert zero["total"] == 1 and zero["rows"][0]["score"] == 0


def test_pagination_and_scope_wide_facets(table_session: SearchSession) -> None:
    """Pages do not overlap and filter choices include values absent from a page."""
    client, base, _ = table_session
    filters = {"layers": ["Search"]}
    first = query(client, base, filters, sort_by="score", page_size=25)
    second = query(client, base, filters, sort_by="score", page_size=25, page=1)
    assert first["total"] > 100
    assert len(first["rows"]) == len(second["rows"]) == 25
    assert not {row["id"] for row in first["rows"]} & {row["id"] for row in second["rows"]}
    assert max(row["score"] for row in first["rows"]) <= min(row["score"] for row in second["rows"])
    assert first["facets"]["layers"] == ["Search", "Validated"]
    assert {item["label"] for item in first["facets"]["fractions"]} == {"F01", "F02", "Unresolved"}
    assert set(first["facets"]["score_types"]) == {"PEP", "hyperscore"}
    clamped = query(client, base, {"link": "unresolved"}, page=100)
    assert clamped["page"] == 0 and clamped["total"] == 1


def test_protein_member_search_sees_candidates_beyond_first_page(
    table_session, monkeypatch
) -> None:
    """Search a hidden accession globally and reuse its index across filter edits."""
    client, base, _ = table_session

    def reject_raw(*_args, **_kwargs):
        """Table operations must not decode any raw peak arrays."""
        pytest.fail("PSM query accessed mzML")

    monkeypatch.setattr(MzMLReader, "spectrum", reject_raw)
    result = query(client, base, {"proteins": {"value": "zz_hidden_127", "mode": "exact"}})
    assert result["total"] == 1
    assert result["rows"][0]["score"] == 0.127
    compact = query(client, base, {"proteins": {"value": "P0CE47", "mode": "exact"}})
    assert compact["total"] == 130
    sorted_rows = query(client, base, sort_by="proteins", sort_direction="desc")
    assert all(row["protein_accessions"] for row in sorted_rows["rows"])
    service = client.app.state.runtime.search
    index = service.protein_indexes[""]
    query(client, base, {"proteins": {"value": "hidden_12"}})
    assert service.protein_indexes[""] is index


def test_rt_minutes_scan_matching_and_unresolved_filters(table_session: SearchSession) -> None:
    """Convert minute bounds once and retain NULL RT semantics for unresolved rows."""
    client, base, _ = table_session
    result = query(client, base, {"rt_min": 3.9, "rt_max": 4.2, "link": "resolved"}, sort_by="rt")
    assert result["rows"]
    assert all(234 <= row["rt"] <= 252 for row in result["rows"])
    unresolved = query(client, base, {"fractions": ["__unresolved__"], "link": "unresolved"})
    assert unresolved["total"] == 1 and unresolved["rows"][0]["rt"] is None
    literal = query(client, base, {"native": {"value": "_%\\id"}})
    assert literal["total"] == 1
    assert query(client, base, {"sequence": {"value": "PEP%"}})["total"] == 0
    assert query(client, base, {"score_type": "hyperscore"})["total"] == 26


@pytest.mark.parametrize(
    "options",
    [
        {"sort_by": "p.score; DROP TABLE psms"},
        {"sort_direction": "sideways"},
        {"filters": '{"rt_min":10,"rt_max":1}'},
        {"filters": '{"score_min":NaN}'},
        {"filters": '{"unknown_column":"test"}'},
        {"filters": '{"sequence":{"value":"PEP","mode":"regex"}}'},
    ],
)
def test_invalid_query_is_rejected_without_catalog_changes(
    table_session: SearchSession, options: dict[str, str]
) -> None:
    """Reject invalid bounds, unsafe sort fields, and unsupported filter operators."""
    client, base, catalog = table_session
    before = catalog.rows("SELECT count(*) AS n FROM psms")[0]["n"]
    response = client.get(base + "/psms", params={"sample": "Synthetic sample", **options})
    assert response.status_code == 400
    assert catalog.rows("SELECT count(*) AS n FROM psms")[0]["n"] == before


def test_precursor_mz_sorting_and_range_filter(table_session: SearchSession) -> None:
    """Sort full-precision peptide m/z numerically before paging, with NULLs last."""
    client, base, catalog = table_session
    target = catalog.rows("SELECT id FROM psms WHERE protein_accessions LIKE '%zz_hidden_127%'")[0][
        "id"
    ]
    missing = catalog.rows("SELECT id FROM psms WHERE protein_accessions LIKE '%zz_hidden_126%'")[
        0
    ]["id"]
    with catalog.connect() as connection:
        connection.execute("UPDATE psms SET precursor_mz=? WHERE id=?", (1000.123456, target))
        connection.execute("UPDATE psms SET precursor_mz=NULL WHERE id=?", (missing,))
    result = query(client, base, sort_by="precursor_mz", sort_direction="desc", page_size=200)
    assert result["rows"][0]["id"] == target
    assert result["rows"][0]["precursor_mz"] == 1000.123456
    assert result["rows"][-1]["id"] == missing
    result = query(client, base, {"precursor_mz_min": 1000.123455, "precursor_mz_max": 1000.123457})
    assert result["total"] == 1 and result["rows"][0]["id"] == target
    exact = query(client, base, {"precursor_mz_min": 1000.123456, "precursor_mz_max": 1000.123456})
    assert exact["total"] == 1


@pytest.mark.parametrize(
    "filters",
    [
        {"precursor_mz_min": 600, "precursor_mz_max": 500},
        {"precursor_mz_min": -1},
        {"precursor_mz_max": float("inf")},
    ],
)
def test_invalid_precursor_bounds_are_rejected(table_session: SearchSession, filters: dict) -> None:
    """Reject nonfinite, negative, or reversed precursor m/z bounds."""
    client, base, _ = table_session
    response = client.get(
        base + "/psms", params={"sample": "Synthetic sample", "filters": json.dumps(filters)}
    )
    assert response.status_code == 400
