"""Prepare sources sequentially and publish the entire project atomically."""

from collections.abc import Callable
from pathlib import Path

import numpy as np
import pyopenms as oms

from mzloupe.models import AcquisitionInput, ProjectInput
from mzloupe.readers.mzml import MzMLReader
from mzloupe.services.identifications import IdentificationImporter
from mzloupe.storage.catalog import ProjectCatalog


class ProjectPreparer:
    """Index acquisitions and import identifications into a project workspace."""

    def __init__(self, workspace: Path) -> None:
        """Use the staging directory supplied by the project runtime."""
        self.workspace = workspace

    def prepare(
        self,
        project: ProjectInput,
        progress: Callable[[str, float], None],
    ) -> ProjectCatalog:
        """Prepare fractions sequentially, then resolve sample-level identifications."""
        catalog = ProjectCatalog(self.workspace / "catalog.sqlite")
        catalog.create()
        for number, acquisition in enumerate(project.acquisitions):
            progress(f"Indexing {acquisition.fraction}", number / len(project.acquisitions))
            self.acquisition(catalog, acquisition)
        progress("Resolving sample identification files", 0.95)
        IdentificationImporter(catalog, project).import_sources()
        return catalog

    def acquisition(self, catalog: ProjectCatalog, acquisition: AcquisitionInput) -> None:
        """Store scan metadata and a fixed-size MS1 map without retaining all peaks."""
        signal_path = self.indexed_source(acquisition)
        reader = MzMLReader(signal_path)
        if reader.count() == 0:
            raise ValueError(f"Empty acquisition: {acquisition.id}")
        # Streaming pass retains only compact metadata and a fixed-size map.
        grid = np.zeros((160, 240), dtype=np.float64)
        bounds = self.bounds(reader)
        with catalog.connect() as db:
            db.execute(
                "INSERT INTO acquisitions VALUES (?,?,?,?)",
                (acquisition.id, acquisition.sample, acquisition.fraction, str(signal_path)),
            )
            for ordinal in range(reader.count()):
                spectrum = reader.metadata(ordinal)
                precursor = spectrum.getPrecursors()
                mz = precursor[0].getMZ() if precursor else None
                charge = precursor[0].getCharge() if precursor else None
                db.execute(
                    "INSERT INTO scans VALUES (?,?,?,?,?,?,?)",
                    (
                        acquisition.id,
                        ordinal,
                        spectrum.getNativeID(),
                        spectrum.getRT(),
                        spectrum.getMSLevel(),
                        mz,
                        charge,
                    ),
                )
                if spectrum.getMSLevel() == 1:
                    self.add_ms1_signal(grid, reader.spectrum(ordinal), bounds)
        np.savez_compressed(
            self.workspace / f"{acquisition.id}.npz",
            grid=grid,
            bounds=bounds,
        )

    @staticmethod
    def add_ms1_signal(
        grid: np.ndarray,
        spectrum: oms.MSSpectrum,
        bounds: tuple[float, float, float, float],
    ) -> None:
        """Accumulate one MS1 spectrum into the 160-by-240 m/z/RT intensity grid."""
        rt_min, rt_max, mz_min, mz_max = bounds
        masses, intensities = spectrum.get_peaks()
        relative_rt = (spectrum.getRT() - rt_min) / (rt_max - rt_min)
        column = min(239, max(0, int(relative_rt * 240)))
        bins = np.floor((masses - mz_min) / (mz_max - mz_min) * 160).astype(int)
        valid = (bins >= 0) & (bins <= 160)
        # Include the upper boundary in the last bin so its intensity is retained.
        np.add.at(grid[:, column], np.minimum(bins[valid], 159), intensities[valid])

    def indexed_source(self, acquisition: AcquisitionInput) -> Path:
        """Reuse an indexed mzML or write an indexed working copy in the workspace."""
        probe = oms.OnDiscMSExperiment()
        if probe.openFile(acquisition.mzml, True):
            return Path(acquisition.mzml)
        working = self.workspace / f"{acquisition.id}.mzML"
        consumer = oms.PlainMSDataWritingConsumer(str(working))
        try:
            oms.MzMLFile().transform(acquisition.mzml, consumer)
        finally:
            del consumer
        return working

    def bounds(self, reader: MzMLReader) -> tuple[float, float, float, float]:
        """Scan retention times in seconds and MS1 m/z bounds for map binning.

        Expand degenerate ranges so binning never divides by zero. Acquisitions
        without MS1 peaks use a default m/z range of 100 to 1500.
        """
        rt_min, rt_max = float("inf"), float("-inf")
        mz_min, mz_max = float("inf"), float("-inf")
        for ordinal in range(reader.count()):
            spectrum = reader.metadata(ordinal)
            rt_min = min(rt_min, spectrum.getRT())
            rt_max = max(rt_max, spectrum.getRT())
            if spectrum.getMSLevel() == 1:
                masses, _ = reader.spectrum(ordinal).get_peaks()
                if len(masses):
                    mz_min = min(mz_min, float(masses.min()))
                    mz_max = max(mz_max, float(masses.max()))
        if not np.isfinite(mz_min):
            mz_min, mz_max = 100.0, 1500.0
        return rt_min, max(rt_max, rt_min + 1), mz_min, max(mz_max, mz_min + 1)
