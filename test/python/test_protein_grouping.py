"""Native inference collections, scoped assignments, and raw-cache reuse."""

from pathlib import Path
import json
from typing import Any
import time

from fastapi.testclient import TestClient
from pydantic import ValidationError
import pyopenms as oms
import pytest

from mzloupe.app import create_app
from mzloupe.demo import DemoProject
from mzloupe.models import ProjectInput
from mzloupe.readers.mzml import MzMLReader
from mzloupe.readers.protein_grouping import ProteinGroupingFile
from mzloupe.services.preparation import ProjectPreparer


def ready(client: TestClient) -> str:
    """Return the active API prefix after in-process project preparation."""
    for _ in range(100):
        state = client.get("/api/status").json()
        if state["state"] != "preparing":
            break
        time.sleep(0.02)
    assert state["state"] == "ready", state
    return "/api/projects/" + state["token"]


def fixture_project(directory: Path, explicit: bool = False) -> tuple[Path, Path]:
    """Create distinct parent/subgroups and PSM links that expose ambiguous joins."""
    manifest = DemoProject().write(directory)
    path = directory / "sample_Search.idXML"
    proteins, peptides = oms.IdXMLFile().load(str(path))
    protein_hits = []
    for accession in ("A", "B", "C", "D"):
        hit = oms.ProteinHit()
        hit.setAccession(accession)
        protein_hits.append(hit)
    proteins[0].setHits(protein_hits)
    for index, peptide in enumerate(peptides):
        hits = peptide.getHits()
        for rank, hit in enumerate(hits):
            # Same native IDs occur in both fractions. First-ranked candidates
            # share the same sequence; their evidence can still differ by scan.
            accessions = [] if rank else (["A", "C"] if index == 1 else ["A"])
            hit.setPeptideEvidences(evidences(accessions))
        peptide.setHits(hits)
    oms.IdXMLFile().store(str(path), proteins, oms.PeptideIdentificationList(peptides))
    run = oms.ProteinIdentification(proteins[0])
    run.setSearchEngine("ProteinProphet")
    run.setScoreType("ProteinProphet probability")
    parent = oms.ProteinGroup()
    parent.accessions = ["C", "D", "A", "B"]
    parent.probability = 0.99
    run.insertProteinGroup(parent)
    for members in (["A", "B"], ["C", "D"]):
        group = oms.ProteinGroup()
        group.accessions = members
        group.probability = 0.0
        run.insertIndistinguishableProteins(group)
    grouping_path = directory / "inference.idXML"
    inference = oms.PeptideIdentificationList()
    if explicit:
        for index in (0, 5):
            peptide = oms.PeptideIdentification(peptides[index])
            hit = peptide.getHits()[0]
            hit.setPeptideEvidences(evidences(["C"] if index == 0 else ["A"]))
            peptide.setHits([hit])
            inference.append(peptide)
    oms.IdXMLFile().store(str(grouping_path), [run], inference)
    return manifest, grouping_path


def evidences(accessions: list[str]) -> list[oms.PeptideEvidence]:
    """Construct native peptide mappings in their requested order."""
    result = []
    for accession in accessions:
        evidence = oms.PeptideEvidence()
        evidence.setProteinAccession(accession)
        result.append(evidence)
    return result


def configuration(manifest: Path, path: Path, collection: str) -> dict[str, Any]:
    """Associate a cohort grouping with only the Search identification layer."""
    project = ProjectInput.load(manifest).model_dump()
    project["protein_groupings"] = [
        {
            "name": "Inference",
            "path": str(path),
            "collection": collection,
            "samples": ["Synthetic sample"],
            "layers": ["Search"],
        }
    ]
    return project


def table(client: TestClient, base: str) -> list[dict]:
    """Read both fractions so repeated scan IDs participate in regression checks."""
    return client.get(base + "/psms", params={"sample": "Synthetic sample"}).json()["rows"]


def test_collection_selection_changes_groups_without_repreparing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Honor source ordering, scope, ambiguity, and metadata-only collection changes."""
    manifest, path = fixture_project(tmp_path / "data")
    app = create_app(tmp_path / "cache", manifest)
    with TestClient(app) as client:
        ready(client)
        workspace = app.state.runtime.active[2]
        maps = {item.name: item.read_bytes() for item in workspace.glob("*.npz")}

        def reject_raw(*_args, **_kwargs):
            """Changing a grouping input must never reprepare or reopen mzML."""
            pytest.fail("Grouping changes accessed raw mzML")

        monkeypatch.setattr(ProjectPreparer, "prepare", reject_raw)
        monkeypatch.setattr(MzMLReader, "__init__", reject_raw)
        initial_ids = [row["id"] for row in table(client, ready(client))]
        first = configuration(manifest, path, "protein_groups")
        response = client.post("/api/open-configuration", json=first)
        assert response.status_code == 202
        parent_base = ready(client)
        assert app.state.runtime.active[2] == workspace
        rows = table(client, parent_base)
        assert [row["id"] for row in rows] == initial_ids
        parent = next(row for row in rows if row["layer"] == "Search" and row["rank"] == 1)
        annotation = parent["protein_groupings"][0]
        assert annotation["groups"][0]["members"] == ["C", "D", "A", "B"]
        assert annotation["groups"][0]["probability"] == 0.99
        assert annotation["status"] == "assigned"
        assert annotation["basis"] == "accession_overlap"
        assert parent["protein_accessions"] == ["A"]
        assert all(row["protein_groupings"] == [] for row in rows if row["layer"] == "Validated")

        second = configuration(manifest, path, "indistinguishable_proteins")
        assert client.post("/api/open-configuration", json=second).status_code == 202
        subgroup_base = ready(client)
        assert subgroup_base != parent_base
        assert (
            client.get(parent_base + "/psms", params={"sample": "Synthetic sample"}).status_code
            == 400
        )
        rows = table(client, subgroup_base)
        shared = next(row for row in rows if row["protein_accessions"] == ["A", "C"])
        annotation = shared["protein_groupings"][0]
        assert annotation["status"] == "ambiguous"
        assert [group["members"] for group in annotation["groups"]] == [["A", "B"], ["C", "D"]]
        assert all(
            group["probability"] is None and group["stored_probability"] == 0
            for group in annotation["groups"]
        )
        unmapped = next(row for row in rows if row["layer"] == "Search" and row["rank"] == 2)
        assert unmapped["protein_groupings"][0]["status"] == "unassigned"
        assert maps == {item.name: item.read_bytes() for item in workspace.glob("*.npz")}


def test_inference_evidence_overrides_search_links_without_crossing_fractions(
    tmp_path: Path,
) -> None:
    """Use inference peptide mappings and retain missing assignments as missing."""
    manifest, path = fixture_project(tmp_path / "data", explicit=True)
    with TestClient(create_app(tmp_path / "cache")) as client:
        project = configuration(manifest, path, "indistinguishable_proteins")
        assert client.post("/api/open-configuration", json=project).status_code == 202
        base = ready(client)
        rows = table(client, base)
        selected = [
            row
            for row in rows
            if row["native"] == "scan=76" and row["rank"] == 1 and row["layer"] == "Search"
        ]
        assert len(selected) == 2
        for row in selected:
            group = row["protein_groupings"][0]
            expected = "C" if row["source"] == "fraction_01" else "A"
            assert group["groups"][0]["members"][0] == expected
            assert group["inferred_accessions"] == [expected]
            assert group["basis"] == "spectrum"
            assert row["protein_accessions"] == ["A"]
            spectrum = client.get(
                base + f'/sources/{row["source"]}/spectra/{row["ordinal"]}'
            ).json()
            candidate = next(item for item in spectrum["candidates"] if item["id"] == row["id"])
            assert candidate["protein_groupings"] == row["protein_groupings"]
        absent = next(
            row for row in rows if row["native"] == "scan=80" and row["layer"] == "Search"
        )
        assert absent["protein_groupings"][0]["status"] == "unassigned"
        xic = client.post(
            base + "/xic",
            json={
                "source": "fraction_01",
                "mz": 400.6873,
                "start": 210,
                "stop": 280,
            },
        ).json()
        assert any(row["protein_groupings"] for row in xic["psms"])


def test_peptide_only_inference_preserves_ambiguity(tmp_path: Path) -> None:
    """ProtXML-style peptide evidence can map one sequence to multiple groups."""
    manifest, path = fixture_project(tmp_path / "data", explicit=True)
    proteins, peptides = oms.IdXMLFile().load(str(path))
    for peptide in peptides:
        peptide.removeMetaValue("spectrum_reference")
    oms.IdXMLFile().store(str(path), proteins, oms.PeptideIdentificationList(peptides))
    with TestClient(create_app(tmp_path / "cache")) as client:
        client.post(
            "/api/open-configuration",
            json=configuration(manifest, path, "indistinguishable_proteins"),
        )
        rows = table(client, ready(client))
        row = next(item for item in rows if item["layer"] == "Search" and item["rank"] == 1)
        assert row["protein_groupings"][0]["basis"] == "peptide"
        assert row["protein_groupings"][0]["status"] == "ambiguous"


def test_inspection_counts_and_manifest_round_trip(tmp_path: Path) -> None:
    """Inspect both collections and preserve grouping scope through server JSON saving."""
    manifest, path = fixture_project(tmp_path / "data")
    with TestClient(create_app(tmp_path / "cache")) as client:
        assert client.post("/api/protein-groupings/inspect", json={"path": str(path)}).json() == {
            "protein_groups": 1,
            "indistinguishable_proteins": 2,
        }
        project = configuration(manifest, path, "protein_groups")
        result = client.post(
            "/api/save-project",
            json={
                "directory": str(tmp_path),
                "filename": "saved.json",
                "project": project,
            },
        )
        assert result.status_code == 200
        saved = ProjectInput.load(tmp_path / "saved.json")
        assert saved.protein_groupings[0].path == str(path)
        assert saved.model_dump()["protein_groupings"] == project["protein_groupings"]
        result = client.post(
            "/api/protein-groupings/inspect", json={"path": str(tmp_path / "missing.idXML")}
        )
        assert result.status_code == 400
    project["protein_groupings"][0]["samples"] = ["Unknown sample"]
    with pytest.raises(ValidationError, match="Unknown sample"):
        ProjectInput.model_validate(project)


def test_unresolved_inference_scan_does_not_choose_a_fraction(tmp_path: Path) -> None:
    """Repeated native IDs without provenance remain ambiguous in both fractions."""
    manifest, path = fixture_project(tmp_path / "data", explicit=True)
    proteins, peptides = oms.IdXMLFile().load(str(path))
    proteins[0].setPrimaryMSRunPath([])
    for peptide in peptides:
        peptide.removeMetaValue("id_merge_index")
    oms.IdXMLFile().store(str(path), proteins, oms.PeptideIdentificationList(peptides))
    with TestClient(create_app(tmp_path / "cache")) as client:
        project = configuration(manifest, path, "indistinguishable_proteins")
        client.post("/api/open-configuration", json=project)
        rows = table(client, ready(client))
        selected = [
            row
            for row in rows
            if row["native"] == "scan=76" and row["rank"] == 1 and row["layer"] == "Search"
        ]
        assert len(selected) == 2
        for row in selected:
            assignment = row["protein_groupings"][0]
            assert assignment["status"] == "ambiguous"
            assert assignment["groups"] == []


def test_multiple_views_share_one_native_load(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Selecting both collections reads the inference file once per activation."""
    manifest, path = fixture_project(tmp_path / "data")
    original = ProteinGroupingFile.__init__
    opened = []

    def counted_load(reader: ProteinGroupingFile, filename: str | Path) -> None:
        """Count full native loads independently of collection-specific indexes."""
        opened.append(str(filename))
        original(reader, filename)

    monkeypatch.setattr(ProteinGroupingFile, "__init__", counted_load)
    project = configuration(manifest, path, "protein_groups")
    other = {
        **project["protein_groupings"][0],
        "name": "Subgroups",
        "collection": "indistinguishable_proteins",
    }
    project["protein_groupings"].append(other)
    with TestClient(create_app(tmp_path / "cache")) as client:
        client.post("/api/open-configuration", json=project)
        base = ready(client)
        rows = table(client, base)
        assert len(next(row for row in rows if row["layer"] == "Search")["protein_groupings"]) == 2
        assert opened == [str(path)]


def test_group_members_filter_before_pagination(tmp_path: Path) -> None:
    """Search the selected collection's hidden members, not original accession labels."""
    manifest, path = fixture_project(tmp_path / "data")
    project = configuration(manifest, path, "protein_groups")
    project["protein_groupings"].append(
        {
            **project["protein_groupings"][0],
            "name": "Subgroups",
            "collection": "indistinguishable_proteins",
        }
    )
    with TestClient(create_app(tmp_path / "cache")) as client:
        client.post("/api/open-configuration", json=project)
        base = ready(client)
        parameters = {
            "sample": "Synthetic sample",
            "filters": json.dumps({"proteins": {"value": "D", "mode": "exact"}}),
            "grouping": "Inference",
            "sort_by": "proteins",
        }
        parents = client.get(base + "/psms", params=parameters).json()
        assert parents["total"] == 10
        assert all("D" not in row["protein_accessions"] for row in parents["rows"])
        parameters["grouping"] = "Subgroups"
        subgroups = client.get(base + "/psms", params=parameters).json()
        assert subgroups["total"] == 1
        assert subgroups["rows"][0]["protein_groupings"][1]["status"] == "ambiguous"
        index = client.app.state.runtime.search.protein_indexes["Subgroups"]
        assert index.values[subgroups["rows"][0]["id"]].label == "a (+1); c (+1)"

        parameters["grouping"] = ""
        assert client.get(base + "/psms", params=parameters).json()["total"] == 0
        assert set(client.app.state.runtime.search.protein_indexes) == {
            "Inference",
            "Subgroups",
            "",
        }
