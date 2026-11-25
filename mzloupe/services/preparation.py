"""Prepare sources sequentially and publish the entire project atomically."""

from collections.abc import Callable
import errno
from pathlib import Path
import json
import os
import shutil
import sqlite3

import numpy as np
import pyopenms as oms

from mzloupe.models import AcquisitionInput, ProjectInput
from mzloupe.readers.mzml import MzMLReader
from mzloupe.services.identifications import IdentificationImporter
from mzloupe.services.project_cache import ProjectCache
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
        previous: Path | None = None,
        description: dict | None = None,
    ) -> ProjectCatalog:
        """Reuse unchanged acquisitions and reimport only affected sample/layer inputs."""
        state = description or ProjectCache.inputs(project)
        old = ProjectCache.description(previous)
        catalog = self.copy_catalog(previous)
        self.update_acquisitions(
            catalog, project, progress=progress, previous=previous, state=state, old=old
        )
        progress("Resolving sample identification files", 0.95)
        self.update_identifications(catalog, project, state, old)
        return catalog

    def copy_catalog(self, previous: Path | None) -> ProjectCatalog:
        """Stage compact metadata while preserving the previous reader's snapshot."""
        catalog = ProjectCatalog(self.workspace / "catalog.sqlite")
        if previous is None:
            catalog.create()
        else:
            with sqlite3.connect(previous / "catalog.sqlite") as source:
                with catalog.connect() as destination:
                    source.backup(destination)
        return catalog

    def update_acquisitions(
        self,
        catalog: ProjectCatalog,
        project: ProjectInput,
        *,
        progress: Callable[[str, float], None],
        previous: Path | None,
        state: dict,
        old: dict,
    ) -> None:
        """Reuse unchanged signal artifacts and index only added or replaced acquisitions."""
        retained = {item.id for item in project.acquisitions}
        with catalog.connect() as connection:
            for row in connection.execute("SELECT id FROM acquisitions").fetchall():
                if row["id"] not in retained:
                    connection.execute("DELETE FROM scans WHERE source=?", (row["id"],))
                    connection.execute("DELETE FROM acquisitions WHERE id=?", (row["id"],))
            connection.execute("DELETE FROM layers")
        for number, acquisition in enumerate(project.acquisitions):
            unchanged = (
                old.get("acquisitions", {}).get(acquisition.id)
                == state["acquisitions"][acquisition.id]
            )
            if unchanged and previous is not None:
                progress(f"Reusing {acquisition.fraction}", number / len(project.acquisitions))
                if self.reuse(catalog, acquisition, previous):
                    continue
            # Missing catalog headers make reuse impossible even when the file is unchanged.
            progress(f"Indexing {acquisition.fraction}", number / len(project.acquisitions))
            with catalog.connect() as connection:
                connection.execute("DELETE FROM scans WHERE source=?", (acquisition.id,))
                connection.execute("DELETE FROM acquisitions WHERE id=?", (acquisition.id,))
            self.acquisition(catalog, acquisition)

    @staticmethod
    def update_identifications(
        catalog: ProjectCatalog, project: ProjectInput, state: dict, old: dict
    ) -> None:
        """Re-resolve changed sample scopes without duplicating unaffected PSM imports."""
        importer = IdentificationImporter(catalog, project)
        for key in old.get("identifications", {}):
            if old["identifications"][key] != state["identifications"].get(key):
                sample, layer, path = json.loads(key)
                with catalog.connect() as connection:
                    connection.execute(
                        "DELETE FROM psms WHERE sample=? AND layer=? AND source_path=?",
                        (sample, layer, path),
                    )
        for (sample, layer, path), sources in project.identification_sources().items():
            key = json.dumps([sample, layer, path])
            if old.get("identifications", {}).get(key) != state["identifications"][key]:
                importer.import_source(sample=sample, layer=layer, path=path, source_ids=sources)
            else:
                with catalog.connect() as connection:
                    importer.register_layers(connection=connection, source_ids=sources, layer=layer)

    def reuse(self, catalog: ProjectCatalog, acquisition: AcquisitionInput, previous: Path) -> bool:
        """Carry prepared artifacts forward, or return False when catalog headers are missing.

        Check the catalog before creating files so the caller can safely re-index
        this acquisition without overwriting a hard-linked artifact from the old revision.
        """
        rows = catalog.rows("SELECT path FROM acquisitions WHERE id=?", (acquisition.id,))
        if not rows:
            return False
        path = rows[0]["path"]
        for suffix in (".npz", ".mzML"):
            source = previous / (acquisition.id + suffix)
            if source.is_file():
                self.link_or_copy(source, self.workspace / source.name)
        if Path(path).parent == previous:
            path = str(self.workspace / Path(path).name)
        with catalog.connect() as connection:
            connection.execute(
                "UPDATE acquisitions SET sample=?, fraction=?, path=?, mode=? WHERE id=?",
                (acquisition.sample, acquisition.fraction, path, acquisition.mode, acquisition.id),
            )
        return True

    @staticmethod
    def link_or_copy(source: Path, destination: Path) -> None:
        """Share an immutable artifact when possible; copy it if hard links are unavailable.

        Keep unrelated errors visible, including missing files, existing destinations,
        I/O failures, and exhausted storage. A failed fallback copy also propagates.
        """
        try:
            os.link(source, destination)
        except OSError as error:
            if error.errno not in {
                errno.EXDEV,
                errno.ENOTSUP,
                errno.EOPNOTSUPP,
                errno.ENOSYS,
                errno.EPERM,
            }:
                raise
            shutil.copy2(source, destination)

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
                "INSERT INTO acquisitions VALUES (?,?,?,?,?)",
                (
                    acquisition.id,
                    acquisition.sample,
                    acquisition.fraction,
                    str(signal_path),
                    acquisition.mode,
                ),
            )
            for ordinal in range(reader.count()):
                spectrum = reader.metadata(ordinal)
                precursor = spectrum.getPrecursors()
                mz = precursor[0].getMZ() if precursor else None
                charge = precursor[0].getCharge() if precursor else None
                lower, upper = self.isolation_bounds(precursor)
                db.execute(
                    "INSERT INTO scans VALUES (?,?,?,?,?,?,?,?,?)",
                    (
                        acquisition.id,
                        ordinal,
                        spectrum.getNativeID(),
                        spectrum.getRT(),
                        spectrum.getMSLevel(),
                        mz,
                        charge,
                        lower,
                        upper,
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
    def isolation_bounds(precursors: list[oms.Precursor]) -> tuple[float | None, float | None]:
        """Keep only finite, nonempty isolation windows with one unambiguous precursor.

        OpenMS reports positive offsets relative to the isolation center. Zero
        offsets on both sides usually mean the file did not supply window metadata.
        Multiple precursor entries need a separate window model and remain unknown.
        """
        if len(precursors) != 1:
            return None, None
        precursor = precursors[0]
        center = precursor.getMZ()
        lower_offset = precursor.getIsolationWindowLowerOffset()
        upper_offset = precursor.getIsolationWindowUpperOffset()
        values = (center, lower_offset, upper_offset)
        if not all(np.isfinite(value) for value in values):
            return None, None
        if center <= 0 or min(lower_offset, upper_offset) < 0:
            return None, None
        lower, upper = center - lower_offset, center + upper_offset
        if lower <= 0 or upper <= lower:
            return None, None
        return lower, upper

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
