"""Guide sections and source pages from data/university/sources.json."""

import json
import os
from functools import lru_cache
from pathlib import Path
from urllib.parse import urlparse

from pydantic import BaseModel, HttpUrl

from app.models.contracts import GuideSectionId

SOURCES_FILE = Path(
    os.getenv("UNIVERSITY_SOURCES_FILE")
    or Path(__file__).resolve().parents[5] / "data" / "university" / "sources.json"
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


class SourcesFile(BaseModel):
    sections: list[Section]
    universities: list[University]


@lru_cache(maxsize=1)
def load(path: Path = SOURCES_FILE) -> SourcesFile:
    return SourcesFile.model_validate(json.loads(path.read_text()))


def university(university_id: int) -> University | None:
    return next((u for u in load().universities if u.id == university_id), None)


def host(url: str) -> str:
    return (urlparse(url).hostname or "").removeprefix("www.")
