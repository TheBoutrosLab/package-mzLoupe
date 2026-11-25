"""Project inputs and shared scientific values."""

from __future__ import annotations

from pathlib import Path
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator


class IdentificationInput(BaseModel):
    """Associate a named identification layer with its idXML source file."""

    name: str = Field(min_length=1)
    path: str = Field(min_length=1)


class AcquisitionInput(BaseModel):
    """Describe one sample fraction's mzML and source filename aliases."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(pattern=r"^[A-Za-z0-9_-]+$")
    sample: str = Field(min_length=1)
    fraction: str = Field(min_length=1)
    mzml: str
    aliases: list[str] = Field(default_factory=list)


class SampleInput(BaseModel):
    """Associate sample-level idXML layers with all of that sample's fractions."""

    name: str = Field(min_length=1)
    identifications: list[IdentificationInput] = Field(default_factory=list)


class ProteinGroupingInput(BaseModel):
    """Select an inference collection and the identification layers it describes.

    Empty sample or layer lists mean all registered samples or layers. The file
    stays independent of sample-level PSM inputs and can describe an entire cohort.
    """

    name: str = Field(min_length=1)
    path: str = Field(min_length=1)
    collection: Literal["protein_groups", "indistinguishable_proteins"]
    samples: list[str] = Field(default_factory=list)
    layers: list[str] = Field(default_factory=list)


class ProjectInput(BaseModel):
    """Validate a project manifest and resolve its local source-file associations."""

    id: str = Field(default_factory=lambda: str(uuid4()), pattern=r"^[a-f0-9-]{36}$")
    name: str = Field(min_length=1)
    acquisitions: list[AcquisitionInput] = Field(default_factory=list)
    samples: list[SampleInput] = Field(default_factory=list)

    protein_groupings: list[ProteinGroupingInput] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_ids(self) -> ProjectInput:
        """Reject duplicate fractions, IDs, and conflicting layer associations."""
        ids = [item.id for item in self.acquisitions]
        if len(ids) != len(set(ids)):
            raise ValueError("Acquisition IDs must be unique")
        fractions = [(item.sample, item.fraction) for item in self.acquisitions]
        if len(fractions) != len(set(fractions)):
            raise ValueError("Each sample/fraction pair must be unique")
        names = [sample.name for sample in self.samples]
        if len(names) != len(set(names)):
            raise ValueError("Sample names must be unique")
        acquisition_samples = {item.sample for item in self.acquisitions}
        for sample in self.samples:
            if sample.name not in acquisition_samples:
                raise ValueError(f"Sample has no acquisitions: {sample.name}")
            layers = [layer.name for layer in sample.identifications]
            if len(layers) != len(set(layers)):
                raise ValueError(f"Identification layer names must be unique in {sample.name}")
        self.validate_groupings()
        return self

    def validate_groupings(self) -> None:
        """Check unique inference names and sample/layer scope references."""
        acquisition_samples = {item.sample for item in self.acquisitions}
        grouping_names = [grouping.name for grouping in self.protein_groupings]
        if len(grouping_names) != len(set(grouping_names)):
            raise ValueError("Protein grouping names must be unique")
        associations = self.identification_sources()
        for grouping in self.protein_groupings:
            if set(grouping.samples) - acquisition_samples:
                raise ValueError(f"Unknown sample in protein grouping: {grouping.name}")
            applicable_layers = {
                layer
                for sample, layer, _ in associations
                if not grouping.samples or sample in grouping.samples
            }
            if set(grouping.layers) - applicable_layers:
                raise ValueError(
                    f"Unknown identification layer in protein grouping: {grouping.name}"
                )

    @classmethod
    def load(cls, path: Path, validate_files: bool = True) -> ProjectInput:
        """Read a JSON manifest and resolve paths relative to its directory."""
        project = cls.model_validate_json(path.read_text())
        return project.resolve_paths(path.parent, validate_files=validate_files)

    def resolve_paths(self, directory: Path, validate_files: bool = True) -> ProjectInput:
        """Normalize source paths in place and optionally reject missing files."""
        for acquisition in self.acquisitions:
            acquisition.mzml = str((directory / Path(acquisition.mzml).expanduser()).resolve())
        for sample in self.samples:
            for layer in sample.identifications:
                layer.path = str((directory / Path(layer.path).expanduser()).resolve())
        for grouping in self.protein_groupings:
            grouping.path = str((directory / Path(grouping.path).expanduser()).resolve())
        issues = self.file_issues()
        if validate_files and issues:
            raise ValueError(issues[0]["message"])
        return self

    def file_issues(self) -> list[dict[str, str]]:
        """List missing sources with the sample or acquisition needed to edit them."""
        issues = []
        for acquisition in self.acquisitions:
            if not Path(acquisition.mzml).expanduser().is_file():
                issues.append(
                    {
                        "kind": "acquisition",
                        "id": acquisition.id,
                        "field": "mzml",
                        "message": f"File does not exist: {acquisition.mzml}",
                    }
                )
        for sample in self.samples:
            for layer in sample.identifications:
                if not Path(layer.path).expanduser().is_file():
                    issues.append(
                        {
                            "kind": "identification",
                            "sample": sample.name,
                            "layer": layer.name,
                            "field": "path",
                            "message": f"File does not exist: {layer.path}",
                        }
                    )
        for grouping in self.protein_groupings:
            if not Path(grouping.path).expanduser().is_file():
                issues.append(
                    {
                        "kind": "protein_grouping",
                        "grouping": grouping.name,
                        "field": "path",
                        "message": f"File does not exist: {grouping.path}",
                    }
                )
        return issues

    def identification_sources(self) -> dict[tuple[str, str, str], set[str]]:
        """Associate each sample-level identification source with its acquisitions."""
        sources = {}
        for sample in self.samples:
            for layer in sample.identifications:
                ids = {item.id for item in self.acquisitions if item.sample == sample.name}
                sources[(sample.name, layer.name, layer.path)] = ids
        return sources


class MapTargetRequest(BaseModel):
    """Bound a heatmap selection by acquisition, retention seconds, and MS1 m/z."""

    source: str
    start: float = Field(ge=0, allow_inf_nan=False)
    stop: float = Field(gt=0, allow_inf_nan=False)
    mz_start: float = Field(gt=0, allow_inf_nan=False)
    mz_stop: float = Field(gt=0, allow_inf_nan=False)

    @model_validator(mode="after")
    def validate_bounds(self) -> MapTargetRequest:
        """Reject empty or reversed retention-time and m/z windows."""
        if self.stop <= self.start or self.mz_stop <= self.mz_start:
            raise ValueError("Map selection bounds must increase")
        return self


class XicRequest(BaseModel):
    """Specify an MS1 target m/z, ppm tolerance, and retention interval in seconds."""

    source: str
    mz: float = Field(gt=0, allow_inf_nan=False)
    ppm: float = Field(default=10, gt=0, le=1000, allow_inf_nan=False)
    start: float = Field(ge=0, allow_inf_nan=False)
    stop: float = Field(gt=0, allow_inf_nan=False)

    @model_validator(mode="after")
    def validate_bounds(self) -> XicRequest:
        """Require the extraction interval to end after it starts."""
        if self.stop <= self.start:
            raise ValueError("Stop must be greater than start")
        return self
