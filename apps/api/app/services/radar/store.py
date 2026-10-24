"""`opportunities` in Supabase (PROJECT.md §9), via PostgREST like articulation_cache."""

import os
from typing import Any

import httpx

from app.config import supabase_rest_url
from app.models.contracts import Campus
from app.services.radar.normalize import RadarItem

UPSERT_CHUNK = 500
# Ranking reads at most this many rows per campus; scans produce a few hundred.
MAX_CANDIDATES = 2000


class StoreError(Exception):
    status = 502


class StoreNotConfigured(StoreError):
    status = 503


def _client(transport: httpx.BaseTransport | None = None) -> httpx.Client:
    rest_url, key = supabase_rest_url(), os.getenv("SUPABASE_SERVICE_ROLE_KEY")
    if not rest_url or not key:
        raise StoreNotConfigured("Radar storage is not configured (SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY)")
    return httpx.Client(base_url=rest_url, headers={"apikey": key, "Authorization": f"Bearer {key}"},
                        timeout=15.0, transport=transport)


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
