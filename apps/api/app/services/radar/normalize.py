"""Cheerio Scraper dataset items → §8.3 Radar items (PROJECT.md §6, §8.3).

Each source kind has its own parser over the raw JSON / RSS / embedded JSON that
page_function.js returns. Rules that hold for every kind:
- `url` is the item's own page on the source, never a search or listing page.
- Dates come only from the source. Missing stays None; nothing is guessed. A date
  printed without a time is pinned to 00:00 Pacific, so a countdown never shows
  more time left than the source gives.
- Items that already ended are dropped; so are cancelled, deleted, or invite-only ones.
"""

import html
import json
import logging
import re
from collections import Counter
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any, Callable, Literal
from zoneinfo import ZoneInfo

from defusedxml import DefusedXmlException
from defusedxml import ElementTree as ET
from pydantic import BaseModel

from app.models.contracts import Campus
from app.services.radar import sources as sources_mod
from app.services.radar.sources import Source

log = logging.getLogger(__name__)

PACIFIC = ZoneInfo("America/Los_Angeles")
MAX_DESCRIPTION = 2000
MAX_TAGS = 20
# An item with a start but no end is treated as over this long after it starts.
NO_END_GRACE = timedelta(days=1)

ItemType = Literal["event", "workshop", "club", "program", "hackathon", "position"]


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


@dataclass
class _Parsed:
    """What a kind parser extracts; normalize() fills in the rest."""

    title: str
    url: str
    starts_at: datetime | None = None
    ends_at: datetime | None = None
    deadline: datetime | None = None
    org: str = ""
    description: str = ""
    tags: list[str] = field(default_factory=list)
    type_hints: set[ItemType] = field(default_factory=set)  # from the source's own categories


@dataclass
class NormalizeResult:
    items: list[RadarItem]
    per_source: Counter
    skipped: Counter  # reason → count


# ---- helpers ----

_TAG = re.compile(r"<[^>]+>")
_SPACE = re.compile(r"\s+")
_FRACTION = re.compile(r"(\.\d{6})\d+")


def clean_text(value: Any) -> str:
    """HTML or entity-laden text → one line of plain text."""
    if not isinstance(value, str):
        return ""
    text = html.unescape(_TAG.sub(" ", html.unescape(value)))
    return _SPACE.sub(" ", text).strip()


def parse_when(value: Any) -> datetime | None:
    """ISO 8601 datetime or date → aware datetime; None when absent or unparseable."""
    if not isinstance(value, str) or not value.strip():
        return None
    raw = _FRACTION.sub(r"\1", value.strip().replace("Z", "+00:00"))
    try:
        if len(raw) == 10:
            return datetime.combine(date.fromisoformat(raw), datetime.min.time(), PACIFIC)
        dt = datetime.fromisoformat(raw)
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=PACIFIC)


def _pacific_midnight(d: date) -> datetime:
    return datetime.combine(d, datetime.min.time(), PACIFIC)


_MONTHS = {m: i for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], start=1)}
_DEVPOST_RANGE = re.compile(
    r"^(?P<m1>[A-Za-z]{3})[a-z]*\.? (?P<d1>\d{1,2})(?:, (?P<y1>\d{4}))?"
    r"(?: - (?:(?P<m2>[A-Za-z]{3})[a-z]*\.? )?(?P<d2>\d{1,2}))?, (?P<y2>\d{4})$"
)


def parse_devpost_dates(text: Any) -> tuple[date, date] | None:
    """Devpost `submission_period_dates` → (first day, last day).

    Forms seen: "Oct 23 - 25, 2026", "Oct 23 - Nov 02, 2026",
    "Dec 30, 2026 - Jan 02, 2027", "Mar 27, 2027".
    """
    if not isinstance(text, str):
        return None
    m = _DEVPOST_RANGE.match(text.strip())
    if not m:
        return None
    try:
        m1 = _MONTHS[m["m1"].lower()]
        m2 = _MONTHS[m["m2"].lower()] if m["m2"] else m1
        y2 = int(m["y2"])
        y1 = int(m["y1"]) if m["y1"] else y2
        start = date(y1, m1, int(m["d1"]))
        end = date(y2, m2, int(m["d2"])) if m["d2"] else start
    except (KeyError, ValueError):
        return None
    if end < start:
        return None
    return start, end


def _is_http_url(value: Any) -> bool:
    return isinstance(value, str) and re.match(r"^https?://[^\s/]+", value) is not None


def _names(entries: Any) -> list[str]:
    return [e["name"] for e in entries or [] if isinstance(e, dict) and isinstance(e.get("name"), str)]


# ---- kind parsers: (raw dataset item, source) → parsed items ----


def _localist(raw: dict, source: Source) -> list[_Parsed]:
    out = []
    for wrapper in (raw.get("json") or {}).get("events") or []:
        e = wrapper.get("event") or {}
        if e.get("status") != "live" or e.get("private"):
            continue
        instances = e.get("event_instances") or []
        inst = (instances[0].get("event_instance") or {}) if instances else {}
        filters = e.get("filters") or {}
        tags = (_names(filters.get("event_types")) + _names(filters.get("event_topic"))
                + _names(filters.get("event_target_audience")) + list(e.get("keywords") or []))
        if e.get("experience") == "virtual":
            tags.append("virtual")
        org = (_names(e.get("departments")) + _names(e.get("groups")) or [""])[0]
        out.append(_Parsed(
            title=e.get("title") or "",
            url=e.get("localist_url") or "",
            starts_at=parse_when(inst.get("start")),
            ends_at=parse_when(inst.get("end")),
            org=org,
            description=e.get("description_text") or "",
            tags=tags,
            type_hints={"workshop"} if "Conferences, Training, Workshops" in tags else set(),
        ))
    return out


def _livewhale(raw: dict, source: Source) -> list[_Parsed]:
    out = []
    for e in (raw.get("json") or {}).get("data") or []:
        if e.get("is_canceled"):
            continue
        tags = list(e.get("tags") or []) + list(e.get("event_types") or [])
        if e.get("is_online"):
            tags.append("online")
        out.append(_Parsed(
            title=e.get("title") or "",
            url=e.get("url") or "",
            starts_at=parse_when(e.get("date_iso")),
            ends_at=parse_when(e.get("date2_iso")),
            org=e.get("group_title") or "",
            description=e.get("summary") or "",
            tags=tags,
        ))
    return out


def _campusgroups_rss(raw: dict, source: Source) -> list[_Parsed]:
    text = raw.get("text") or ""
    try:
        root = ET.fromstring(text)
    except (ET.ParseError, DefusedXmlException) as e:
        log.warning("%s: unreadable RSS: %s", source.id, e)
        return []
    out = []
    for item in root.iter("item"):
        def get(tag: str) -> str:
            return (item.findtext(tag) or "").strip()

        if get("eventDelete") not in ("", "0"):
            continue
        tags = [get("eventType"), get("groupType")] + [t.strip() for t in get("eventTopics").split(",")]
        out.append(_Parsed(
            title=get("title"),
            url=get("eventLink") or get("link"),
            starts_at=parse_when(get("eventStartDateTime")),
            ends_at=parse_when(get("eventEndDateTime")),
            org=get("group"),
            description=get("fullDescription") or get("description"),
            tags=tags,
            type_hints=({"club"} if clean_text(get("groupType")) == "Recognized Student Organization" else set())
            | ({"workshop"} if get("eventType") == "Workshop" else set()),
        ))
    return out


def _devpost(raw: dict, source: Source) -> list[_Parsed]:
    out = []
    for h in (raw.get("json") or {}).get("hackathons") or []:
        if h.get("open_state") == "ended" or h.get("invite_only"):
            continue
        dates = parse_devpost_dates(h.get("submission_period_dates"))
        location = clean_text((h.get("displayed_location") or {}).get("location"))
        themes = _names(h.get("themes"))
        prize = clean_text(h.get("prize_amount"))
        parts = [f"Location: {location}." if location else "",
                 f"Themes: {', '.join(themes)}." if themes else "",
                 f"Prizes: {prize}." if prize and prize not in ("$0", "$ 0") else ""]
        out.append(_Parsed(
            title=h.get("title") or "",
            url=h.get("url") or "",
            starts_at=_pacific_midnight(dates[0]) if dates else None,
            # The submission period's last day is the deadline.
            deadline=_pacific_midnight(dates[1]) if dates else None,
            org=h.get("organization_name") or "",
            description=" ".join(p for p in parts if p),
            tags=themes + (["online"] if location.lower() == "online" else []),
            type_hints={"hackathon"},
        ))
    return out


_MLH_FORMATS = {"physical": "in-person", "hybrid_physical": "hybrid", "digital": "online"}


def _mlh_season(raw: dict, source: Source) -> list[_Parsed]:
    out = []
    for blob in raw.get("embeddedJson") or []:
        try:
            events = (json.loads(blob).get("props") or {}).get("upcomingEvents") or []
        except (ValueError, AttributeError):
            log.warning("%s: unreadable embedded JSON", source.id)
            continue
        for e in events:
            location = clean_text(e.get("location"))
            if source.location_contains and not any(w.lower() in location.lower() for w in source.location_contains):
                continue
            url = e.get("websiteUrl") or ""
            if not _is_http_url(url) and isinstance(e.get("url"), str):
                url = f"https://www.mlh.com{e['url']}"
            fmt = _MLH_FORMATS.get(e.get("formatType") or "", "")
            focus = list(((e.get("customFields") or {}).get("hackathon_focus")) or [])
            out.append(_Parsed(
                title=e.get("name") or "",
                url=url,
                starts_at=parse_when(e.get("startsAt")),
                ends_at=parse_when(e.get("endsAt")),
                description=f"MLH member hackathon in {location}." if location else "MLH member hackathon.",
                tags=focus + ([fmt] if fmt else []),
                type_hints={"hackathon"},
            ))
    return out


PARSERS: dict[str, Callable[[dict, Source], list[_Parsed]]] = {
    "localist": _localist,
    "livewhale": _livewhale,
    "campusgroups_rss": _campusgroups_rss,
    "devpost": _devpost,
    "mlh_season": _mlh_season,
}


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


def _ended(p: _Parsed, now: datetime) -> bool:
    if p.deadline is not None:
        return p.deadline < now
    if p.ends_at is not None:
        return p.ends_at < now
    return p.starts_at is not None and p.starts_at + NO_END_GRACE < now


def _iso(dt: datetime | None) -> str | None:
    return dt.isoformat() if dt else None


def normalize(raw_items: list[dict], now: datetime, lookup=sources_mod.by_id) -> NormalizeResult:
    """Dataset items from one or more scans → deduped (by url) Radar items."""
    items: dict[str, RadarItem] = {}
    per_source: Counter = Counter()
    skipped: Counter = Counter()
    scraped_at = now.isoformat()

    for raw in raw_items:
        source = lookup(raw.get("sourceId") or "")
        campus = raw.get("campus")
        if source is None or campus not in ("sjsu", "berkeley"):
            skipped["unknown_source"] += 1
            continue
        if raw.get("#error") or not any(k in raw for k in ("json", "text", "embeddedJson")):
            skipped["fetch_failed"] += 1
            continue
        for p in PARSERS[source.kind](raw, source):
            title = clean_text(p.title)
            if not title or not _is_http_url(p.url):
                skipped["missing_title_or_url"] += 1
                continue
            if _ended(p, now):
                skipped["ended"] += 1
                continue
            if p.url in items:
                skipped["duplicate_url"] += 1
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
            )
            per_source[source.id] += 1
    return NormalizeResult(items=list(items.values()), per_source=per_source, skipped=skipped)
