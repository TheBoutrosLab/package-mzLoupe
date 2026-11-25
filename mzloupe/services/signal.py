"""Bounded spectrum retrieval, chromatograms, and fragment annotation."""

from pathlib import Path
from typing import Any

import numpy as np
import pyopenms as oms

from mzloupe.models import FragmentXicRequest, MapTargetRequest, XicRequest
from mzloupe.services.fragment_xic import FragmentXicExtractor
from mzloupe.readers.mzml import MzMLReader
from mzloupe.storage.catalog import ProjectCatalog


class SignalService:
    """Combine catalog headers with indexed peak access and small session caches.

    Retain one active reader, the latest displayed spectrum, and the latest XIC.
    Cache entries have size limits; MS1 arrays decoded during extraction are not
    retained. The project runtime serializes access to the shared native reader.
    """

    max_cached_spectrum_peaks = 50_000
    max_cached_trace_scans = 20_000
    max_cached_candidates = 1_000

    def __init__(self, catalog: ProjectCatalog, workspace: Path) -> None:
        """Use one prepared project's metadata and cached map directory."""
        self.catalog = catalog
        self.workspace = workspace
        self.readers: dict[str, MzMLReader] = {}
        self.spectra: dict[tuple[str, int], dict[str, Any]] = {}
        self.traces: dict[tuple[str, float, float, float, float], dict[str, Any]] = {}
        self.fragment_traces: dict[str, dict[str, Any]] = {}

    def reader(self, source: str) -> MzMLReader:
        """Reuse one active index-only reader, rejecting unknown acquisition IDs."""
        cached = self.readers.get(source)
        if cached is not None:
            return cached
        rows = self.catalog.rows("SELECT path FROM acquisitions WHERE id=?", (source,))
        if not rows:
            raise ValueError("Unknown acquisition")
        reader = MzMLReader(rows[0]["path"], load_metadata=False)
        self.readers.clear()
        self.readers[source] = reader
        return reader

    def spectrum(self, source: str, ordinal: int) -> dict[str, Any]:
        """Return a scan's peaks and catalog headers, reusing it for annotation requests."""
        key = (source, ordinal)
        cached = self.spectra.get(key)
        if cached is not None:
            return cached
        metadata = self.catalog.scan(source, ordinal)
        spectrum = self.reader(source).spectrum(ordinal)
        masses, intensities = spectrum.get_peaks()
        result = {
            **metadata,
            "masses": masses.tolist(),
            "intensities": intensities.tolist(),
            "candidates": self.catalog.candidates(source, metadata["native"]),
        }
        self.spectra.clear()
        if (
            len(masses) <= self.max_cached_spectrum_peaks
            and len(result["candidates"]) <= self.max_cached_candidates
        ):
            self.spectra[key] = result
        return result

    def map(self, source: str) -> dict[str, Any]:
        """Return the cached log10(1 + intensity) MS1 map and MS2 isolation centers."""
        rows = self.catalog.rows("SELECT id FROM acquisitions WHERE id=?", (source,))
        if not rows:
            raise ValueError("Unknown acquisition")
        with np.load(self.workspace / f"{source}.npz") as data:
            grid, bounds = data["grid"], data["bounds"]
            log_grid = np.log10(1 + grid)
            return {
                "intensity": log_grid.tolist(),
                "bounds": bounds.tolist(),
                "scale_max": max(1.0, float(np.ceil(log_grid.max()))),
                "events": self.catalog.rows(
                    "SELECT ordinal, rt, mz FROM scans "
                    "WHERE source=? AND level=2 AND mz IS NOT NULL",
                    (source,),
                ),
            }

    def map_target(self, request: MapTargetRequest) -> dict[str, Any]:
        """Resolve a map cell in seconds and m/z to its strongest measured MS1 peak."""
        scans = self.catalog.rows(
            "SELECT ordinal,rt FROM scans "
            "WHERE source=? AND level=1 AND rt BETWEEN ? AND ? ORDER BY rt",
            (request.source, request.start, request.stop),
        )
        reader = self.reader(request.source)
        target: dict[str, Any] | None = None
        strongest_intensity = 0.0
        for scan in scans:
            masses, intensities = reader.spectrum(scan["ordinal"]).get_peaks()
            selected = np.flatnonzero(
                (masses >= request.mz_start) & (masses <= request.mz_stop) & (intensities > 0)
            )
            if len(selected) == 0:
                continue
            peak = selected[int(np.argmax(intensities[selected]))]
            intensity = float(intensities[peak])
            if intensity > strongest_intensity:
                strongest_intensity = intensity
                target = {
                    "source": request.source,
                    "rt": scan["rt"],
                    "ordinal": scan["ordinal"],
                    "mz": float(masses[peak]),
                    "intensity": intensity,
                }
        if target is None:
            raise ValueError("No positive MS1 peak in this map cell. Select a cell with signal.")
        return target

    def xic(self, request: XicRequest) -> dict[str, Any]:
        """Sum MS1 intensities within a ppm window for each scan in an RT interval.

        Retention times are in seconds. Empty intervals return empty arrays;
        scans without matching peaks contribute zero intensity. Include all
        resolved PSMs in the same fraction, RT interval, and peptide m/z window.
        Reuse an identical extraction within this prepared project session.
        """
        key = (request.source, request.mz, request.ppm, request.start, request.stop)
        cached = self.traces.get(key)
        if cached is not None:
            return cached
        reader = self.reader(request.source)
        scans = self.catalog.rows(
            "SELECT ordinal,rt FROM scans "
            "WHERE source=? AND level=1 AND rt BETWEEN ? AND ? ORDER BY rt",
            (request.source, request.start, request.stop),
        )
        tolerance = request.mz * request.ppm / 1e6
        values = []
        for scan in scans:
            masses, intensities = reader.spectrum(scan["ordinal"]).get_peaks()
            selected = (masses >= request.mz - tolerance) & (masses <= request.mz + tolerance)
            values.append(float(intensities[selected].sum()))
        result = {
            "rt": [scan["rt"] for scan in scans],
            "intensity": values,
            "mz": request.mz,
            "ppm": request.ppm,
            "source": request.source,
            "start": request.start,
            "stop": request.stop,
            "scan_count": len(scans),
            "matched_scan_count": sum(value > 0 for value in values),
            "psms": self.catalog.precursor_psms(
                source=request.source,
                start=request.start,
                stop=request.stop,
                mz_min=request.mz - tolerance,
                mz_max=request.mz + tolerance,
            ),
        }
        self.traces.clear()
        if (
            len(scans) <= self.max_cached_trace_scans
            and len(result["psms"]) <= self.max_cached_candidates
        ):
            self.traces[key] = result
        return result

    def fragment_xic(self, request: FragmentXicRequest) -> dict[str, Any]:
        """Extract all matched b/y ions in one pass over the eligible DIA scans.

        Resolve the PSM on the server so precursor and fragment masses cannot drift
        away from the selected identification. Retain only the latest bounded result.
        """
        key = request.model_dump_json()
        cached = self.fragment_traces.get(key)
        if cached is not None:
            return cached
        extractor = FragmentXicExtractor(self.catalog)
        psm = extractor.psm(request.psm_id)
        spectrum = self.spectrum(psm["source"], psm["ordinal"])
        targets = FragmentAnnotator().annotate(spectrum, psm["sequence"], request.ppm)
        if not targets:
            raise ValueError("No b/y fragments match this PSM at the selected fragment tolerance")
        result = extractor.extract(request, psm, targets, self.reader(psm["source"]))
        self.fragment_traces.clear()
        if result["scan_count"] * len(targets) <= self.max_cached_trace_scans:
            self.fragment_traces[key] = result
        return result


class FragmentAnnotator:
    """Match theoretical singly charged fragments to the nearest measured peaks."""

    def annotate(
        self,
        spectrum: dict[str, Any],
        sequence: str,
        ppm: float,
    ) -> list[dict[str, int | str | float]]:
        """Label peaks whose mass error falls within the supplied ppm tolerance."""
        theoretical = self.theoretical_spectrum(sequence)
        labels = theoretical.getStringDataArrays()[0]
        masses = np.asarray(spectrum["masses"])
        annotations = []
        # The native peak and label arrays share their order. Index them directly
        # because the generated bindings do not describe their iterators fully.
        for peak_index in range(min(theoretical.size(), len(labels))):
            if len(masses) == 0:
                break
            peak = theoretical[peak_index]
            label = labels[peak_index]
            index = int(np.abs(masses - peak.getMZ()).argmin())
            error = (masses[index] - peak.getMZ()) / peak.getMZ() * 1e6
            if abs(error) <= ppm:
                text = label.decode() if isinstance(label, bytes) else str(label)
                annotations.append(
                    {
                        "index": index,
                        "label": text,
                        "ppm": float(error),
                        "mz": float(peak.getMZ()),
                        "charge": 1,
                    }
                )
        return annotations

    @staticmethod
    def theoretical_spectrum(sequence: str) -> oms.MSSpectrum:
        """Generate labeled singly charged b/y ions from a modified peptide sequence."""
        generator = oms.TheoreticalSpectrumGenerator()
        parameters = generator.getParameters()
        parameters.setValue("add_metainfo", "true")
        generator.setParameters(parameters)
        theoretical = oms.MSSpectrum()
        generator.getSpectrum(
            theoretical,
            oms.AASequence.fromString(sequence),
            1,
            1,
        )
        return theoretical
