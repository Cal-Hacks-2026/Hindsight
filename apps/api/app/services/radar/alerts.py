"""The agent's ranking and alert steps (PROJECT.md §12, DECISIONS.md D-006).

Ranking re-runs the Radar feed for each profile that reads a campus's feed (its university's or its
own college's, by ASSIST id: radar/feeds.py) and stores it in
profile_opportunities (which also pre-warms Claude's cached reasons, D-005).
An alert is a top-ranked item whose deadline (or, without one, its start) falls
within the next ALERT_WINDOW; writing it sets `notified` on that row.
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from app.models import Profile
from app.models.contracts import Campus
from app.services import campuses, profile_store
from app.services.radar import feeds, rank, store
from app.services.radar.extract import parse_when

ALERT_TOP_N = 5
ALERT_WINDOW = timedelta(days=7)
MAX_PROFILES = 200


class UnknownProfile(Exception):
    pass


@dataclass
class Ranked:
    profile_id: str
    ranked: int
    top: list[dict] = field(default_factory=list)


@dataclass
class Alert:
    profile_id: str
    opportunity_id: str
    title: str
    url: str
    when: str
    new: bool  # False when this row was already notified on an earlier run


def _profiles(campus: Campus, profile_id: str | None) -> list[Profile]:
    if profile_id is None:
        entry = campuses.by_feed(campus)
        found = profile_store.list_profiles_at(entry.assist_id, limit=MAX_PROFILES) if entry else []
        return [p for p in found if feeds.for_key(p, campus)]
    profile = profile_store.get_profile(profile_id)
    if profile is None or feeds.for_key(profile, campus) is None:
        raise UnknownProfile(f"No {campus} profile {profile_id}")
    return [profile]


def rank_profiles(campus: Campus, profile_id: str | None = None, now: datetime | None = None) -> list[Ranked]:
    profiles = _profiles(campus, profile_id)
    stored: dict[str, list[dict]] = {}

    def read(feed: str) -> list[dict]:
        if feed not in stored:
            stored[feed] = store.candidates(feed)
        return stored[feed]

    out = []
    for profile in profiles:
        # Every feed the profile reads, so a student with two feeds keeps both in their ranking.
        items = rank.ranked_opportunities(profile, feeds.candidates(profile, with_programs=False, read=read), now)
        store.record_ranked(profile.id, items)
        out.append(Ranked(profile_id=profile.id, ranked=len(items), top=[
            {"title": i.title, "score": i.score, "deadline": i.deadline, "starts_at": i.starts_at}
            for i in items[:3]]))
    return out


def due_within(row: dict, now: datetime, window: timedelta = ALERT_WINDOW) -> datetime | None:
    """The row's deadline, or its start when it has none, if that is in [now, now + window]."""
    opp = row.get("opportunities") or {}
    when = parse_when(opp.get("deadline")) or parse_when(opp.get("starts_at"))
    return when if when is not None and now <= when <= now + window else None


def write_alerts(campus: Campus, profile_id: str | None = None, now: datetime | None = None) -> list[Alert]:
    now = now or datetime.now(timezone.utc)
    out = []
    for profile in _profiles(campus, profile_id):
        due = [(row, when) for row in store.top_ranked(profile.id, ALERT_TOP_N)
               if (when := due_within(row, now)) is not None]
        store.mark_notified(profile.id, [str(row["opportunity_id"]) for row, _ in due if not row.get("notified")])
        out += [Alert(profile_id=profile.id, opportunity_id=str(row["opportunity_id"]),
                      title=(row.get("opportunities") or {}).get("title") or "",
                      url=(row.get("opportunities") or {}).get("url") or "",
                      when=when.isoformat(), new=not row.get("notified")) for row, when in due]
    return out

