"""`agent_events` in Supabase (PROJECT.md §9): the Droid run log behind /agent/events."""

import json
import uuid
from typing import Any

import httpx

from app.models import AgentEvent
from app.services.db import StoreError, client

MAX_MESSAGE = 2000
MAX_PAYLOAD_BYTES = 100_000  # a diff of one extractor fits comfortably
MAX_EVENTS = 500


def _is_uuid(value: str) -> bool:
    try:
        uuid.UUID(value)
    except ValueError:
        return False
    return True


def _bounded(payload: Any) -> Any:
    if payload is None:
        return None
    text = json.dumps(payload, default=str)
    if len(text.encode()) <= MAX_PAYLOAD_BYTES:
        return payload
    return {"truncated": True, "preview": text[:MAX_PAYLOAD_BYTES // 2]}


def record(run_id: str, kind: str, message: str, payload: Any = None,
           transport: httpx.BaseTransport | None = None) -> None:
    if not _is_uuid(run_id):
        raise ValueError("run_id must be a UUID")
    row = {"run_id": run_id, "kind": kind, "message": message[:MAX_MESSAGE], "payload": _bounded(payload)}
    try:
        with client(transport) as db:
            db.post("/agent_events", json=row, headers={"Prefer": "return=minimal"}).raise_for_status()
    except httpx.HTTPStatusError as e:
        raise StoreError(f"Supabase insert failed ({e.response.status_code}): {e.response.text[:200]}") from e
    except httpx.HTTPError as e:
        raise StoreError(f"Supabase unreachable: {e}") from e


def for_run(run_id: str, transport: httpx.BaseTransport | None = None) -> list[AgentEvent]:
    """Oldest first. A malformed run id has no events (PostgREST would 400 on it)."""
    if not _is_uuid(run_id):
        return []
    try:
        with client(transport) as db:
            res = db.get("/agent_events", params={
                "select": "run_id,kind,message,payload,created_at",
                "run_id": f"eq.{run_id}",
                "order": "created_at.asc",
                "limit": str(MAX_EVENTS),
            })
            res.raise_for_status()
            return [AgentEvent(**{**row, "message": row.get("message") or ""}) for row in res.json()]
    except httpx.HTTPStatusError as e:
        raise StoreError(f"Supabase read failed ({e.response.status_code})") from e
    except (httpx.HTTPError, ValueError) as e:
        raise StoreError(f"Supabase unreachable: {e}") from e


# Campus-wide scans only: a profile_created run logs one student's ranked listings and alerts,
# and anyone can call /agent/runs/latest.
PUBLIC_TRIGGERS = ("manual", "schedule")


def latest_run_id(campus: str, transport: httpx.BaseTransport | None = None) -> str | None:
    """The newest scan run for a campus. apps/agent opens every run with a step whose payload
    names its trigger and campus ("Run started: …"), so that row identifies it."""
    try:
        with client(transport) as db:
            res = db.get("/agent_events", params={
                "select": "run_id",
                "payload->>campus": f"eq.{campus}",
                "payload->>trigger": f"in.({','.join(PUBLIC_TRIGGERS)})",
                "order": "created_at.desc",
                "limit": "1",
            })
            res.raise_for_status()
            rows = res.json()
    except httpx.HTTPStatusError as e:
        raise StoreError(f"Supabase read failed ({e.response.status_code})") from e
    except (httpx.HTTPError, ValueError) as e:
        raise StoreError(f"Supabase unreachable: {e}") from e
    return str(rows[0]["run_id"]) if rows else None
