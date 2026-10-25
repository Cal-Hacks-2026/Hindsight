"""Guide sections (data/university/sections.json, the same for every university) and each
university's source pages (the file its registry entry names: university_guide.sources)."""

import json
import os
from functools import lru_cache
from pathlib import Path
from urllib.parse import urlparse

from pydantic import BaseModel, HttpUrl

from app.models.contracts import GuideSectionId
from app.services import campuses

SECTIONS_FILE = Path(
    os.getenv("UNIVERSITY_SECTIONS_FILE")
    or Path(__file__).resolve().parents[5] / "data" / "university" / "sections.json"
)


class Section(BaseModel):
    id: GuideSectionId
    title: str
    topic: str  # what the section covers; given to Claude as its brief
    opportunity_types: list[str] = []


class Source(BaseModel):
    id: str
    title: str
    publisher: str
    url: HttpUrl
    sections: list[GuideSectionId]


class University(BaseModel):
    id: int  # ASSIST institution id
    name: str
    sources: list[Source]

    def for_section(self, section: GuideSectionId) -> list[Source]:
        return [s for s in self.sources if section in s.sections]

    def source(self, source_id: str) -> Source | None:
        return next((s for s in self.sources if s.id == source_id), None)


class SectionsFile(BaseModel):
    sections: list[Section]


class SourceList(BaseModel):
    sources: list[Source]


class SourcesFile(BaseModel):
    sections: list[Section]
    universities: list[University]


@lru_cache(maxsize=1)
def load() -> SourcesFile:
    """The sections, and every registry university that lists guide sources."""
    return SourcesFile(
        sections=SectionsFile.model_validate(json.loads(SECTIONS_FILE.read_text())).sections,
        universities=[
            University(id=c.assist_id, name=c.name,
                       sources=SourceList.model_validate(
                           json.loads(c.path(c.university_guide.sources).read_text())).sources)
            for c in campuses.all_campuses() if c.university_guide
        ],
    )


def university(university_id: int) -> University | None:
    return next((u for u in load().universities if u.id == university_id), None)


def host(url: str) -> str:
    return (urlparse(url).hostname or "").removeprefix("www.")
