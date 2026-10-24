"""`articulation_cache` (PROJECT.md §9): every fetched agreement is kept, because
the ASSIST API is unofficial and can disappear mid-demo.

Process memory always; Supabase too when SUPABASE_URL + SUPABASE_SERVICE_ROLE_KEY
are set (via PostgREST, so no extra dependency). A Supabase failure never fails
the request — the cache is an optimization, ASSIST is the source of truth.
"""

import logging
import os
import threading
from datetime import datetime, timezone
from typing import Any

import httpx

log = logging.getLogger(__name__)


class ArticulationCache:
    def __init__(self, supabase_url: str | None = None, service_key: str | None = None,
                 transport: httpx.BaseTransport | None = None):
        self._mem: dict[str, dict[str, Any]] = {}
        self._lock = threading.Lock()
        self._db: httpx.Client | None = None
        if supabase_url and service_key:
            self._db = httpx.Client(
                base_url=f"{supabase_url.rstrip('/')}/rest/v1",
                headers={"apikey": service_key, "Authorization": f"Bearer {service_key}"},
                timeout=10.0,
                transport=transport,
            )

    @classmethod
    def from_env(cls) -> "ArticulationCache":
        return cls(os.getenv("SUPABASE_URL") or None, os.getenv("SUPABASE_SERVICE_ROLE_KEY") or None)

    def get(self, key: str) -> dict[str, Any] | None:
        with self._lock:
            if key in self._mem:
                return self._mem[key]
        if self._db is None:
            return None
        try:
            res = self._db.get("/articulation_cache", params={"key": f"eq.{key}", "select": "payload"})
            res.raise_for_status()
            rows = res.json()
        except (httpx.HTTPError, ValueError) as e:
            log.warning("articulation_cache read failed for %s: %s", key, e)
            return None
        if not rows or not rows[0].get("payload"):
            return None
        payload = rows[0]["payload"]
        with self._lock:
            self._mem[key] = payload
        return payload

    def put(self, key: str, payload: dict[str, Any], *, sending_id: int, receiving_id: int,
            year_id: int, major_label: str) -> None:
        with self._lock:
            self._mem[key] = payload
        if self._db is None:
            return
        row = {
            "key": key,
            "sending_id": sending_id,
            "receiving_id": receiving_id,
            "year_id": year_id,
            "major_label": major_label,
            "payload": payload,
            "fetched_at": datetime.now(timezone.utc).isoformat(),
        }
        try:
            self._db.post(
                "/articulation_cache",
                json=row,
                headers={"Prefer": "resolution=merge-duplicates,return=minimal"},
            ).raise_for_status()
        except httpx.HTTPError as e:
            log.warning("articulation_cache write failed for %s: %s", key, e)
