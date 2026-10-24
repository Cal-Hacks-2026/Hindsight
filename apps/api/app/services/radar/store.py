"""`opportunities` and `profile_opportunities` in Supabase (PROJECT.md §9)."""

from typing import Any

import httpx

from app.models.contracts import Campus, RankedOpportunity
from app.services.db import StoreError, StoreNotConfigured, client as _client  # noqa: F401 (re-exported)
from app.services.radar.normalize import RadarItem

UPSERT_CHUNK = 500
# Ranking reads at most this many rows per campus; scans produce a few hundred.
MAX_CANDIDATES = 2000


def upsert(items: list[RadarItem], transport: httpx.BaseTransport | None = None) -> int:
    """Insert or update by `url` (unique); existing rows keep their id. Returns rows sent."""
    rows = [i.model_dump() for i in items]
    try:
        with _client(transport) as db:
            for start in range(0, len(rows), UPSERT_CHUNK):
                res = db.post("/opportunities", params={"on_conflict": "url"},
                              json=rows[start:start + UPSERT_CHUNK],
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
                "select": "id,campus,type,title,org,starts_at,deadline,url,description,tags,scraped_at",
                "or": f"(campus.eq.{campus},type.eq.hackathon)",
                "order": "scraped_at.desc",
                "limit": str(MAX_CANDIDATES),
            })
            res.raise_for_status()
            return res.json()
    except httpx.HTTPStatusError as e:
        raise StoreError(f"Supabase read failed ({e.response.status_code})") from e
    except (httpx.HTTPError, ValueError) as e:
        raise StoreError(f"Supabase unreachable: {e}") from e


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
