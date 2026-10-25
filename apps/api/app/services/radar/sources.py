"""Curated Radar sources (PROJECT.md §8.3): each campus's file named in its registry entry
(data/campuses/<id>.json → opportunities.sources), plus data/opportunities/shared-sources.json,
which every campus scans."""

import json
import os
from functools import lru_cache
from pathlib import Path
from typing import Literal
from urllib.parse import urlparse

from pydantic import BaseModel, HttpUrl

from app.models.contracts import Campus
from app.services import campuses

SHARED_SOURCES_FILE = Path(
    os.getenv("SHARED_SOURCES_FILE")
    or Path(__file__).resolve().parents[5] / "data" / "opportunities" / "shared-sources.json"
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


class SourceList(BaseModel):
    """One sources file: a campus's own, or the shared one."""

    sources: list[Source]


class SourcesFile(BaseModel):
    campuses: dict[Campus, list[Source]]  # by feed
    shared: list[Source] = []


def _read(path: Path) -> list[Source]:
    return SourceList.model_validate(json.loads(path.read_text())).sources


@lru_cache(maxsize=1)
def load() -> SourcesFile:
    """Every feed in the registry with its sources, plus the shared sources."""
    return SourcesFile(
        campuses={c.opportunities.feed: _read(c.path(c.opportunities.sources))
                  for c in campuses.all_campuses() if c.opportunities},
        shared=_read(SHARED_SOURCES_FILE),
    )


def for_campus(campus: Campus) -> list[Source]:
    data = load()
    return data.campuses.get(campus, []) + data.shared


def by_id(source_id: str) -> Source | None:
    data = load()
    for source in [s for group in data.campuses.values() for s in group] + data.shared:
        if source.id == source_id:
            return source
    return None


CAMPUS_ONLY_KINDS: tuple[Kind, ...] = ("localist", "livewhale", "campusgroups_rss")


def other_campus_hosts(campus: Campus) -> set[str]:
    """Hosts of another campus's own event sites. Hackathon sites (Devpost, MLH) are open
    to every campus; these aren't, so their items stay out of this campus's feed."""
    data = load()
    return {
        (urlparse(str(s.url)).hostname or "").removeprefix("www.")
        for c, group in data.campuses.items() if c != campus
        for s in group if s.kind in CAMPUS_ONLY_KINDS
    }
