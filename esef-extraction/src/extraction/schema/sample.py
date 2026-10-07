"""Contract of config/sample_candidates.yaml."""

from __future__ import annotations

import datetime as dt
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

Group = Literal["industriali_servizi", "utility", "banca", "assicurazione"]


class Candidate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    lei: str = Field(pattern=r"^[A-Z0-9]{18}[0-9]{2}$")
    issuer: str
    group: Group
    sector_proposed: str
    index_proposed: str
    star_proposed: bool
    rationale: str


class SampleConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["proposta", "approvata"]
    approved_by: str | None = None
    approved_on: dt.date | None = None
    fiscal_years: list[int]
    targets: dict[Group, tuple[int, int]]
    candidates: list[Candidate]

    @model_validator(mode="after")
    def _check(self) -> "SampleConfig":
        leis = [c.lei for c in self.candidates]
        dupes = sorted({lei for lei in leis if leis.count(lei) > 1})
        if dupes:
            raise ValueError(f"duplicate LEIs in candidates: {dupes}")
        if self.status == "approvata" and not (self.approved_by and self.approved_on):
            raise ValueError("an approved sample needs approved_by and approved_on")
        return self

    @property
    def is_approved(self) -> bool:
        return self.status == "approvata"


def load_sample_config(path: Path) -> SampleConfig:
    with path.open(encoding="utf-8") as fh:
        return SampleConfig.model_validate(yaml.safe_load(fh))
