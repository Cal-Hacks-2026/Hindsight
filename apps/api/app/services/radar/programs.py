"""Recurring campus programs from data/programs/<campus>.json (Opportunities feature).

These aren't one-off events, so no feed lists them: research programs, tutoring and
campus jobs, scholarships, student government, honors, study abroad. Each entry was
checked by hand against its official page; `window` is the typical timing that page
states (never a promised date) and `last_checked` is when it was read. They join the
scanned listings as candidates with type "program" and their own category label.
"""

import json
import os
from functools import lru_cache
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field, HttpUrl, model_validator

from app.services.radar.classify import is_label
from app.services.radar.extract import Modality

PROGRAMS_DIR = Path(
    os.getenv("PROGRAMS_DIR") or Path(__file__).resolve().parents[5] / "data" / "programs"
)
ID_PREFIX = "program:"


class Program(BaseModel):
    id: str
    title: str
    org: str
    category: str
    subcategory: str
    url: HttpUrl
    description: str
    window: str
    window_months: list[int] = Field(default_factory=list)  # 1–12; empty for rolling or unstated
    evidence: str = ""
    modality: Modality | None = None
    tags: list[str] = Field(default_factory=list)
    last_checked: str
    # Reviewed against the page, for programs whose written reasons overstated who they're for.
    reason: str = Field(default="", max_length=160)

    @model_validator(mode="after")
    def _check(self) -> "Program":
        if not is_label(self.category, self.subcategory):
            raise ValueError(f"{self.id}: unknown category {self.category}/{self.subcategory}")
        if any(not 1 <= m <= 12 for m in self.window_months):
            raise ValueError(f"{self.id}: window_months must be 1–12")
        return self


class ProgramsFile(BaseModel):
    campus: str
    last_checked: str
    programs: list[Program]


def load(campus: str, directory: Path | None = None) -> list[Program]:
    return _load(campus, directory or PROGRAMS_DIR)


@lru_cache(maxsize=8)
def _load(campus: str, directory: Path) -> list[Program]:
    path = directory / f"{campus}.json"
    if not path.is_file():
        return []
    return ProgramsFile.model_validate(json.loads(path.read_text())).programs


def is_program(opportunity_id: str) -> bool:
    return opportunity_id.startswith(ID_PREFIX)


def as_rows(campus: str, directory: Path | None = None) -> list[dict[str, Any]]:
    """Programs in the shape of an `opportunities` row, plus their label and window."""
    return [{
        "id": f"{ID_PREFIX}{p.id}", "campus": campus, "type": "program", "title": p.title, "org": p.org,
        "url": str(p.url), "description": p.description, "tags": p.tags,
        "starts_at": None, "ends_at": None, "deadline": None, "location": None, "modality": p.modality,
        "category": p.category, "subcategory": p.subcategory,
        "window": p.window, "window_months": p.window_months, "last_checked": p.last_checked,
        "reviewed_reason": p.reason or None,
    } for p in load(campus, directory)]
