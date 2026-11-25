"""Create conventional DIA cycles with known fragment chromatograms for tests."""

from pathlib import Path

import numpy as np
import pyopenms as oms

from mzloupe.demo import DemoProject
from mzloupe.models import ProjectInput


def write_dia_project(directory: Path) -> Path:
    """Interleave two isolation windows with identical masses but distinct intensities.

    The selected scan=80 belongs to 390–410 m/z. The neighboring 415–435
    window has much stronger interference at exactly the same fragment masses.
    scan=88 is acquired in the selected window but deliberately contains no peaks.
    """
    manifest = DemoProject().write(directory)
    project = ProjectInput.load(manifest)
    for acquisition in project.acquisitions:
        acquisition.mode = "DIA" if acquisition.fraction == "F01" else "DDA"
        experiment = oms.MSExperiment()
        oms.MzMLFile().load(acquisition.mzml, experiment)
        for ordinal in range(experiment.size()):
            spectrum = experiment[ordinal]
            if spectrum.getMSLevel() != 2:
                continue
            selected = ordinal % 8 == 7
            precursor = spectrum.getPrecursors()[0]
            precursor.setMZ(400 if selected else 425)
            precursor.setIsolationWindowLowerOffset(10)
            precursor.setIsolationWindowUpperOffset(10)
            spectrum.setPrecursors([precursor])
            masses, intensity = spectrum.get_peaks()
            envelope = np.exp(-0.5 * ((spectrum.getRT() - 242) / 18) ** 2)
            intensity = intensity * envelope if selected else np.full(len(masses), 1e8)
            # Measured peaks differ slightly from theoretical masses, as real data do.
            spectrum.set_peaks((masses * (1 + 5e-6), intensity))
            if ordinal == 87:
                spectrum.set_peaks((np.array([], dtype=float), np.array([], dtype=float)))
            experiment[ordinal] = spectrum
        oms.MzMLFile().store(acquisition.mzml, experiment)
    manifest.write_text(project.model_dump_json(indent=2))
    return manifest
