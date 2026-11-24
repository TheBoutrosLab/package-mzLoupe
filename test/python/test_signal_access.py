"""Protect indexed signal access, bounded caching, and project isolation."""

from pathlib import Path
import shutil

import numpy as np
import pytest

from mzloupe.app import ProjectRuntime
from mzloupe.demo import DemoProject
from mzloupe.models import ProjectInput, XicRequest
from mzloupe.services.preparation import ProjectPreparer
from mzloupe.services.signal import SignalService
from mzloupe.storage.catalog import ProjectCatalog


@pytest.fixture
def signal_service(tmp_path: Path) -> SignalService:
    """Prepare a small real mzML/idXML project without opening network listeners."""
    manifest = DemoProject().write(tmp_path / "data")
    project = ProjectInput.load(manifest)
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    def progress(_message: str, _fraction: float) -> None:
        """Preparation progress does not need a UI in these signal regressions."""

    catalog = ProjectPreparer(workspace).prepare(project, progress)
    return SignalService(catalog, workspace)


def test_index_only_signal_uses_catalog_headers(signal_service: SignalService) -> None:
    """Keep RT, MS level, and precursors correct when native index-only headers are absent."""
    result = signal_service.spectrum("fraction_01", 79)
    assert signal_service.reader("fraction_01").headers is None
    assert result["native"] == "scan=80"
    assert result["rt"] == 237
    assert result["level"] == 2
    assert result["mz"] == 400.6873
    assert result["charge"] == 2
    assert len(result["masses"]) > 5
    assert len(result["masses"]) == len(result["intensities"])
    assert max(result["intensities"]) > 0


def test_signal_results_follow_source_target_and_bounds(signal_service: SignalService) -> None:
    """Do not reuse a previous fraction, target, tolerance, or interval's extraction."""
    request = XicRequest(source="fraction_01", mz=400.6873, ppm=10, start=210, stop=280)
    first = signal_service.xic(request)
    second = signal_service.xic(request.model_copy(update={"source": "fraction_02"}))
    assert second["source"] == "fraction_02"
    assert not np.array_equal(first["intensity"], second["intensity"])
    assert all(psm["source"] == "fraction_02" for psm in second["psms"])
    different_target = signal_service.xic(request.model_copy(update={"mz": 450.0}))
    assert different_target["mz"] == 450.0
    assert different_target["psms"] == []
    different_tolerance = signal_service.xic(request.model_copy(update={"ppm": 20.0}))
    assert different_tolerance["ppm"] == 20.0
    narrow = signal_service.xic(request.model_copy(update={"start": 236, "stop": 238}))
    assert narrow["rt"] == []
    assert len(narrow["psms"]) == 3
    first_scan = signal_service.spectrum("fraction_01", 79)
    second_scan = signal_service.spectrum("fraction_02", 79)
    assert first_scan["source"] != second_scan["source"]
    assert first_scan["candidates"][0]["id"] != second_scan["candidates"][0]["id"]


def test_large_results_are_returned_without_retaining_them(
    signal_service: SignalService,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Keep all requested data even when a result exceeds the in-memory cache limits."""
    monkeypatch.setattr(signal_service, "max_cached_spectrum_peaks", 1)
    monkeypatch.setattr(signal_service, "max_cached_trace_scans", 1)
    spectrum = signal_service.spectrum("fraction_01", 79)
    assert len(spectrum["masses"]) > 1
    assert signal_service.spectra == {}
    request = XicRequest(source="fraction_01", mz=400.6873, ppm=10, start=210, stop=280)
    trace = signal_service.xic(request)
    assert trace["scan_count"] > 1
    assert trace["matched_scan_count"] > 0
    assert signal_service.traces == {}


def test_project_change_replaces_cached_signal(
    signal_service: SignalService,
    tmp_path: Path,
) -> None:
    """Discard old results when a new workspace reuses acquisition IDs and ordinals."""
    project = ProjectInput.load(tmp_path / "data" / "project.json")
    runtime = ProjectRuntime(tmp_path / "runtime")
    runtime.active = (project, signal_service.catalog, signal_service.workspace)
    runtime.token = "original"
    try:
        with runtime.signal_lock:
            original = runtime.signal_service("original").spectrum("fraction_01", 79)
        replacement = tmp_path / "replacement"
        replacement.mkdir()
        shutil.copyfile(signal_service.catalog.path, replacement / "catalog.sqlite")
        catalog = ProjectCatalog(replacement / "catalog.sqlite")
        with catalog.connect() as connection:
            connection.execute("UPDATE psms SET score=0.777")
        runtime.active = (project, catalog, replacement)
        runtime.token = "replacement"
        with runtime.signal_lock:
            updated = runtime.signal_service("replacement").spectrum("fraction_01", 79)
            with pytest.raises(ValueError, match="Project changed"):
                runtime.signal_service("original")
        assert original["candidates"][0]["score"] != 0.777
        assert all(candidate["score"] == 0.777 for candidate in updated["candidates"])
    finally:
        runtime.close()
    assert runtime.signal is None
