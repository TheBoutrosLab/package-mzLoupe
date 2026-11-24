"""Disk-backed access to a single indexed acquisition."""

from pathlib import Path

import pyopenms as oms


class MzMLReader:
    """Read spectra on demand through the native OpenMS on-disk experiment."""

    def __init__(self, path: str | Path, *, load_metadata: bool = True) -> None:
        """Open the index, optionally reading scan headers for project preparation.

        Interactive requests already have headers in SQLite and can skip the
        XML metadata pass. Both modes leave peak arrays on disk until requested.
        """
        self.experiment = oms.OnDiscMSExperiment()
        if not self.experiment.openFile(str(path), not load_metadata):
            raise ValueError("mzML needs a valid index. Convert it to indexed mzML before loading.")
        # Preparation shares OpenMS's peak-free headers. Interactive reads use
        # the catalog instead and skip XML metadata loading entirely.
        self.headers = self.experiment.getMetaData() if load_metadata else None

    def metadata(self, ordinal: int) -> oms.MSSpectrum:
        """Return one spectrum's header, including precursors, without decoding peaks."""
        if self.headers is None:
            raise ValueError("This reader was opened without scan metadata")
        return self.headers.getSpectrum(ordinal)

    def spectrum(self, ordinal: int) -> oms.MSSpectrum:
        """Load a zero-based spectrum; index-only mode provides peaks without full headers.

        Read RT, MS level, and precursor information from the project catalog
        when load_metadata is False, as OpenMS does not fill these header fields.
        """
        return self.experiment.getSpectrum(ordinal)

    def count(self) -> int:
        """Return the spectrum count recorded in the mzML index."""
        return self.experiment.getNrSpectra()
