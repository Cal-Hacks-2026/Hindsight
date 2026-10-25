"""Recurring campus programs: the file a campus's registry entry names (data/campuses/<id>.json →
opportunities.programs) (Opportunities feature).

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

from app.services import campuses
from app.services.radar.classify import is_label
from app.services.radar.extract import Modality

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
    # Why it's listed, checked against the page and the same for every student. Programs never
    # get a per-profile reason from Claude: those overstated who a program is for.
    reason: str = Field(min_length=1, max_length=160)

    @model_validator(mode="after")
    def _check(self) -> "Program":
        if not is_label(self.category, self.subcategory):
            raise ValueError(f"{self.id}: unknown category {self.category}/{self.subcategory}")
        if any(not 1 <= m <= 12 for m in self.window_months):
            raise ValueError(f"{self.id}: window_months must be 1–12")
        return self


class ProgramsFile(BaseModel):
    last_checked: str
    programs: list[Program]


def programs_file(campus: str) -> Path | None:
    """The programs file for a feed, from its registry entry; None when it lists none."""
    entry = campuses.by_feed(campus)
    if entry is None or entry.opportunities is None or entry.opportunities.programs is None:
        return None
    return entry.path(entry.opportunities.programs)


def load(campus: str, path: Path | None = None) -> list[Program]:
    path = path or programs_file(campus)
    return _load(path) if path is not None else []


@lru_cache(maxsize=8)
def _load(path: Path) -> list[Program]:
    if not path.is_file():
        return []
    return ProgramsFile.model_validate(json.loads(path.read_text())).programs


def is_program(opportunity_id: str) -> bool:
    return opportunity_id.startswith(ID_PREFIX)


def as_rows(campus: str, path: Path | None = None) -> list[dict[str, Any]]:
    """Programs in the shape of an `opportunities` row, plus their label and window."""
    return [{
        "id": f"{ID_PREFIX}{p.id}", "campus": campus, "type": "program", "title": p.title, "org": p.org,
        "url": str(p.url), "description": p.description, "tags": p.tags,
        "starts_at": None, "ends_at": None, "deadline": None, "location": None, "modality": p.modality,
        "category": p.category, "subcategory": p.subcategory,
        "window": p.window, "window_months": p.window_months, "last_checked": p.last_checked,
        "reviewed_reason": p.reason,
    } for p in load(campus, path)]
