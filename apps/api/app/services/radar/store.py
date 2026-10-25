"""`opportunities`, `opportunity_labels`, and `profile_opportunities` in Supabase (PROJECT.md §9)."""

import logging
from typing import Any
from urllib.parse import urlparse

import httpx

from app.models.contracts import Campus, RankedOpportunity
from app.services.db import StoreError, StoreNotConfigured, client as _client  # noqa: F401 (re-exported)
from app.services.radar import sources
from app.services.radar.normalize import RadarItem

log = logging.getLogger(__name__)

UPSERT_CHUNK = 500
# Ranking reads at most this many rows per campus; scans produce a few hundred.
MAX_CANDIDATES = 2000
LABEL_READ_CHUNK = 150  # ids per request, to keep the URL short
# Columns added by supabase/migrations/20261025_opportunities.sql. Until that migration is
# applied, PostgREST rejects them (PGRST204), so rows are sent again without them.
NEW_COLUMNS = ("ends_at", "location", "modality")


def _missing_column(res: httpx.Response) -> bool:
    return res.status_code == 400 and "PGRST204" in res.text


def upsert(items: list[RadarItem], transport: httpx.BaseTransport | None = None) -> int:
    """Insert or update by `url` (unique); existing rows keep their id. Returns rows sent."""
    rows = [i.model_dump() for i in items]
    try:
        with _client(transport) as db:
            for start in range(0, len(rows), UPSERT_CHUNK):
                chunk = rows[start:start + UPSERT_CHUNK]
                res = db.post("/opportunities", params={"on_conflict": "url"}, json=chunk,
                              headers={"Prefer": "resolution=merge-duplicates,return=minimal"})
                if _missing_column(res):
                    log.warning("radar: opportunities lacks %s; apply the 20261025 migration", NEW_COLUMNS)
                    res = db.post("/opportunities", params={"on_conflict": "url"},
                                  json=[{k: v for k, v in r.items() if k not in NEW_COLUMNS} for r in chunk],
                                  headers={"Prefer": "resolution=merge-duplicates,return=minimal"})
                res.raise_for_status()
    except httpx.HTTPStatusError as e:
        raise StoreError(f"Supabase upsert failed ({e.response.status_code}): {e.response.text[:200]}") from e
    except httpx.HTTPError as e:
        raise StoreError(f"Supabase unreachable: {e}") from e
    return len(rows)


def candidates(campus: Campus, transport: httpx.BaseTransport | None = None) -> list[dict[str, Any]]:
    """Rows for a campus, plus hackathons from anywhere: they're open to students of every campus."""
    try:
        with _client(transport) as db:
            res = db.get("/opportunities", params={
                "select": "*",  # ends_at, location, modality once the 20261025 migration is applied
                "or": f"(campus.eq.{campus},type.eq.hackathon)",
                "order": "scraped_at.desc",
                "limit": str(MAX_CANDIDATES),
            })
            res.raise_for_status()
            return _drop_other_campus_sites(campus, res.json())
    except httpx.HTTPStatusError as e:
        raise StoreError(f"Supabase read failed ({e.response.status_code})") from e
    except (httpx.HTTPError, ValueError) as e:
        raise StoreError(f"Supabase unreachable: {e}") from e


def all_rows(transport: httpx.BaseTransport | None = None) -> list[dict[str, Any]]:
    """Every stored listing, any campus (for `python -m app.classify`)."""
    try:
        with _client(transport) as db:
            res = db.get("/opportunities", params={"select": "*", "order": "scraped_at.desc",
                                                   "limit": str(MAX_CANDIDATES * 2)})
            res.raise_for_status()
            return res.json()
    except httpx.HTTPStatusError as e:
        raise StoreError(f"Supabase read failed ({e.response.status_code})") from e
    except (httpx.HTTPError, ValueError) as e:
        raise StoreError(f"Supabase unreachable: {e}") from e


# ---- Opportunities: ten categories, programs, fits your week ----


def labels(opportunity_ids: list[str], transport: httpx.BaseTransport | None = None) -> list[dict[str, Any]]:
    """Stored Claude labels (opportunity_labels) for these listings."""
    if not opportunity_ids:
        return []
    out: list[dict[str, Any]] = []
    try:
        with _client(transport) as db:
            for start in range(0, len(opportunity_ids), LABEL_READ_CHUNK):
                ids = opportunity_ids[start:start + LABEL_READ_CHUNK]
                res = db.get("/opportunity_labels", params={
                    "select": "opportunity_id,category,subcategory,title_hash",
                    "opportunity_id": f"in.({','.join(ids)})",
                })
                res.raise_for_status()
                out += res.json()
    except httpx.HTTPStatusError as e:
        raise StoreError(f"Supabase read failed ({e.response.status_code})") from e
    except (httpx.HTTPError, ValueError) as e:
        raise StoreError(f"Supabase unreachable: {e}") from e
    return out


def save_labels(rows: list[dict[str, Any]], transport: httpx.BaseTransport | None = None) -> int:
    """Upsert labels by opportunity_id. Returns rows sent."""
    if not rows:
        return 0
    try:
        with _client(transport) as db:
            res = db.post("/opportunity_labels", params={"on_conflict": "opportunity_id"}, json=rows,
                          headers={"Prefer": "resolution=merge-duplicates,return=minimal"})
            res.raise_for_status()
    except httpx.HTTPStatusError as e:
        raise StoreError(f"Supabase upsert failed ({e.response.status_code}): {e.response.text[:200]}") from e
    except httpx.HTTPError as e:
        raise StoreError(f"Supabase unreachable: {e}") from e
    return len(rows)


def _drop_other_campus_sites(campus: Campus, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """A hackathon found on another campus's event site (e.g. events.berkeley.edu) isn't open to this campus."""
    foreign = sources.other_campus_hosts(campus)
    return [
        r for r in rows
        if r.get("campus") == campus
        or (urlparse(r.get("url") or "").hostname or "").removeprefix("www.") not in foreign
    ]


def record_ranked(profile_id: str, items: list[RankedOpportunity],
                  transport: httpx.BaseTransport | None = None) -> int:
    """Upsert the feed into profile_opportunities. `notified` isn't sent, so a re-rank
    updates score/reason and leaves notified as it was. Returns rows sent."""
    rows = [{"profile_id": profile_id, "opportunity_id": i.id, "score": i.score, "reason": i.reason}
            for i in items]
    if not rows:
        return 0
    try:
        with _client(transport) as db:
            res = db.post("/profile_opportunities", params={"on_conflict": "profile_id,opportunity_id"},
                          json=rows, headers={"Prefer": "resolution=merge-duplicates,return=minimal"})
            res.raise_for_status()
    except httpx.HTTPStatusError as e:
        raise StoreError(f"Supabase upsert failed ({e.response.status_code}): {e.response.text[:200]}") from e
    except httpx.HTTPError as e:
        raise StoreError(f"Supabase unreachable: {e}") from e
    return len(rows)


def top_ranked(profile_id: str, limit: int, transport: httpx.BaseTransport | None = None) -> list[dict[str, Any]]:
    """The profile's highest-scored rows in profile_opportunities, each with its opportunity."""
    try:
        with _client(transport) as db:
            res = db.get("/profile_opportunities", params={
                "select": "opportunity_id,score,notified,opportunities(title,url,starts_at,deadline)",
                "profile_id": f"eq.{profile_id}",
                "order": "score.desc",
                "limit": str(limit),
            })
            res.raise_for_status()
            return res.json()
    except httpx.HTTPStatusError as e:
        raise StoreError(f"Supabase read failed ({e.response.status_code})") from e
    except (httpx.HTTPError, ValueError) as e:
        raise StoreError(f"Supabase unreachable: {e}") from e


def mark_notified(profile_id: str, opportunity_ids: list[str],
                  transport: httpx.BaseTransport | None = None) -> int:
    """Set notified=true on these rows. Returns rows sent."""
    if not opportunity_ids:
        return 0
    try:
        with _client(transport) as db:
            res = db.patch("/profile_opportunities", params={
                "profile_id": f"eq.{profile_id}",
                "opportunity_id": f"in.({','.join(opportunity_ids)})",
            }, json={"notified": True}, headers={"Prefer": "return=minimal"})
            res.raise_for_status()
    except httpx.HTTPStatusError as e:
        raise StoreError(f"Supabase update failed ({e.response.status_code}): {e.response.text[:200]}") from e
    except httpx.HTTPError as e:
        raise StoreError(f"Supabase unreachable: {e}") from e
    return len(opportunity_ids)


def notified_ids(profile_id: str, transport: httpx.BaseTransport | None = None) -> set[str]:
    """Opportunity ids Droid has alerted this profile about (write_alerts sets notified)."""
    try:
        with _client(transport) as db:
            res = db.get("/profile_opportunities", params={
                "select": "opportunity_id",
                "profile_id": f"eq.{profile_id}",
                "notified": "is.true",
            })
            res.raise_for_status()
            return {str(row["opportunity_id"]) for row in res.json()}
    except httpx.HTTPStatusError as e:
        raise StoreError(f"Supabase read failed ({e.response.status_code})") from e
    except (httpx.HTTPError, ValueError) as e:
        raise StoreError(f"Supabase unreachable: {e}") from e
