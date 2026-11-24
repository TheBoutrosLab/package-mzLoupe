"""End-to-end checks for local project inspection and source isolation."""

from collections.abc import Iterator
import json
from pathlib import Path
import time

from fastapi.testclient import TestClient
import numpy as np
import pytest

from mzloupe.app import create_app
from mzloupe.demo import DemoProject
from mzloupe.readers.mzml import MzMLReader

InspectionSession = tuple[TestClient, str, Path]


@pytest.fixture
def session(tmp_path: Path) -> Iterator[InspectionSession]:
    """Prepare a synthetic project and yield its client, API prefix, and manifest."""
    manifest = DemoProject().write(tmp_path / "data")
    app = create_app(tmp_path / "cache", manifest)
    with TestClient(app) as client:
        for _ in range(100):
            status = client.get("/api/status").json()
            if status["state"] != "preparing":
                break
            time.sleep(0.05)
        assert status["state"] == "ready", status
        yield client, "/api/projects/" + status["token"], manifest


def test_fraction_identity_and_independent_xic(session: InspectionSession) -> None:
    """Keep repeated scan IDs fraction-specific and extract the expected precursor trace."""
    client, base, manifest = session
    project = client.get(base, params={"layer": "Validated"}).json()
    assert len(project["acquisitions"]) == 2
    assert all(row["ms2"] == 40 and row["identified"] == 5 for row in project["acquisitions"])
    first = client.get(base + "/sources/fraction_01/spectra/79").json()
    second = client.get(base + "/sources/fraction_02/spectra/79").json()
    assert first["native"] == second["native"] == "scan=80"
    assert first["source"] != second["source"]
    assert len(first["candidates"]) == 3
    result = client.post(
        base + "/xic",
        json={"source": "fraction_01", "mz": 400.6873, "ppm": 10, "start": 210, "stop": 255},
    ).json()
    expected = 100 + 100000 * np.exp(-0.5 * ((np.array(result["rt"]) - 242) / 18) ** 2)
    np.testing.assert_allclose(result["intensity"], expected, rtol=1e-6)
    annotations = client.get(base + f'/psms/{first["candidates"][0]["id"]}/annotations').json()
    assert len(annotations) > 4
    assert all(abs(item["ppm"]) < 20 for item in annotations)


def test_psm_selection_reuses_reader_spectrum_and_trace(
    session: InspectionSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Serve annotations and repeated selections without reopening or redecoding mzML."""
    client, base, _ = session
    original_init = MzMLReader.__init__
    opened = []

    def open_index(reader: MzMLReader, path: str | Path, *, load_metadata: bool = True) -> None:
        """Reject a full metadata pass during interactive requests."""
        assert load_metadata is False
        opened.append(str(path))
        original_init(reader, path, load_metadata=load_metadata)

    monkeypatch.setattr(MzMLReader, "__init__", open_index)
    spectrum_url = base + "/sources/fraction_01/spectra/79"
    spectrum = client.get(spectrum_url).json()
    candidate = next(row for row in spectrum["candidates"] if row["layer"] == "Validated")
    annotation_url = base + f'/psms/{candidate["id"]}/annotations'

    def reject_peak_read(_reader: MzMLReader, _ordinal: int) -> None:
        """An already displayed spectrum must not be decoded again for annotation."""
        pytest.fail("The cached result unexpectedly triggered another peak read")

    with monkeypatch.context() as annotation_patch:
        annotation_patch.setattr(MzMLReader, "spectrum", reject_peak_read)
        annotations = client.get(annotation_url).json()
    assert annotations
    request = {"source": "fraction_01", "mz": 400.6873, "ppm": 10, "start": 210, "stop": 280}
    trace = client.post(base + "/xic", json=request).json()
    assert trace["matched_scan_count"] > 0
    monkeypatch.setattr(MzMLReader, "spectrum", reject_peak_read)
    assert client.get(spectrum_url).json() == spectrum
    assert client.get(annotation_url).json() == annotations
    assert client.post(base + "/xic", json=request).json() == trace
    assert len(opened) == 1


def test_xic_psms_span_layers_but_stay_within_extraction(session: InspectionSession) -> None:
    """Include other peak assignments while respecting fraction, RT, and peptide m/z."""
    client, base, _ = session
    request = {
        "source": "fraction_01",
        "mz": 400.6873,
        "ppm": 10,
        "start": 210,
        "stop": 280,
    }
    result = client.post(base + "/xic", json=request).json()
    psms = result["psms"]
    assert len(psms) == 15
    assert {psm["source"] for psm in psms} == {"fraction_01"}
    assert {psm["fraction"] for psm in psms} == {"F01"}
    assert {psm["layer"] for psm in psms} == {"Search", "Validated"}
    assert {psm["sequence"] for psm in psms} == {"PEPTIDE", "PEPTIED"}
    assert len({psm["ordinal"] for psm in psms}) == 5
    assert all(210 <= psm["rt"] <= 280 and psm["resolved"] for psm in psms)
    # An MS2 assignment can exist between MS1 scans, even with no extracted signal.
    narrow = client.post(
        base + "/xic",
        json={**request, "start": 236, "stop": 238},
    ).json()
    assert narrow["scan_count"] == 0
    assert len(narrow["psms"]) == 3
    assert {psm["ordinal"] for psm in narrow["psms"]} == {79}
    different_mz = client.post(base + "/xic", json={**request, "mz": 450}).json()
    assert different_mz["matched_scan_count"] > 0
    assert different_mz["psms"] == []
    empty = client.post(
        base + "/xic",
        json={**request, "start": 900, "stop": 910},
    ).json()
    assert empty["psms"] == []


def test_xic_psms_are_not_limited_to_the_table_page(session: InspectionSession) -> None:
    """Retain all matching candidates when their count exceeds the table's 50-row page."""
    client, base, _ = session
    runtime = client.app.state.runtime
    _, catalog, _ = runtime.snapshot(base.rsplit("/", 1)[-1])
    prototype = catalog.rows("SELECT * FROM psms WHERE source='fraction_01' LIMIT 1")[0]
    prototype.pop("id")
    # Model a dense set of candidate assignments using an existing resolved scan.
    columns = ", ".join(prototype)
    placeholders = ", ".join(":" + column for column in prototype)
    candidates = [{**prototype, "rank": rank} for rank in range(2, 62)]
    with catalog.connect() as connection:
        connection.executemany(
            f"INSERT INTO psms ({columns}) VALUES ({placeholders})",
            candidates,
        )
    table = client.get(
        base + "/psms",
        params={"sample": "Synthetic sample", "source": "fraction_01"},
    ).json()
    result = client.post(
        base + "/xic",
        json={"source": "fraction_01", "mz": 400.6873, "ppm": 10, "start": 210, "stop": 280},
    ).json()
    assert table["total"] == 75
    assert len(table["rows"]) == 50
    assert len(result["psms"]) == 75
    assert len({psm["id"] for psm in result["psms"]}) == 75


def test_missing_reference_stays_searchable(tmp_path: Path) -> None:
    """Keep unmatched scan references searchable while rejecting spectrum annotation."""
    manifest = DemoProject().write(tmp_path / "data")
    path = manifest.parent / "sample_Search.idXML"
    path.write_text(path.read_text().replace("scan=80", "scan=9999", 1))
    with TestClient(create_app(tmp_path / "cache", manifest)) as client:
        for _ in range(100):
            status = client.get("/api/status").json()
            if status["state"] != "preparing":
                break
            time.sleep(0.05)
        base = "/api/projects/" + status["token"]
        result = client.get(
            base + "/psms",
            params={
                "sample": "Synthetic sample",
                "filters": json.dumps({"native": {"value": "scan=9999", "mode": "exact"}}),
            },
        ).json()
        assert result["total"] == 2
        assert all(row["resolved"] == 0 for row in result["rows"])
        assert client.get(base + f'/psms/{result["rows"][0]["id"]}/annotations').status_code == 400
        assert client.get("/api/projects/stale-token").status_code == 400


def test_bad_bounds_and_invalid_project(session: InspectionSession) -> None:
    """Reject reversed extraction intervals, unknown sources, and invalid project IDs."""
    client, base, manifest = session
    assert (
        client.post(
            base + "/xic",
            json={"source": "fraction_01", "mz": 400, "ppm": 10, "start": 250, "stop": 200},
        ).status_code
        == 422
    )
    assert client.get(base + "/sources/unknown/map").status_code == 400
    project = json.loads(manifest.read_text())
    project["acquisitions"][0]["id"] = "../escape"
    manifest.write_text(json.dumps(project))
    assert client.post("/api/open", json={"path": str(manifest)}).status_code == 400


def test_gzip_working_copy_and_reused_cache(tmp_path: Path) -> None:
    """Prepare compressed mzML through a working copy and reuse its completed cache."""
    import gzip

    manifest = DemoProject().write(tmp_path / "data")
    project = json.loads(manifest.read_text())
    source = manifest.parent / "fraction_01.mzML"
    compressed = source.with_suffix(".mzML.gz")
    compressed.write_bytes(gzip.compress(source.read_bytes()))
    project["acquisitions"][0]["mzml"] = compressed.name
    # Normalizing the .gz suffix preserves the spectra_data association.
    manifest.write_text(json.dumps(project))
    cache = tmp_path / "cache"
    tokens = []
    for _ in range(2):
        with TestClient(create_app(cache, manifest)) as client:
            for _ in range(100):
                status = client.get("/api/status").json()
                if status["state"] != "preparing":
                    break
                time.sleep(0.05)
            assert status["state"] == "ready", status
            tokens.append(status["token"])
            spectrum = client.get(
                "/api/projects/" + tokens[-1] + "/sources/fraction_01/spectra/79"
            ).json()
            assert spectrum["level"] == 2
            assert spectrum["rt"] == 237
            assert spectrum["native"] == "scan=80"
            assert len(spectrum["masses"]) > 5
    assert tokens[0] == tokens[1]
    assert list(cache.glob("project-*/*.mzML"))


def test_psm_fraction_scope(session: InspectionSession) -> None:
    """Filter PSMs by fraction without losing sample-level totals."""
    client, base, _ = session
    parameters = {"sample": "Synthetic sample", "filters": json.dumps({"layers": ["Validated"]})}
    all_rows = client.get(base + "/psms", params=parameters).json()
    parts = []
    for source in ("fraction_01", "fraction_02"):
        scoped = client.get(base + "/psms", params={**parameters, "source": source}).json()
        assert scoped["total"] > 0
        assert all(row["source"] == source for row in scoped["rows"])
        parts.append(scoped["total"])
    assert sum(parts) == all_rows["total"]
    assert all_rows["rows"][0]["fraction"] == "F01"


def test_heatmap_cell_resolves_measured_peak(session: InspectionSession) -> None:
    """Resolve map clicks to measured peaks and report empty selections clearly."""
    client, base, _ = session
    request = {"source": "fraction_01", "start": 230, "stop": 244, "mz_start": 400, "mz_stop": 401}
    response = client.post(base + "/map-target", json=request)
    assert response.status_code == 200, response.text
    target = response.json()
    assert target["source"] == "fraction_01"
    assert abs(target["mz"] - 400.6873) < 0.00001
    assert target["intensity"] > 0
    trace = client.post(
        base + "/xic",
        json={"source": target["source"], "mz": target["mz"], "ppm": 10, "start": 210, "stop": 255},
    ).json()
    assert trace["matched_scan_count"] > 0
    empty = client.post(base + "/map-target", json={**request, "mz_start": 800, "mz_stop": 801})
    assert empty.status_code == 400
    assert "No positive MS1 peak" in empty.json()["detail"]
    assert client.post(base + "/map-target", json={**request, "stop": 200}).status_code == 422


def test_assets_remain_paired_with_running_api(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Keep an active API paired with its original dashboard assets after updates."""
    import importlib

    module = importlib.import_module("mzloupe.app")
    package = tmp_path / "package"
    assets = package / "static"
    (assets / "assets").mkdir(parents=True)
    (assets / "index.html").write_text("original dashboard")
    (assets / "assets" / "client.js").write_text("original client")
    monkeypatch.setattr(module, "__file__", str(package / "app.py"))
    app = create_app(tmp_path / "cache")
    (assets / "index.html").write_text("updated dashboard")
    (assets / "assets" / "client.js").write_text("updated client")
    with TestClient(app) as client:
        assert client.get("/api/status").json()["state"] == "empty"
        assert client.get("/").text == "original dashboard"
        assert client.get("/assets/client.js").text == "original client"


def test_psm_api_exposes_only_column_filters(session: InspectionSession) -> None:
    """Keep retired global search and layer parameters out of the current API."""
    client, _, _ = session
    parameters = client.get("/openapi.json").json()["paths"]["/api/projects/{token}/psms"]["get"][
        "parameters"
    ]
    names = {parameter["name"] for parameter in parameters}
    assert "filters" in names
    assert "layer" not in names and "search" not in names


def test_cache_format_change_rebuilds_instead_of_migrating(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A new cache version creates a fresh catalog and leaves prior files intact."""
    from mzloupe.app import ProjectRuntime

    manifest = DemoProject().write(tmp_path / "data")
    cache = tmp_path / "cache"
    tokens = []
    for version in [ProjectRuntime.cache_version, ProjectRuntime.cache_version + 1]:
        monkeypatch.setattr(ProjectRuntime, "cache_version", version)
        with TestClient(create_app(cache, manifest)) as client:
            for _ in range(100):
                state = client.get("/api/status").json()
                if state["state"] != "preparing":
                    break
                time.sleep(0.02)
            assert state["state"] == "ready", state
            tokens.append(state["token"])
            rows = client.get(
                f"/api/projects/{state['token']}/psms",
                params={"sample": "Synthetic sample"},
            ).json()["rows"]
            assert rows and all(row["protein_accessions"] == [] for row in rows)
    assert tokens[0] != tokens[1]
    assert all((cache / token / "catalog.sqlite").is_file() for token in tokens)
