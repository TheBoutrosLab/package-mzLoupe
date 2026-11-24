"""Scientific regressions for DIA precursor targets and map bin boundaries."""

from pathlib import Path
import time

from fastapi.testclient import TestClient
import numpy as np
import pyopenms as oms

from mzloupe.app import create_app
from mzloupe.demo import DemoProject


def test_peptide_target_is_independent_of_isolation_center(tmp_path: Path) -> None:
    """Preserve peptide XIC targets, calculated fallbacks, and total map intensity."""
    manifest = DemoProject().write(tmp_path / "data")
    for path in manifest.parent.glob("*.mzML"):
        experiment = oms.MSExperiment()
        oms.MzMLFile().load(str(path), experiment)
        for index in range(experiment.size()):
            spectrum = experiment[index]
            if spectrum.getMSLevel() == 2:
                precursor = spectrum.getPrecursors()[0]
                precursor.setMZ(404.0)
                spectrum.setPrecursors([precursor])
                experiment[index] = spectrum
        oms.MzMLFile().store(str(path), experiment)
    # A file without reported peptide m/z falls back to the sequence and charge.
    identification_path = manifest.parent / "sample_Search.idXML"
    proteins, peptides = oms.IdXMLFile().load(str(identification_path))
    for index, peptide in enumerate(peptides):
        peptide.setMZ(float("nan"))
        peptides[index] = peptide
    oms.IdXMLFile().store(
        str(identification_path),
        proteins,
        oms.PeptideIdentificationList(peptides),
    )
    with TestClient(create_app(tmp_path / "cache", manifest)) as client:
        for _ in range(100):
            state = client.get("/api/status").json()
            if state["state"] != "preparing":
                break
            time.sleep(0.05)
        assert state["state"] == "ready", state
        base = "/api/projects/" + state["token"]
        spectrum = client.get(base + "/sources/fraction_01/spectra/79").json()
        assert spectrum["mz"] == 404.0
        psm = next(row for row in spectrum["candidates"] if row["layer"] == "Validated")
        assert psm["precursor_mz"] == 400.6873
        assert psm["precursor_mz_origin"] == "idXML"
        calculated = next(row for row in spectrum["candidates"] if row["layer"] == "Search")
        assert abs(calculated["precursor_mz"] - 400.6873) < 0.001
        assert calculated["precursor_mz_origin"] == "calculated"
        request = {
            "source": "fraction_01",
            "mz": psm["precursor_mz"],
            "ppm": 10,
            "start": 210,
            "stop": 255,
        }
        peptide_trace = client.post(
            base + "/xic",
            json=request,
        ).json()
        center_trace = client.post(
            base + "/xic",
            json={**request, "mz": 404.0},
        ).json()
        assert peptide_trace["matched_scan_count"] > 0
        assert peptide_trace["psms"]
        assert {psm["layer"] for psm in peptide_trace["psms"]} == {"Search", "Validated"}
        assert all(psm["source"] == "fraction_01" for psm in peptide_trace["psms"])
        assert center_trace["matched_scan_count"] == 0
        assert center_trace["psms"] == []
        assert peptide_trace["scan_count"] == len(peptide_trace["rt"])
        no_scans = client.post(
            base + "/xic",
            json={**request, "start": 900, "stop": 910},
        ).json()
        assert no_scans["scan_count"] == 0
        assert no_scans["psms"] == []
        map_data = client.get(base + "/sources/fraction_01/map").json()
        assert map_data["scale_max"] >= np.max(map_data["intensity"])
        with np.load(tmp_path / "cache" / state["token"] / "fraction_01.npz") as grid:
            map_sum = grid["grid"].sum()
        original = oms.MSExperiment()
        oms.MzMLFile().load(str(manifest.parent / "fraction_01.mzML"), original)
        expected = sum(s.get_peaks()[1].sum() for s in original if s.getMSLevel() == 1)
        np.testing.assert_allclose(map_sum, expected, rtol=1e-6)
