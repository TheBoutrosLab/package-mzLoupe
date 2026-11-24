"""Validated filters and ordering for server-side PSM table queries."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class TextFilter(BaseModel):
    """Match a literal string, rather than interpreting SQL wildcard characters."""

    model_config = ConfigDict(extra="forbid")
    value: str = ""
    mode: Literal["contains", "exact"] = "contains"


class PsmFilters(BaseModel):
    """Combine column conditions with AND; selected values within a column use OR.

    RT inputs are minutes at the API boundary. Original catalog retention times
    remain in seconds. Score bounds retain the identification's numeric scale.
    """

    model_config = ConfigDict(extra="forbid")
    fractions: list[str] = Field(default_factory=list)
    layers: list[str] = Field(default_factory=list)
    sequence: TextFilter = Field(default_factory=TextFilter)
    native: TextFilter = Field(default_factory=TextFilter)
    proteins: TextFilter = Field(default_factory=TextFilter)
    precursor_mz_min: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    precursor_mz_max: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    rt_min: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    rt_max: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    score_min: float | None = Field(default=None, allow_inf_nan=False)
    score_max: float | None = Field(default=None, allow_inf_nan=False)
    score_type: str = ""
    link: Literal["", "resolved", "unresolved"] = ""

    @model_validator(mode="after")
    def validate_ranges(self) -> "PsmFilters":
        """Reject reversed ranges without silently changing the user's bounds."""
        for name, label in (("rt", "RT"), ("score", "Score"), ("precursor_mz", "Precursor m/z")):
            lower = getattr(self, name + "_min")
            upper = getattr(self, name + "_max")
            if lower is not None and upper is not None and lower > upper:
                raise ValueError(f"{label} minimum must not exceed maximum")
        return self


class PsmQuery(BaseModel):
    """Describe one result page, with explicitly allowed sort columns."""

    model_config = ConfigDict(extra="forbid")

    sample: str
    source: str | None = None
    filters: PsmFilters = Field(default_factory=PsmFilters)
    grouping: str = ""
    sort_by: Literal[
        "",
        "fraction",
        "sequence",
        "proteins",
        "native",
        "precursor_mz",
        "rt",
        "layer",
        "score",
        "resolved",
    ] = ""
    sort_direction: Literal["asc", "desc"] = "asc"
    page: int = Field(default=0, ge=0)
    page_size: int = Field(default=50, ge=10, le=200)
