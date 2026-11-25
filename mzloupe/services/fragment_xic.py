"""Select conventional DIA windows and extract peptide fragment chromatograms."""

from typing import Any

import numpy as np
import pyopenms as oms

from mzloupe.models import FragmentXicRequest
from mzloupe.readers.mzml import MzMLReader
from mzloupe.storage.catalog import ProjectCatalog


class FragmentXicExtractor:
    """Keep DIA scan eligibility separate from peak matching and UI state."""

    # Absolute m/z tolerance for isolation metadata, independent of extraction ppm.
    window_tolerance = 1e-6

    def __init__(self, catalog: ProjectCatalog) -> None:
        """Use the current prepared metadata snapshot without opening raw data."""
        self.catalog = catalog

    def psm(self, identifier: int) -> dict[str, Any]:
        """Require a resolved peptide precursor in an explicitly marked DIA run."""
        rows = self.catalog.rows(
            "SELECT p.*, s.ordinal, s.level, s.isolation_lower_mz, s.isolation_upper_mz, "
            "a.mode FROM psms p "
            "JOIN scans s ON s.source=p.source AND s.native=p.native "
            "JOIN acquisitions a ON a.id=p.source WHERE p.id=? AND p.resolved=1",
            (identifier,),
        )
        if not rows:
            raise ValueError("PSM has no resolved spectrum")
        psm = rows[0]
        if psm["mode"] != "DIA":
            raise ValueError("Fragment XICs require an acquisition marked DIA in project setup")
        mz = psm["precursor_mz"]
        if mz is None or not np.isfinite(mz) or mz <= 0:
            raise ValueError("The selected PSM has no peptide precursor m/z")
        lower, upper = psm["isolation_lower_mz"], psm["isolation_upper_mz"]
        if psm["level"] != 2 or lower is None or upper is None:
            raise ValueError("The selected spectrum has no usable MS2 isolation window")
        if lower > mz + self.window_tolerance or upper < mz - self.window_tolerance:
            raise ValueError("The peptide precursor lies outside the selected isolation window")
        return psm

    def scans(self, psm: dict[str, Any], start: float, stop: float) -> list[dict[str, Any]]:
        """Select one fixed window; reject ambiguous or incomplete window metadata.

        Check matching windows across the acquisition, including outside the current
        viewport, so zoom cannot hide an overlapping or staggered acquisition scheme.
        Unknown windows in the extraction interval must not silently lose measurements.
        """
        source, mz = psm["source"], psm["precursor_mz"]
        self.validate_window(psm)
        unknown = self.catalog.rows(
            "SELECT 1 FROM scans WHERE source=? AND level=2 AND rt BETWEEN ? AND ? "
            "AND (isolation_lower_mz IS NULL OR isolation_upper_mz IS NULL) LIMIT 1",
            (source, start, stop),
        )
        if unknown:
            raise ValueError("Some MS2 scans in this interval have unknown isolation windows")
        return self.catalog.rows(
            "SELECT ordinal, rt FROM scans WHERE source=? AND level=2 "
            "AND rt BETWEEN ? AND ? AND isolation_lower_mz<=? AND isolation_upper_mz>=? "
            "ORDER BY rt, ordinal",
            (
                source,
                start,
                stop,
                mz + self.window_tolerance,
                mz - self.window_tolerance,
            ),
        )

    def validate_window(self, psm: dict[str, Any]) -> None:
        """Reject distinct windows while allowing tiny differences in their stored bounds.

        Anchor both endpoints to the selected spectrum rather than grouping neighboring
        windows transitively. Use only an absolute tolerance, so larger precursor masses
        do not permit larger window differences. Preserve the original catalog values.
        """
        different = self.catalog.rows(
            "SELECT 1 FROM scans WHERE source=? AND level=2 "
            "AND isolation_lower_mz<=? AND isolation_upper_mz>=? "
            "AND (ABS(isolation_lower_mz-?)>? OR ABS(isolation_upper_mz-?)>?) LIMIT 1",
            (
                psm["source"],
                psm["precursor_mz"] + self.window_tolerance,
                psm["precursor_mz"] - self.window_tolerance,
                psm["isolation_lower_mz"],
                self.window_tolerance,
                psm["isolation_upper_mz"],
                self.window_tolerance,
            ),
        )
        if different:
            raise ValueError(
                "Fragment XICs currently require one fixed, non-overlapping DIA window"
            )

    def extract(
        self,
        request: FragmentXicRequest,
        psm: dict[str, Any],
        targets: list[dict[str, int | str | float]],
        reader: MzMLReader,
    ) -> dict[str, Any]:
        """Decode each eligible spectrum once and sum all theoretical target windows.

        Unrelated isolation windows contribute no points. An eligible scan without a
        matching fragment contributes zero. Returned intensities are always raw;
        relative display scaling belongs to the frontend and preserves these values.
        """
        scans = self.scans(psm, request.start, request.stop)
        masses = np.asarray([target["mz"] for target in targets], dtype=float)
        tolerances = masses * request.ppm / 1e6
        values: list[list[float]] = [[] for _ in targets]
        for scan in scans:
            spectrum = reader.spectrum(scan["ordinal"])
            for index, intensity in enumerate(
                self.target_intensities(spectrum, masses, tolerances)
            ):
                values[index].append(intensity)
        return {
            "psm_id": request.psm_id,
            "source": psm["source"],
            "precursor_mz": psm["precursor_mz"],
            "ppm": request.ppm,
            "start": request.start,
            "stop": request.stop,
            "scan_count": len(scans),
            "isolation_lower_mz": psm["isolation_lower_mz"],
            "isolation_upper_mz": psm["isolation_upper_mz"],
            "rt": [scan["rt"] for scan in scans],
            "fragments": [
                {
                    "label": target["label"],
                    "mz": target["mz"],
                    "charge": target["charge"],
                    "intensity": intensity,
                }
                for target, intensity in zip(targets, values)
            ],
        }

    @staticmethod
    def target_intensities(
        spectrum: oms.MSSpectrum,
        masses: np.ndarray,
        tolerances: np.ndarray,
    ) -> list[float]:
        """Sum each target's ppm interval from one spectrum, sorting only if necessary."""
        observed, intensities = spectrum.get_peaks()
        if np.any(np.diff(observed) < 0):
            order = np.argsort(observed)
            observed, intensities = observed[order], intensities[order]
        left = np.searchsorted(observed, masses - tolerances, side="left")
        right = np.searchsorted(observed, masses + tolerances, side="right")
        return [float(intensities[first:last].sum()) for first, last in zip(left, right)]
