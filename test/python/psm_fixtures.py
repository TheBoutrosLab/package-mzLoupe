"""Prepare synthetic projects and PSM metadata for API and browser regression checks."""

import json
from time import monotonic, sleep

from fastapi.testclient import TestClient

from mzloupe.services.identifications import IdentificationImporter
from mzloupe.storage.catalog import ProjectCatalog


def wait_for_project(client: TestClient, timeout_seconds: float = 30.0) -> None:
    """Wait for background preparation, reporting real failures or a bounded timeout."""
    deadline = monotonic() + timeout_seconds
    while True:
        response = client.get("/api/status")
        response.raise_for_status()
        status = response.json()
        if status["state"] == "ready":
            return
        if status["state"] != "preparing":
            raise RuntimeError(f"Test project preparation failed: {status}")
        remaining = deadline - monotonic()
        if remaining <= 0:
            raise TimeoutError(
                f"Test project was not ready after {timeout_seconds:g} seconds: {status}"
            )
        sleep(min(0.05, remaining))


def seed_psm_rows(catalog: ProjectCatalog) -> None:
    """Add candidates beyond one page with hidden accessions and controlled scores."""
    row = catalog.rows("SELECT * FROM psms WHERE layer='Search' ORDER BY id LIMIT 1")[0]
    with catalog.connect() as connection:
        for index in range(130):
            candidate = {
                **row,
                "source": "fraction_02" if index % 3 == 0 else "fraction_01",
                "sequence": "PEPTIDE" if index % 2 == 0 else "PEPTIED",
                "peptide": "PEPTIDE" if index % 2 == 0 else "PEPTIED",
                "score": index / 1000,
                "score_type": "hyperscore" if index % 5 == 0 else "PEP",
                "higher_better": int(index % 5 == 0),
                "protein_accessions": json.dumps(
                    ["sp|P0CE47|EFTU1_ECOLI", f"zz_hidden_{index:03d}"]
                ),
            }
            connection.execute(IdentificationImporter.insert_psm_sql, candidate)
        connection.execute(
            IdentificationImporter.insert_psm_sql,
            {
                **row,
                "source": None,
                "native": "scan=literal_%\\id",
                "resolved": 0,
                "link_reason": "Missing reference",
                "score": 0.42,
                "protein_accessions": "[]",
            },
        )
