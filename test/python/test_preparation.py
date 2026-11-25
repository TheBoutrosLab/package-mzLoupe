"""Keep initial preparation independent of unneeded MS2 peak decoding."""

import errno
import os
from pathlib import Path
import shutil

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


@pytest.mark.parametrize("error_number", [errno.EXDEV, errno.EOPNOTSUPP, errno.ENOSYS, errno.EPERM])
def test_artifact_copy_fallback_preserves_contents_and_metadata(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, error_number: int
) -> None:
    """Unsupported hard links fall back to an independent copy with the source timestamp."""
    source = tmp_path / "original.npz"
    destination = tmp_path / "reused.npz"
    source.write_bytes(b"Prepared signal artifact")
    timestamp = 1_700_000_000_000_000_000
    os.utime(source, ns=(timestamp, timestamp))

    def unsupported_link(_source: Path, _destination: Path) -> None:
        """Simulate a filesystem that cannot hard-link these artifacts."""
        raise OSError(error_number, "Hard linking unavailable")

    monkeypatch.setattr(os, "link", unsupported_link)
    ProjectPreparer.link_or_copy(source, destination)
    assert destination.read_bytes() == source.read_bytes()
    assert destination.stat().st_mtime_ns == source.stat().st_mtime_ns
    assert not os.path.samefile(source, destination)


@pytest.mark.parametrize(
    "error_number", [errno.ENOENT, errno.EEXIST, errno.EIO, errno.ENOSPC, errno.EACCES]
)
def test_unrelated_link_errors_are_not_hidden_by_copying(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, error_number: int
) -> None:
    """Only link capability restrictions permit fallback; other errors retain their cause."""
    source = tmp_path / "original.npz"
    destination = tmp_path / "reused.npz"
    source.write_bytes(b"Prepared signal artifact")

    def fail_link(_source: Path, _destination: Path) -> None:
        """Raise a specific filesystem failure unrelated to hard-link support."""
        raise OSError(error_number, "Filesystem failure")

    def reject_copy(*_args, **_kwargs) -> None:
        """A fallback must not disguise this failure or overwrite an existing destination."""
        pytest.fail("Unexpected fallback copy")

    monkeypatch.setattr(os, "link", fail_link)
    monkeypatch.setattr(shutil, "copy2", reject_copy)
    with pytest.raises(OSError) as failure:
        ProjectPreparer.link_or_copy(source, destination)
    assert failure.value.errno == error_number
    assert not destination.exists()


def test_fallback_copy_failure_propagates(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A copy failure remains visible so preparation cannot publish incomplete artifacts."""

    def unsupported_link(_source: Path, _destination: Path) -> None:
        """Require the copy fallback."""
        raise OSError(errno.EXDEV, "Different filesystems")

    def full_storage(_source: Path, _destination: Path) -> None:
        """Simulate exhausted storage while copying the prepared artifact."""
        raise OSError(errno.ENOSPC, "No space left")

    monkeypatch.setattr(os, "link", unsupported_link)
    monkeypatch.setattr(shutil, "copy2", full_storage)
    with pytest.raises(OSError) as failure:
        ProjectPreparer.link_or_copy(tmp_path / "source.npz", tmp_path / "destination.npz")
    assert failure.value.errno == errno.ENOSPC
