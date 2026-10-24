"""Curated Radar sources from data/sources.json (PROJECT.md §8.3)."""

import json
import os
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, HttpUrl

from app.models.contracts import Campus

SOURCES_FILE = Path(
    os.getenv("SOURCES_FILE") or Path(__file__).resolve().parents[5] / "data" / "sources.json"
)

Kind = Literal["localist", "livewhale", "campusgroups_rss", "devpost", "mlh_season"]


class Source(BaseModel):
    id: str
    name: str
    kind: Kind
    url: HttpUrl
    homepage: HttpUrl
    org: str
    tags: list[str] = []
    json_selector: str | None = None  # mlh_season: element holding the page's embedded JSON
    location_contains: list[str] = []  # mlh_season: keep events whose location mentions one of these


class SourcesFile(BaseModel):
    campuses: dict[Campus, list[Source]]
    shared: list[Source] = []


@lru_cache(maxsize=1)
def load(path: Path = SOURCES_FILE) -> SourcesFile:
    return SourcesFile.model_validate(json.loads(path.read_text()))


def for_campus(campus: Campus) -> list[Source]:
    data = load()
    return data.campuses.get(campus, []) + data.shared


def by_id(source_id: str) -> Source | None:
    data = load()
    for source in [s for group in data.campuses.values() for s in group] + data.shared:
        if source.id == source_id:
            return source
    return None
