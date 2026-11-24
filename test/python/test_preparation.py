"""Keep initial preparation independent of unneeded MS2 peak decoding."""

from pathlib import Path

import pyopenms as oms
import pytest

from mzloupe.demo import DemoProject
from mzloupe.models import ProjectInput
from mzloupe.readers.mzml import MzMLReader
from mzloupe.services.preparation import ProjectPreparer


def test_preparation_uses_headers_for_ms2_scans(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Prepare maps and resolve PSMs even when MS2 peak retrieval is unavailable."""
    manifest = DemoProject().write(tmp_path / "data")
    project = ProjectInput.load(manifest)
    original_spectrum = MzMLReader.spectrum

    def ms1_spectrum(reader: MzMLReader, ordinal: int) -> oms.MSSpectrum:
        """Allow MS1 signal access while rejecting accidental MS2 peak decoding."""
        metadata = reader.metadata(ordinal)
        assert metadata.size() == 0
        assert metadata.getMSLevel() == 1, "Preparation must not decode MS2 peak arrays"
        return original_spectrum(reader, ordinal)

    monkeypatch.setattr(MzMLReader, "spectrum", ms1_spectrum)
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    messages = []

    def progress(message: str, fraction: float) -> None:
        """Capture progress without starting an application server."""
        messages.append((message, fraction))

    catalog = ProjectPreparer(workspace).prepare(project, progress)
    acquisitions = catalog.acquisitions("Validated")
    assert len(acquisitions) == 2
    assert all(row["ms2"] == 40 and row["identified"] == 5 for row in acquisitions)
    scan = catalog.scan("fraction_01", 79)
    assert scan["native"] == "scan=80"
    assert scan["rt"] == 237
    assert scan["mz"] == 400.6873
    assert scan["charge"] == 2
    assert (workspace / "fraction_01.npz").is_file()
    assert (workspace / "fraction_02.npz").is_file()
