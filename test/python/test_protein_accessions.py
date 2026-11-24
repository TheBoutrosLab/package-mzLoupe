"""Protein evidence import and current API payloads."""

from pathlib import Path
import json
import time

from fastapi.testclient import TestClient
import pyopenms as oms

from mzloupe.app import create_app
from mzloupe.demo import DemoProject
from mzloupe.readers.idxml import IdXMLReader

ACCESSIONS = ["DECOY_sp|P12345|TEST", "contaminant_protein", "sp|P0CE47|EFTU1_ECOLI"]


def protein_project(directory: Path) -> Path:
    """Give first-ranked Search hits shared proteins and leave other hits unmapped."""
    manifest = DemoProject().write(directory)
    path = directory / "sample_Search.idXML"
    proteins, peptides = oms.IdXMLFile().load(str(path))
    protein_hits = []
    for accession in ACCESSIONS:
        protein = oms.ProteinHit()
        protein.setAccession(accession)
        protein_hits.append(protein)
    proteins[0].setHits(protein_hits)
    for peptide in peptides:
        hits = peptide.getHits()
        evidences = []
        # A duplicate evidence must not inflate the displayed protein count.
        for accession in [*reversed(ACCESSIONS), ACCESSIONS[0]]:
            evidence = oms.PeptideEvidence()
            evidence.setProteinAccession(accession)
            evidences.append(evidence)
        hits[0].setPeptideEvidences(evidences)
        peptide.setHits(hits)
    oms.IdXMLFile().store(str(path), proteins, oms.PeptideIdentificationList(peptides))
    return manifest


def ready(client: TestClient) -> str:
    """Wait for an in-process project's preparation without starting a server."""
    for _ in range(100):
        state = client.get("/api/status").json()
        if state["state"] != "preparing":
            break
        time.sleep(0.02)
    assert state["state"] == "ready", state
    return "/api/projects/" + state["token"]


def test_protein_evidence_reaches_all_psm_payloads(tmp_path: Path) -> None:
    """Deduplicate evidence and return original IDs in table, spectrum, and XIC."""
    manifest = protein_project(tmp_path / "data")
    records = list(IdXMLReader(manifest.parent / "sample_Search.idXML").records())
    assert records[0]["protein_accessions"] == ACCESSIONS
    assert records[1]["protein_accessions"] == []
    with TestClient(create_app(tmp_path / "cache", manifest)) as client:
        base = ready(client)
        rows = client.get(
            base + "/psms",
            params={"sample": "Synthetic sample", "filters": json.dumps({"layers": ["Search"]})},
        ).json()["rows"]
        assert all(row["protein_accessions"] == ACCESSIONS for row in rows if row["rank"] == 1)
        assert all(row["protein_accessions"] == [] for row in rows if row["rank"] == 2)
        spectrum = client.get(base + "/sources/fraction_01/spectra/79").json()
        search = [row for row in spectrum["candidates"] if row["layer"] == "Search"]
        assert search[0]["protein_accessions"] == ACCESSIONS
        trace = client.post(
            base + "/xic",
            json={"source": "fraction_01", "mz": 400.6873, "ppm": 10, "start": 210, "stop": 280},
        ).json()
        assert any(row["protein_accessions"] == ACCESSIONS for row in trace["psms"])
