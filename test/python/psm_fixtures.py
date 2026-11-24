"""Shared synthetic PSM metadata for API and browser regression checks."""

import json

from mzloupe.services.identifications import IdentificationImporter
from mzloupe.storage.catalog import ProjectCatalog


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
