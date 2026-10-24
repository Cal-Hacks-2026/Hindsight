"""Endpoints apps/agent calls on Droid's behalf (DECISIONS.md D-006). Not part of the
public contract (PROJECT.md §10): every request needs X-Agent-Secret = AGENT_SECRET,
and the agent is the only client."""

import hmac
import json
import os
from dataclasses import asdict
from typing import Any, Literal

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field

from app.models.contracts import Campus
from app.services import agent_events
from app.services.agent_client import SECRET_HEADER
from app.services.radar import alerts, scan, sources

MAX_RAW_TEXT = 8000
MAX_RAW_LIST = 3
MAX_RAW_STRING = 400


def require_agent_secret(secret: str | None = Header(None, alias=SECRET_HEADER)) -> None:
    expected = os.getenv("AGENT_SECRET")
    if not expected:
        raise HTTPException(status_code=503, detail="Agent endpoints not configured")
    if not secret or not hmac.compare_digest(secret, expected):
        raise HTTPException(status_code=401, detail="Bad agent secret")


router = APIRouter(prefix="/internal/agent", tags=["internal"], dependencies=[Depends(require_agent_secret)])


class CampusRequest(BaseModel):
    campus: Campus
    profile_id: str | None = None


class RescanRequest(BaseModel):
    campus: Campus
    apify_run_id: str


class EventRequest(BaseModel):
    run_id: str
    kind: Literal["plan", "step", "diff", "result", "error"]
    message: str = Field(max_length=agent_events.MAX_MESSAGE)
    payload: Any | None = None


def _scan_errors(fn, *args):
    try:
        return fn(*args)
    except scan.ScanError as e:
        raise HTTPException(status_code=502, detail=str(e)) from e


def _report(result: scan.ScanResult, campus: Campus) -> dict:
    return {"apify_run_id": result.run_id, "stored": result.stored, "skipped": result.skipped,
            "sources": [asdict(r) for r in scan.source_reports(result, campus)]}


@router.post("/scan")
def run_scan(body: CampusRequest) -> dict:
    """Scan the campus on Apify (waits for the run, a minute or two), store, and report per source."""
    return _report(_scan_errors(scan.run_scan, [body.campus]), body.campus)


@router.post("/rescan")
def rescan(body: RescanRequest) -> dict:
    """Re-extract an earlier run's fetched pages with the extractors now on disk."""
    return _report(_scan_errors(scan.ingest_run, body.apify_run_id), body.campus)


def preview(value: Any, depth: int = 0) -> Any:
    """Enough of a dataset item to see its shape: short strings, first few list entries."""
    if isinstance(value, str):
        return value if len(value) <= MAX_RAW_STRING else value[:MAX_RAW_STRING] + f"… (+{len(value) - MAX_RAW_STRING} chars)"
    if depth >= 8:
        return "…"
    if isinstance(value, list):
        head = [preview(v, depth + 1) for v in value[:MAX_RAW_LIST]]
        return head + ([f"… (+{len(value) - MAX_RAW_LIST} more)"] if len(value) > MAX_RAW_LIST else [])
    if isinstance(value, dict):
        return {k: preview(v, depth + 1) for k, v in list(value.items())[:80]}
    return value


def _raw_preview(item: dict) -> dict:
    out = {}
    for key, value in item.items():
        if key == "text" and isinstance(value, str):  # RSS/XML: the extractor needs the real markup
            out[key] = value[:MAX_RAW_TEXT]
        elif key in ("embeddedJson", "jsonLd") and isinstance(value, list):
            out[key] = [_blob(v) for v in value[:MAX_RAW_LIST]]
        else:
            out[key] = preview(value)
    return out


def _blob(text: Any) -> Any:
    """An embedded JSON string, parsed and trimmed; unparseable ones stay (trimmed) text."""
    try:
        return preview(json.loads(text))
    except (TypeError, ValueError):
        return str(text)[:MAX_RAW_TEXT]


@router.get("/raw")
def raw(apify_run_id: str, source_id: str) -> dict:
    """A trimmed view of what page_function.js returned for one source in a run."""
    source = sources.by_id(source_id)
    if source is None:
        raise HTTPException(status_code=404, detail="Unknown source")
    items = _scan_errors(scan.raw_items, apify_run_id, source_id)
    return {"source_id": source_id, "kind": source.kind, "extractor": f"{source.kind}.py",
            "url": str(source.url), "items": [_raw_preview(i) for i in items[:MAX_RAW_LIST]]}


def _profile_errors(fn, *args):
    try:
        return fn(*args)
    except alerts.UnknownProfile as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


@router.post("/rank")
def rank_profiles(body: CampusRequest) -> dict:
    """Re-rank the Radar feed for every profile on the campus (or one) and store it."""
    ranked = _profile_errors(alerts.rank_profiles, body.campus, body.profile_id)
    return {"profiles": [asdict(r) for r in ranked]}


@router.post("/alerts")
def write_alerts(body: CampusRequest) -> dict:
    """Mark top-ranked items due within 7 days as notified (alerts)."""
    written = _profile_errors(alerts.write_alerts, body.campus, body.profile_id)
    return {"alerts": [asdict(a) for a in written], "new": sum(a.new for a in written),
            "rule": f"top {alerts.ALERT_TOP_N} ranked, deadline or start within {alerts.ALERT_WINDOW.days} days"}


@router.post("/events")
def record_event(body: EventRequest) -> dict:
    try:
        agent_events.record(body.run_id, body.kind, body.message, body.payload)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
    return {"ok": True}
