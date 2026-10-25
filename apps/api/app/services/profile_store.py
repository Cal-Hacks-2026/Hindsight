"""`profiles` and `transcript_courses` in Supabase (PROJECT.md §9, DECISIONS.md D-004).

Only confirmed courses are stored; a transcript upload's unconfirmed rows live in
the browser until the student confirms them.
"""

import logging
import uuid

import httpx

from app.models import Course, CreateProfileRequest, Profile
from app.services.db import StoreError, client

LEGACY_PROFILE_COLUMNS = ("id,name,campus,sending_institution_id,receiving_institution_id,"
                          "majors,goals,interests,created_at")
# SKELETON: stage and minor need supabase/migrations/20261025_skeleton_profile_stage.sql.
SKELETON_FIELDS = ("stage", "minor")
PROFILE_COLUMNS = f"{LEGACY_PROFILE_COLUMNS},{','.join(SKELETON_FIELDS)}"
log = logging.getLogger(__name__)
COURSE_COLUMNS = "prefix,number,title,units,grade,term,academic_year_id,confirmed"


def _call(transport: httpx.BaseTransport | None, method: str, path: str, **kwargs) -> httpx.Response:
    try:
        with client(transport) as db:
            res = db.request(method, path, **kwargs)
            res.raise_for_status()
            return res
    except httpx.HTTPStatusError as e:
        raise StoreError(f"Supabase {method} {path} failed ({e.response.status_code}): "
                         f"{e.response.text[:200]}") from e
    except httpx.HTTPError as e:
        raise StoreError(f"Supabase unreachable: {e}") from e


def _missing_skeleton_column(e: StoreError) -> bool:
    """PostgREST's answer when the SKELETON migration isn't applied yet: 42703 on a select,
    PGRST204 on an insert, both naming the column."""
    text = str(e)
    return ("42703" in text or "PGRST204" in text) and any(f in text for f in SKELETON_FIELDS)


def _profiles(transport: httpx.BaseTransport | None, method: str, params: dict, **kwargs) -> httpx.Response:
    """Profiles keep working before the SKELETON migration is applied; stage and minor just
    aren't saved or returned until it is."""
    try:
        return _call(transport, method, "/profiles", params={**params, "select": PROFILE_COLUMNS}, **kwargs)
    except StoreError as e:
        if not _missing_skeleton_column(e):
            raise
        log.warning("profiles has no stage/minor columns yet; apply the SKELETON migration")
        if "json" in kwargs:
            kwargs["json"] = {k: v for k, v in kwargs["json"].items() if k not in SKELETON_FIELDS}
        return _call(transport, method, "/profiles", params={**params, "select": LEGACY_PROFILE_COLUMNS}, **kwargs)


def create_profile(body: CreateProfileRequest, transport: httpx.BaseTransport | None = None) -> Profile:
    """Postgres assigns the id and created_at."""
    res = _profiles(transport, "POST", {}, json=body.model_dump(exclude_none=True),
                    headers={"Prefer": "return=representation"})
    try:
        (row,) = res.json()
        return Profile(**row)
    except ValueError as e:
        raise StoreError(f"Supabase returned an unexpected profile: {e}") from e


def get_profile(profile_id: str, transport: httpx.BaseTransport | None = None) -> Profile | None:
    try:
        uuid.UUID(profile_id)
    except ValueError:
        return None  # PostgREST would 400 on a malformed uuid; to the client it's just not found.
    res = _profiles(transport, "GET", {"id": f"eq.{profile_id}"})
    rows = res.json()
    return Profile(**rows[0]) if rows else None


def replace_courses(profile_id: str, courses: list[Course],
                    transport: httpx.BaseTransport | None = None) -> None:
    """Insert the new set, then delete the profile's other rows, so a failed write never
    leaves the student with no courses."""
    ids = [str(uuid.uuid4()) for _ in courses]
    if courses:
        rows = [{"id": i, "profile_id": profile_id, **c.model_dump()} for i, c in zip(ids, courses)]
        _call(transport, "POST", "/transcript_courses", json=rows, headers={"Prefer": "return=minimal"})
    stale = {"profile_id": f"eq.{profile_id}"}
    if ids:
        stale["id"] = f"not.in.({','.join(ids)})"
    _call(transport, "DELETE", "/transcript_courses", params=stale, headers={"Prefer": "return=minimal"})


def confirmed_courses(profile_id: str, transport: httpx.BaseTransport | None = None) -> list[Course]:
    res = _call(transport, "GET", "/transcript_courses", params={
        "select": COURSE_COLUMNS,
        "profile_id": f"eq.{profile_id}",
        "confirmed": "is.true",
        "order": "term,prefix,number",
    })
    return [Course(**row) for row in res.json()]


def list_profiles(campus: str, limit: int = 200, transport: httpx.BaseTransport | None = None) -> list[Profile]:
    """Newest first; the agent ranks and alerts for each of these on its runs."""
    res = _profiles(transport, "GET", {"campus": f"eq.{campus}", "order": "created_at.desc", "limit": str(limit)})
    return [Profile(**row) for row in res.json()]
