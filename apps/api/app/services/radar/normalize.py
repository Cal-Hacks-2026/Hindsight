"""Cheerio Scraper dataset items → §8.3 Radar items (PROJECT.md §6, §8.3).

Each source kind has an extractor, extractors/<kind>.py (see extract.py), over the
raw JSON / RSS / embedded JSON that extractors/page_function.js returns. The rules
below hold for every kind and stay outside the extractors folder Droid may patch:
- `url` is an absolute http(s) URL (the item's own page on the source); anything
  else is dropped. Scraped URLs are untrusted.
- Dates come only from the source. Missing stays None; nothing is guessed. A date
  printed without a time is pinned to 00:00 Pacific, so a countdown never shows
  more time left than the source gives.
- Items that already ended are dropped; so are cancelled, deleted, or invite-only ones.
- A broken extractor fails only its own sources; the error is reported per source.
"""

import logging
import re
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from pydantic import BaseModel

from app.models.contracts import Campus
from app.services.radar import extract
from app.services.radar import sources as sources_mod
from app.services.radar.extract import MODALITIES, ItemType, Modality, Parsed, clean_text, is_http_url
from app.services.radar.sources import Source
from app.services.radar.extract import parse_devpost_dates, parse_when  # noqa: F401 (re-exported)

log = logging.getLogger(__name__)

MAX_DESCRIPTION = 2000
MAX_LOCATION = 200
MAX_TAGS = 20
# An item with a start but no end is treated as over this long after it starts.
NO_END_GRACE = timedelta(days=1)


class RadarItem(BaseModel):
    """The §8.3 item shape; one row of `opportunities`."""

    title: str
    type: ItemType
    org: str
    campus: Campus
    starts_at: str | None = None
    deadline: str | None = None
    url: str
    description: str
    tags: list[str]
    scraped_at: str
    # Opportunities: ten categories, programs, fits your week.
    ends_at: str | None = None
    location: str | None = None
    modality: Modality | None = None


@dataclass
class NormalizeResult:
    items: list[RadarItem]
    per_source: Counter  # source id → items kept
    skipped: Counter  # reason → count
    fetched: Counter = field(default_factory=Counter)  # source id → dataset items (pages) seen
    fetch_failed: Counter = field(default_factory=Counter)  # source id → pages that came back empty
    parsed: Counter = field(default_factory=Counter)  # source id → listings its extractor returned
    errors: dict[str, str] = field(default_factory=dict)  # source id → extractor error


# ---- shared rules ----

_RULES: list[tuple[ItemType, re.Pattern]] = [
    ("hackathon", re.compile(r"\bhack(athon|athons|s)?\b", re.I)),
    ("workshop", re.compile(r"\bworkshops?\b", re.I)),
    ("position", re.compile(r"\b(internships?|hiring|job openings?|research assistants?|now recruiting)\b", re.I)),
    ("program", re.compile(r"\b(fellowships?|scholarships?|accelerator|bootcamp|cohort)\b", re.I)),
]


def infer_type(title: str, hints: set[ItemType]) -> ItemType:
    """First match wins: the title's own words, or the source's category for that type."""
    for kind, pattern in _RULES:
        if kind in hints or pattern.search(title):
            return kind
    return "club" if "club" in hints else "event"


def _tags(*groups: list[str]) -> list[str]:
    seen: dict[str, None] = {}
    for group in groups:
        for t in group:
            tag = clean_text(t).lower()
            if tag and len(tag) <= 60:
                seen.setdefault(tag, None)
    return list(seen)[:MAX_TAGS]


def _ended(p: Parsed, now: datetime) -> bool:
    if p.deadline is not None:
        return p.deadline < now
    if p.ends_at is not None:
        return p.ends_at < now
    return p.starts_at is not None and p.starts_at + NO_END_GRACE < now


def _iso(dt: datetime | None) -> str | None:
    return dt.isoformat() if dt else None


def normalize(raw_items: list[dict], now: datetime, lookup=sources_mod.by_id,
              runner=extract.run_isolated) -> NormalizeResult:
    """Dataset items from one or more scans → deduped (by url) Radar items.
    `runner` executes the extractors (by default in a separate process; see extract.py)."""
    items: dict[str, RadarItem] = {}
    result = NormalizeResult(items=[], per_source=Counter(), skipped=Counter())
    scraped_at = now.isoformat()

    pending: list[tuple[dict, Source, str]] = []
    batches: extract.Batches = {}
    for raw in raw_items:
        source = lookup(raw.get("sourceId") or "")
        campus = raw.get("campus")
        if source is None or campus not in ("sjsu", "berkeley"):
            result.skipped["unknown_source"] += 1
            continue
        result.fetched[source.id] += 1
        if raw.get("#error") or not any(k in raw for k in ("json", "text", "embeddedJson")):
            result.skipped["fetch_failed"] += 1
            result.fetch_failed[source.id] += 1
            continue
        pending.append((raw, source, campus))
        batches.setdefault(source.kind, []).append((raw, source))

    outputs = {kind: iter(results) for kind, results in runner(batches).items()}
    for raw, source, campus in pending:
        parsed = next(outputs[source.kind])
        if isinstance(parsed, extract.ExtractorError):
            result.skipped["extractor_error"] += 1
            result.errors[source.id] = str(parsed)
            log.warning("radar: extractor failed for %s: %s", source.id, parsed)
            continue
        result.parsed[source.id] += len(parsed)
        for p in parsed:
            title = clean_text(p.title)
            if not title or not is_http_url(p.url):
                result.skipped["missing_title_or_url"] += 1
                continue
            if _ended(p, now):
                result.skipped["ended"] += 1
                continue
            if p.url in items:
                result.skipped["duplicate_url"] += 1
                continue
            items[p.url] = RadarItem(
                title=title[:300],
                type=infer_type(title, p.type_hints),
                org=clean_text(p.org) or source.org,
                campus=campus,
                starts_at=_iso(p.starts_at),
                deadline=_iso(p.deadline),
                url=p.url,
                description=clean_text(p.description)[:MAX_DESCRIPTION],
                tags=_tags(source.tags, p.tags),
                scraped_at=scraped_at,
                ends_at=_iso(p.ends_at) if p.ends_at and (p.starts_at is None or p.ends_at >= p.starts_at) else None,
                location=clean_text(p.location)[:MAX_LOCATION] or None,
                modality=p.modality if p.modality in MODALITIES else None,
            )
            result.per_source[source.id] += 1
    result.items = list(items.values())
    return result
