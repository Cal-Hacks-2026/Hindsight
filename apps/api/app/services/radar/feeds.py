"""Which opportunity feeds a profile reads, found in the campus registry by its ASSIST ids.

A student reads their university's feed and, when their own community college has one in the
registry, that one too. Every listing from a campus's own sources carries that campus's ASSIST id
(`campus_id`), so the feed can say where it is ("At <university>, your target school"); listings
open to every campus (hackathons) carry none. A school with no feed adds nothing: a student never
sees another campus's listings.
"""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Literal

from app.models import Profile
from app.services import campuses
from app.services.radar import programs, sources, store

# Open to students of every campus, whichever campus's scan found them (store.candidates).
OPEN_TYPES = {"hackathon"}


@dataclass(frozen=True)
class Feed:
    key: str  # the registry's opportunities.feed
    campus: campuses.Campus
    role: Literal["university", "college"]


def for_profile(profile: Profile) -> list[Feed]:
    """The university's feed first, then the college's; each only when the registry lists sources."""
    scanned = sources.load().campuses
    out: list[Feed] = []
    for role, assist_id in (("university", profile.receiving_institution_id),
                            ("college", profile.sending_institution_id)):
        entry = campuses.get(assist_id)
        key = entry.opportunities.feed if entry and entry.opportunities else None
        if key in scanned and all(f.key != key for f in out):
            out.append(Feed(key=key, campus=entry, role=role))  # type: ignore[arg-type]
    return out


def for_key(profile: Profile, key: str) -> Feed | None:
    return next((f for f in for_profile(profile) if f.key == key), None)


def label(rows: list[dict[str, Any]], feeds: list[Feed]) -> list[dict[str, Any]]:
    """Each row with `campus_id`: the ASSIST id of the campus whose own listing it is."""
    ids = {f.key: f.campus.assist_id for f in feeds}
    return [{**r, "campus_id": ids.get(r.get("campus")) if r.get("type") not in OPEN_TYPES else None}
            for r in rows]


def where(profile: Profile, campus_id: int | None) -> str | None:
    """Where a labeled listing is, for the counselor: "<short name> (the student's target university)"."""
    entry = campuses.get(campus_id)
    if entry is None:
        return None
    if campus_id == profile.receiving_institution_id:
        role = "university" if profile.stage == "transferred" else "target university"
    else:
        role = "community college"
    return f"{entry.short_name} (the student's {role})"


def candidates(profile: Profile, with_programs: bool = True,
               read: Callable[[str], list[dict[str, Any]]] | None = None) -> list[dict[str, Any]]:
    """Stored listings (and recurring programs) from every feed the profile reads, each once.
    `read` gives one feed's stored rows (a caller ranking many profiles passes a memoized one)."""
    read = read or store.candidates
    feeds = for_profile(profile)
    rows: dict[str, dict[str, Any]] = {}
    for f in feeds:
        for r in read(f.key) + (programs.as_rows(f.key) if with_programs else []):
            rows.setdefault(str(r["id"]), r)
    return label(list(rows.values()), feeds)
