"""Regression checks for a sample idXML spanning multiple fractions."""

from pathlib import Path
import json
import time

from fastapi.testclient import TestClient
import pyopenms as oms
import pytest

from mzloupe.app import create_app
from mzloupe.demo import DemoProject
from mzloupe.readers.idxml import IdXMLReader


class SampleProject:
    """Create a two-fraction project and edit its native identification objects."""

    def __init__(self, directory: Path) -> None:
        """Generate source files and remember the search-layer identification path."""
        self.manifest = DemoProject().write(directory)
        self.idxml = directory / "sample_Search.idXML"

    def edit_hints(self, key: str | None) -> None:
        """Replace merge indices with filename hints, or remove source hints."""
        proteins, peptides = oms.IdXMLFile().load(str(self.idxml))
        for index, peptide in enumerate(peptides):
            peptide.removeMetaValue("id_merge_index")
            if key is not None:
                peptide.setMetaValue(
                    key,
                    f"file:///old/location/fraction_{index // 5 + 1:02d}.mzML",
                )
            peptides[index] = peptide
        oms.IdXMLFile().store(str(self.idxml), proteins, oms.PeptideIdentificationList(peptides))

    def ready(self, client: TestClient) -> str:
        """Wait for preparation and return the prepared project API prefix."""
        for _ in range(100):
            state = client.get("/api/status").json()
            if state["state"] != "preparing":
                break
            time.sleep(0.05)
        assert state["state"] == "ready", state
        return "/api/projects/" + state["token"]


def test_sample_file_is_imported_once(tmp_path: Path) -> None:
    """Import a shared idXML once and resolve repeated scan IDs by source."""
    sample = SampleProject(tmp_path / "data")
    with TestClient(create_app(tmp_path / "cache", sample.manifest)) as client:
        base = sample.ready(client)
        results = client.get(
            base + "/psms",
            params={"sample": "Synthetic sample", "filters": json.dumps({"layers": ["Search"]})},
        ).json()
        assert results["total"] == 20
        assert {row["source"] for row in results["rows"]} == {"fraction_01", "fraction_02"}
        assert {row["source_path"] for row in results["rows"]} == {str(sample.idxml)}
        scans = [row for row in results["rows"] if row["native"] == "scan=80" and row["rank"] == 1]
        assert len(scans) == 2
        for row in scans:
            spectrum = client.get(
                base + f'/sources/{row["source"]}/spectra/{row["ordinal"]}'
            ).json()
            assert spectrum["source"] == row["source"]
            assert len(spectrum["candidates"]) == 3


@pytest.mark.parametrize(
    "key",
    ["base_name", "file_origin"],
)
def test_sample_provenance_selects_fraction(tmp_path: Path, key: str | None) -> None:
    """Resolve each fraction using its identification-level filename hint."""
    sample = SampleProject(tmp_path / "data")
    sample.edit_hints(key)
    with TestClient(create_app(tmp_path / "cache", sample.manifest)) as client:
        base = sample.ready(client)
        results = client.get(
            base + "/psms",
            params={"sample": "Synthetic sample", "filters": json.dumps({"layers": ["Search"]})},
        ).json()
        assert results["total"] == 20
        assert all(row["resolved"] for row in results["rows"])
        assert [row["source"] for row in results["rows"]].count("fraction_01") == 10


def test_ambiguous_sample_psms_remain_visible(tmp_path: Path) -> None:
    """Retain ambiguous candidates without guessing their acquisition."""
    sample = SampleProject(tmp_path / "data")
    sample.edit_hints(None)
    with TestClient(create_app(tmp_path / "cache", sample.manifest)) as client:
        base = sample.ready(client)
        results = client.get(
            base + "/psms",
            params={"sample": "Synthetic sample", "filters": json.dumps({"layers": ["Search"]})},
        ).json()
        assert results["total"] == 20
        assert all(row["source"] is None and row["fraction"] is None for row in results["rows"])
        assert all("multiple fractions" in row["link_reason"] for row in results["rows"])
        assert client.get(base + f'/psms/{results["rows"][0]["id"]}/annotations').status_code == 400
        counts = client.get(
            base,
            params={"layer": "Search"},
        ).json()["acquisitions"]
        assert all(row["identified"] == 0 for row in counts)


def test_conflicting_provenance_stays_unresolved(tmp_path: Path) -> None:
    """Leave candidates unresolved when run and peptide source hints conflict."""
    sample = SampleProject(tmp_path / "data")
    proteins, peptides = oms.IdXMLFile().load(str(sample.idxml))
    first = peptides[0]
    first.setMetaValue("base_name", "fraction_02.mzML")
    peptides[0] = first
    oms.IdXMLFile().store(str(sample.idxml), proteins, oms.PeptideIdentificationList(peptides))
    with TestClient(create_app(tmp_path / "cache", sample.manifest)) as client:
        base = sample.ready(client)
        rows = client.get(
            base + "/psms",
            params={"sample": "Synthetic sample", "filters": json.dumps({"layers": ["Search"]})},
        ).json()["rows"]
        unresolved = [row for row in rows if not row["resolved"]]
        assert len(unresolved) == 2
        assert all(row["source"] is None for row in unresolved)
        assert all("metadata" in row["link_reason"] for row in unresolved)
        assert sum(row["resolved"] for row in rows) == 18


def test_identification_runs_keep_their_own_source_order(tmp_path: Path) -> None:
    """Match each peptide to its own run before interpreting a merge index."""
    sample = SampleProject(tmp_path / "data")
    original_proteins, original_peptides = oms.IdXMLFile().load(str(sample.idxml))
    proteins = []
    peptides = oms.PeptideIdentificationList()

    # Both runs reference the same native scan and merge index. Only the
    # run-specific source ordering distinguishes their intended fractions.
    for index, source_paths in enumerate(
        [
            ["fraction_02.mzML", "fraction_01.mzML"],
            ["fraction_01.mzML", "fraction_02.mzML"],
        ]
    ):
        identifier = f"run-{index}"
        protein = oms.ProteinIdentification(original_proteins[0])
        protein.setIdentifier(identifier)
        protein.setSearchEngine(f"engine-{index}")
        protein.setPrimaryMSRunPath(source_paths)
        proteins.append(protein)

        peptide = oms.PeptideIdentification(original_peptides[1])
        peptide.setIdentifier(identifier)
        peptide.setMetaValue("id_merge_index", 0)
        hits = peptide.getHits()
        if index == 0:
            hits[0].setMetaValue("file_origin", "fraction_02.mzML")
        else:
            # Identification-level metadata takes precedence over a hit hint.
            peptide.setMetaValue("base_name", "fraction_01.mzML")
            hits[0].setMetaValue("base_name", "fraction_02.mzML")
            peptide.setScoreType("hyperscore")
            peptide.setHigherScoreBetter(True)
        peptide.setHits(hits)
        peptides.append(peptide)

    oms.IdXMLFile().store(str(sample.idxml), proteins, peptides)
    records = list(IdXMLReader(sample.idxml).records())
    assert len(records) == 4
    pep_records = [row for row in records if row["score_type"] == "PEP"]
    hyper_records = [row for row in records if row["score_type"] == "hyperscore"]
    assert len(pep_records) == len(hyper_records) == 2
    assert all(row["spectra_data"][0] == "fraction_02.mzML" for row in pep_records)
    assert all(row["spectra_data"][0] == "fraction_01.mzML" for row in hyper_records)
    assert all(row["id_merge_index"] == "0" for row in records)
    assert all(row["higher_better"] for row in hyper_records)
    assert all(row["base_name"] == "fraction_01.mzML" for row in hyper_records)
    assert any(row["file_origin"] == "fraction_02.mzML" for row in pep_records)

    with TestClient(create_app(tmp_path / "cache", sample.manifest)) as client:
        base = sample.ready(client)
        result = client.get(
            base + "/psms",
            params={"sample": "Synthetic sample", "filters": json.dumps({"layers": ["Search"]})},
        ).json()
        assert result["total"] == 4
        assert all(row["resolved"] for row in result["rows"])
        for row in result["rows"]:
            expected = "fraction_02" if row["score_type"] == "PEP" else "fraction_01"
            assert row["source"] == expected


def test_fraction_identification_fields_are_rejected() -> None:
    """Reject obsolete fraction-level idXML fields instead of silently dropping them."""
    from mzloupe.models import ProjectInput

    with pytest.raises(ValueError, match="identifications"):
        ProjectInput.model_validate(
            {
                "name": "Invalid associations",
                "acquisitions": [
                    {
                        "id": "f01",
                        "sample": "Sample",
                        "fraction": "F01",
                        "mzml": "run.mzML",
                        "identifications": [{"name": "Search", "path": "search.idXML"}],
                    }
                ],
            }
        )
