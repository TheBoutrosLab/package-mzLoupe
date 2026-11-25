"""Create reproducible, explicitly synthetic data for local exploration."""

import json
from pathlib import Path
from typing import cast
from uuid import uuid4

import numpy as np
import pyopenms as oms

from mzloupe.readers.idxml import IdXMLWriter


class DemoProject:
    """Generate a small two-fraction project with repeatable signal and PSMs."""

    def write(self, directory: str | Path) -> Path:
        """Write synthetic mzML/idXML sources and return their project manifest."""
        directory = Path(directory)
        directory.mkdir(parents=True, exist_ok=True)
        acquisitions = []
        for fraction in (1, 2):
            stem = f"fraction_{fraction:02d}"
            path = directory / f"{stem}.mzML"
            self.write_acquisition(path, fraction)
            acquisitions.append(
                {
                    "id": stem,
                    "sample": "Synthetic sample",
                    "fraction": f"F{fraction:02d}",
                    "mzml": path.name,
                }
            )
        layers = []
        for label in ("Search", "Validated"):
            idpath = directory / f"sample_{label}.idXML"
            self.write_identifications(idpath, label, acquisitions)
            layers.append({"name": label, "path": idpath.name})
        manifest = directory / "project.json"
        project = {
            "id": str(uuid4()),
            "name": "Synthetic DDA demonstration",
            "samples": [{"name": "Synthetic sample", "identifications": layers}],
            "acquisitions": acquisitions,
        }
        manifest.write_text(json.dumps(project, indent=2))
        return manifest

    def write_acquisition(self, path: Path, fraction: int) -> None:
        """Write synthetic MS1 elution peaks and interleaved PEPTIDE MS2 scans."""
        experiment = oms.MSExperiment()
        generator = oms.TheoreticalSpectrumGenerator()
        fragments = oms.MSSpectrum()
        generator.getSpectrum(
            fragments,
            oms.AASequence.fromString("PEPTIDE"),
            1,
            1,
        )
        for scan in range(160):
            spectrum = oms.MSSpectrum()
            rt = scan * 3.0
            spectrum.setRT(rt)
            spectrum.setNativeID(f"scan={scan+1}")
            if scan % 4 == 3:
                spectrum.setMSLevel(2)
                precursor = oms.Precursor()
                precursor.setMZ(400.6873)
                precursor.setCharge(2)
                precursor.setIsolationWindowLowerOffset(0.7)
                precursor.setIsolationWindowUpperOffset(0.7)
                spectrum.setPrecursors([precursor])
                masses = np.array([peak.getMZ() for peak in fragments])
                intensity = np.linspace(2000, 18000, len(masses))
            else:
                spectrum.setMSLevel(1)
                masses = np.array([350.0, 400.6873, 401.1889, 450.0, 510.0, 600.0])
                centers = np.array(
                    [80.0, 230.0 + fraction * 12, 230.0 + fraction * 12, 350.0, 170.0, 420.0]
                )
                intensity = 100 + 100000 * np.exp(-0.5 * ((rt - centers) / 18) ** 2)
            spectrum.set_peaks((masses, intensity))
            experiment.addSpectrum(spectrum)
        oms.MzMLFile().store(str(path), experiment)

    def write_identifications(
        self,
        path: Path,
        label: str,
        acquisitions: list[dict[str, str]],
    ) -> None:
        """Write one sample-level idXML, preserving fraction order in merge indices."""
        protein = oms.ProteinIdentification()
        protein.setIdentifier("synthetic-demo")
        protein.setSearchEngine("Synthetic")
        protein.setPrimaryMSRunPath([item["mzml"] for item in acquisitions])
        records = oms.PeptideIdentificationList()
        for fraction_index, _ in enumerate(acquisitions):
            for ordinal in (75, 79, 83, 87, 91):
                identification = self.identification(ordinal, fraction_index, label)
                records.append(identification)
        writer = cast(IdXMLWriter, oms.IdXMLFile())
        writer.store(str(path), [protein], records)

    def identification(
        self,
        ordinal: int,
        fraction_index: int,
        label: str,
    ) -> oms.PeptideIdentification:
        """Create one scan's candidates, adding a lower-ranked hit for Search."""
        identification = oms.PeptideIdentification()
        identification.setIdentifier("synthetic-demo")
        identification.setScoreType("PEP")
        identification.setHigherScoreBetter(False)
        identification.setRT(ordinal * 3.0)
        identification.setMZ(400.6873)
        identification.setMetaValue("spectrum_reference", f"scan={ordinal + 1}")
        identification.setMetaValue("id_merge_index", fraction_index)
        candidates = [("PEPTIDE", 0.001)]
        if label == "Search":
            candidates.append(("PEPTIED", 0.1))
        hits = []
        for rank, (candidate, score) in enumerate(candidates, start=1):
            hit = oms.PeptideHit()
            hit.setSequence(oms.AASequence.fromString(candidate))
            hit.setCharge(2)
            hit.setRank(rank)
            hit.setScore(score)
            hits.append(hit)
        identification.setHits(hits)
        return identification
