"""`articulation_cache` (PROJECT.md §9): every fetched agreement is kept, because
the ASSIST API is unofficial and can disappear mid-demo.

Process memory always; Supabase too when SUPABASE_URL + SUPABASE_SERVICE_ROLE_KEY
are set (via PostgREST, so no extra dependency). A Supabase failure never fails
the request — the cache is an optimization, ASSIST is the source of truth.
"""

import logging
import os
import threading
from collections import OrderedDict
from datetime import datetime, timezone
from typing import Any

import httpx

from app.config import supabase_rest_url

log = logging.getLogger(__name__)


# Raw agreements are ~40–60 KB each; Supabase keeps everything, memory keeps the hot set.
MAX_IN_MEMORY = 256


class ArticulationCache:
    def __init__(self, rest_url: str | None = None, service_key: str | None = None,
                 transport: httpx.BaseTransport | None = None):
        self._mem: OrderedDict[str, dict[str, Any]] = OrderedDict()  # least recently used first
        self._lock = threading.Lock()
        self._db: httpx.Client | None = None
        if rest_url and service_key:
            self._db = httpx.Client(
                base_url=rest_url,
                headers={"apikey": service_key, "Authorization": f"Bearer {service_key}"},
                timeout=10.0,
                transport=transport,
            )

    @classmethod
    def from_env(cls) -> "ArticulationCache":
        return cls(supabase_rest_url(), os.getenv("SUPABASE_SERVICE_ROLE_KEY") or None)

    def get(self, key: str) -> dict[str, Any] | None:
        with self._lock:
            if key in self._mem:
                self._mem.move_to_end(key)
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
        self._remember(key, payload)
        return payload

    def _remember(self, key: str, payload: dict[str, Any]) -> None:
        with self._lock:
            self._mem[key] = payload
            self._mem.move_to_end(key)
            while len(self._mem) > MAX_IN_MEMORY:
                self._mem.popitem(last=False)

    def put(self, key: str, payload: dict[str, Any], *, sending_id: int, receiving_id: int,
            year_id: int, major_label: str) -> None:
        self._remember(key, payload)
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
