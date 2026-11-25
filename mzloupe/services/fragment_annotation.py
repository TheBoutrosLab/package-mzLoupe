"""Generate theoretical peptide fragments and annotate measured spectrum peaks."""

from typing import Any

import numpy as np
import pyopenms as oms


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
