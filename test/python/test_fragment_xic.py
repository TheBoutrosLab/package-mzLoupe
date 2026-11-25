"""Verify DIA scan eligibility, theoretical targets, and bounded fragment extraction."""

from collections.abc import Iterator
from pathlib import Path

from fastapi.testclient import TestClient
import numpy as np
import pyopenms as oms
import pytest

from mzloupe.app import create_app
from mzloupe.models import FragmentXicRequest, ProjectInput
from mzloupe.readers.mzml import MzMLReader
from mzloupe.services.fragment_xic import FragmentXicExtractor
from mzloupe.services.preparation import ProjectPreparer
from mzloupe.services.signal import FragmentAnnotator
from test.python.dia_fixtures import write_dia_project
from test.python.psm_fixtures import wait_for_project

DiaSession = tuple[TestClient, str, dict]


@pytest.fixture
def dia_session(tmp_path: Path) -> Iterator[DiaSession]:
    """Prepare real indexed DIA mzML and matching idXML without starting a server."""
    manifest = write_dia_project(tmp_path / "data")
    with TestClient(create_app(tmp_path / "cache", manifest)) as client:
        wait_for_project(client)
        base = "/api/projects/" + client.get("/api/status").json()["token"]
        spectrum = client.get(base + "/sources/fraction_01/spectra/79").json()
        psm = next(row for row in spectrum["candidates"] if row["layer"] == "Validated")
        yield client, base, psm


def test_fragment_xic_uses_only_eligible_scans_once(
    dia_session: DiaSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Exclude stronger off-window interference and retain zero for acquired empty scans."""
    client, base, psm = dia_session
    annotations = client.get(base + f'/psms/{psm["id"]}/annotations').json()
    reads = []
    original = MzMLReader.spectrum

    def count_reads(reader: MzMLReader, ordinal: int) -> oms.MSSpectrum:
        """Count actual disk decodes after the selected spectrum has been cached."""
        reads.append(ordinal)
        return original(reader, ordinal)

    monkeypatch.setattr(MzMLReader, "spectrum", count_reads)
    request = {"psm_id": psm["id"], "start": 210, "stop": 280, "ppm": 20}
    response = client.post(base + "/fragment-xic", json=request)
    assert response.status_code == 200, response.text
    result = response.json()
    expected_ordinals = [71, 79, 87]
    assert reads == expected_ordinals
    assert result["rt"] == [ordinal * 3 for ordinal in expected_ordinals]
    assert result["scan_count"] == 3
    assert result["isolation_lower_mz"] == 390
    assert result["isolation_upper_mz"] == 410
    assert result["precursor_mz"] == psm["precursor_mz"] != 400
    assert len(result["fragments"]) == len(annotations) > 4
    for fragment, annotation in zip(result["fragments"], annotations):
        assert fragment["mz"] == annotation["mz"]
        assert fragment["label"] == annotation["label"]
        assert fragment["charge"] == 1
        expected = []
        for ordinal in expected_ordinals:
            masses, intensity = original(
                client.app.state.runtime.signal.reader(psm["source"]), ordinal
            ).get_peaks()
            tolerance = fragment["mz"] * 20 / 1e6
            mask = np.abs(masses - fragment["mz"]) <= tolerance
            expected.append(float(intensity[mask].sum()))
        np.testing.assert_allclose(fragment["intensity"], expected)
        assert fragment["intensity"][-1] == 0
        assert max(fragment["intensity"]) < 1e6
    assert client.post(base + "/fragment-xic", json=request).json() == result
    assert reads == expected_ordinals  # Exact repeats reuse the bounded batch result.


@pytest.mark.parametrize("mode", ["DDA", "Unknown"])
def test_fragment_xic_requires_explicit_dia(dia_session: DiaSession, mode: str) -> None:
    """Reject unsupported acquisition modes before reading signal."""
    client, base, psm = dia_session
    with client.app.state.runtime.active[1].connect() as connection:
        connection.execute("UPDATE acquisitions SET mode=?", (mode,))
    response = client.post(
        base + "/fragment-xic", json={"psm_id": psm["id"], "start": 210, "stop": 280}
    )
    assert response.status_code == 400
    assert "marked DIA" in response.json()["detail"]


@pytest.mark.parametrize(
    "fault, message",
    [
        ("selected_missing", "no usable MS2 isolation window"),
        ("interval_missing", "unknown isolation windows"),
        ("overlap_outside_interval", "non-overlapping"),
        ("outside_precursor", "outside the selected isolation window"),
        ("missing_precursor", "no peptide precursor"),
        ("unresolved", "no resolved spectrum"),
    ],
)
def test_fragment_xic_rejects_ambiguous_metadata(
    dia_session: DiaSession, fault: str, message: str
) -> None:
    """Do not fabricate windows, confuse isolation centers, or merge staggered channels."""
    client, base, psm = dia_session
    with client.app.state.runtime.active[1].connect() as connection:
        if fault == "selected_missing":
            connection.execute("UPDATE scans SET isolation_lower_mz=NULL WHERE ordinal=79")
        elif fault == "interval_missing":
            connection.execute("UPDATE scans SET isolation_upper_mz=NULL WHERE ordinal=83")
        elif fault == "overlap_outside_interval":
            connection.execute("UPDATE scans SET isolation_lower_mz=395 WHERE ordinal=3")
        elif fault == "outside_precursor":
            connection.execute("UPDATE psms SET precursor_mz=450 WHERE id=?", (psm["id"],))
        elif fault == "missing_precursor":
            connection.execute("UPDATE psms SET precursor_mz=NULL WHERE id=?", (psm["id"],))
        else:
            connection.execute("UPDATE psms SET resolved=0 WHERE id=?", (psm["id"],))
    response = client.post(
        base + "/fragment-xic", json={"psm_id": psm["id"], "start": 210, "stop": 280}
    )
    assert response.status_code == 400
    assert message in response.json()["detail"]


def test_fragment_xic_empty_interval_and_cache_bound(
    dia_session: DiaSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Keep empty results explicit and avoid retaining large trace matrices."""
    client, base, psm = dia_session
    request = {"psm_id": psm["id"], "start": 900, "stop": 910}
    empty = client.post(base + "/fragment-xic", json=request).json()
    assert empty["rt"] == [] and empty["scan_count"] == 0
    assert all(fragment["intensity"] == [] for fragment in empty["fragments"])
    service = client.app.state.runtime.signal
    monkeypatch.setattr(service, "max_cached_trace_scans", 1)
    result = client.post(base + "/fragment-xic", json={**request, "start": 210, "stop": 280})
    assert result.status_code == 200
    assert service.fragment_traces == {}
    invalid = client.post(base + "/fragment-xic", json={**request, "stop": 0})
    assert invalid.status_code == 422
    assert (
        client.post(base + "/fragment-xic", json={**request, "psm_id": 999999}).status_code == 400
    )


def test_fragment_targets_preserve_modifications() -> None:
    """Use modified theoretical masses rather than observed peaks for extraction targets."""
    theoretical = oms.MSSpectrum()
    sequence = "PEPTM(Oxidation)IDE"
    oms.TheoreticalSpectrumGenerator().getSpectrum(
        theoretical, oms.AASequence.fromString(sequence), 1, 1
    )
    masses = np.array([peak.getMZ() for peak in theoretical])
    annotations = FragmentAnnotator().annotate({"masses": masses * (1 + 5e-6)}, sequence, 20)
    np.testing.assert_allclose([row["mz"] for row in annotations], masses)
    assert all(abs(row["ppm"] - 5) < 1e-6 for row in annotations)


def test_isolation_bounds_require_nonempty_unambiguous_windows() -> None:
    """Keep missing, invalid, and multiplexed precursor windows explicitly unknown."""
    precursor = oms.Precursor()
    precursor.setMZ(400)
    assert ProjectPreparer.isolation_bounds([precursor]) == (None, None)
    precursor.setIsolationWindowLowerOffset(10)
    precursor.setIsolationWindowUpperOffset(15)
    assert ProjectPreparer.isolation_bounds([precursor]) == (390, 415)
    assert ProjectPreparer.isolation_bounds([precursor, precursor]) == (None, None)
    assert ProjectPreparer.isolation_bounds([]) == (None, None)


def test_acquisition_mode_edit_reuses_signal(
    dia_session: DiaSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Changing mode updates catalog metadata without decoding raw data or importing PSMs."""
    client, _, _ = dia_session
    configuration = client.get("/api/configuration").json()
    configuration["acquisitions"][0]["mode"] = "DDA"

    def reject_reindex(*_args, **_kwargs) -> None:
        """An acquisition-mode edit must reuse existing signal artifacts."""
        pytest.fail("Acquisition mode edit reread mzML")

    monkeypatch.setattr(ProjectPreparer, "acquisition", reject_reindex)
    assert client.post("/api/open-configuration", json=configuration).status_code == 202
    wait_for_project(client)
    base = "/api/projects/" + client.get("/api/status").json()["token"]
    assert client.get(base).json()["acquisitions"][0]["mode"] == "DDA"
    assert ProjectInput.model_validate(configuration).acquisitions[0].mode == "DDA"
    assert FragmentXicRequest(psm_id=1, start=0, stop=1).ppm == 20


def test_target_intensities_sum_unsorted_peaks() -> None:
    """Retain every in-window peak without requiring sorted mzML input arrays."""
    spectrum = oms.MSSpectrum()
    spectrum.set_peaks((np.array([100.0001, 200, 100, 99.9999]), np.array([1.0, 50.0, 2.0, 3.0])))
    result = FragmentXicExtractor.target_intensities(
        spectrum, np.array([100.0, 300.0]), np.array([0.001, 0.003])
    )
    assert result == [6, 0]


def test_no_matched_fragments_is_explicit(dia_session: DiaSession) -> None:
    """Do not extract unrelated masses when the selected tolerance matches no ions."""
    client, base, psm = dia_session
    response = client.post(
        base + "/fragment-xic", json={"psm_id": psm["id"], "start": 210, "stop": 280, "ppm": 0.1}
    )
    assert response.status_code == 400
    assert "No b/y fragments match" in response.json()["detail"]
