"""Where guides and the pages they were written from are kept.

- data/university/guides/<id>.json: the guide as last built and reviewed in a PR, with each
  item's supporting quote and each section's input hash. Always available, even with no database.
- Supabase `university_guide_cache` (apps/api/supabase/migrations/): the latest built guide
  (`guide:<id>`) and every page it was written from (`page:<id>:<source id>`), so a rebuild
  can skip Apify and a server-side rebuild is served without a redeploy.

GET serves the newer of the file and the cached guide. A Supabase failure never fails the
request; the file is the fallback.
"""

import json
import logging
import os
import threading
import time
from pathlib import Path
from typing import Any

import httpx

from app.config import supabase_rest_url
from app.models.contracts import GuideItem, GuideSection, GuideSource, UniversityGuide
from app.services.university.fetch import Page

log = logging.getLogger(__name__)

GUIDES_DIR = Path(
    os.getenv("UNIVERSITY_GUIDES_DIR")
    or Path(__file__).resolve().parents[5] / "data" / "university" / "guides"
)
TABLE = "/university_guide_cache"
MEMORY_TTL = 600.0  # seconds a served guide (or its absence) is reused before re-reading


def guide_file(university_id: int) -> Path:
    return GUIDES_DIR / f"{university_id}.json"


def _db(transport: httpx.BaseTransport | None = None) -> httpx.Client | None:
    rest_url, key = supabase_rest_url(), os.getenv("SUPABASE_SERVICE_ROLE_KEY")
    if not rest_url or not key:
        return None
    return httpx.Client(base_url=rest_url, headers={"apikey": key, "Authorization": f"Bearer {key}"},
                        timeout=10.0, transport=transport)


def _get_rows(key_filter: str, transport: httpx.BaseTransport | None = None) -> list[dict[str, Any]]:
    """Rows whose key matches a PostgREST filter, e.g. `eq.guide:39` or `like.page:39:*`."""
    db = _db(transport)
    if db is None:
        return []
    try:
        with db:
            res = db.get(TABLE, params={"key": key_filter, "select": "key,payload,fetched_at"})
            res.raise_for_status()
            return res.json()
    except (httpx.HTTPError, ValueError) as e:
        log.warning("university_guide_cache read failed for %s: %s", key_filter, e)
        return []


def _put_rows(rows: list[dict[str, Any]], transport: httpx.BaseTransport | None = None) -> bool:
    db = _db(transport)
    if db is None or not rows:
        return False
    try:
        with db:
            db.post(TABLE, json=rows,
                    headers={"Prefer": "resolution=merge-duplicates,return=minimal"}).raise_for_status()
        return True
    except httpx.HTTPError as e:
        log.warning("university_guide_cache write failed: %s", e)
        return False


# ---- pages ----


def save_pages(university_id: int, pages: list[Page], transport: httpx.BaseTransport | None = None) -> bool:
    return _put_rows([{
        "key": f"page:{university_id}:{p.source_id}", "university_id": university_id, "kind": "page",
        "payload": p.__dict__, "fetched_at": f"{p.retrieved_on}T00:00:00Z",
    } for p in pages], transport)


def cached_pages(university_id: int, transport: httpx.BaseTransport | None = None) -> list[Page]:
    return [Page(**row["payload"]) for row in _get_rows(f"like.page:{university_id}:*", transport)]


# ---- guides ----


def save_guide(stored: dict[str, Any], transport: httpx.BaseTransport | None = None) -> bool:
    """Write the built guide to its file and to the cache."""
    uid = stored["university_id"]
    GUIDES_DIR.mkdir(parents=True, exist_ok=True)
    guide_file(uid).write_text(json.dumps(stored, indent=2, ensure_ascii=False) + "\n")
    with _lock:
        _memory.pop(uid, None)
    return _put_rows([{"key": f"guide:{uid}", "university_id": uid, "kind": "guide", "payload": stored,
                       "fetched_at": stored["generated_at"]}], transport)


def _from_file(university_id: int) -> dict[str, Any] | None:
    path = guide_file(university_id)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError) as e:
        log.error("university guide file %s is unreadable: %s", path, e)
        return None


def _from_cache(university_id: int, transport: httpx.BaseTransport | None = None) -> dict[str, Any] | None:
    rows = _get_rows(f"eq.guide:{university_id}", transport)
    return rows[0]["payload"] if rows and isinstance(rows[0].get("payload"), dict) else None


def to_contract(stored: dict[str, Any]) -> UniversityGuide:
    """The stored guide without its build details (quotes, hashes), cited sources only, in
    footnote order; empty sections are left out."""
    by_id = {s["id"]: s for s in stored["sources"]}
    sections, order = [], []
    for sec in stored["sections"]:
        items = [GuideItem(text=i["text"], source_ids=[s for s in i["source_ids"] if s in by_id])
                 for i in sec["items"]]
        items = [i for i in items if i.source_ids]
        if not items:
            continue
        for item in items:
            order += [s for s in item.source_ids if s not in order]
        sections.append(GuideSection(id=sec["id"], title=sec["title"], items=items,
                                     opportunity_types=sec.get("opportunity_types") or None))
    return UniversityGuide(
        university_id=stored["university_id"], university_name=stored["university_name"],
        last_updated=stored["last_updated"], sections=sections,
        sources=[GuideSource(**{k: by_id[s][k] for k in GuideSource.model_fields}) for s in order],
    )


_memory: dict[int, tuple[float, UniversityGuide | None]] = {}
_lock = threading.Lock()


def get_guide(university_id: int, transport: httpx.BaseTransport | None = None) -> UniversityGuide | None:
    now = time.monotonic()
    with _lock:
        hit = _memory.get(university_id)
        if hit and now - hit[0] < MEMORY_TTL:
            return hit[1]
    candidates = [g for g in (_from_file(university_id), _from_cache(university_id, transport)) if g]
    guide = None
    if candidates:
        newest = max(candidates, key=lambda g: g.get("generated_at") or "")
        try:
            guide = to_contract(newest)
        except (KeyError, TypeError, ValueError) as e:
            log.error("university guide %d is malformed: %s", university_id, e)
        if guide is not None and not guide.sections:
            guide = None
    with _lock:
        _memory[university_id] = (now, guide)
    return guide


def clear_memory() -> None:
    with _lock:
        _memory.clear()
