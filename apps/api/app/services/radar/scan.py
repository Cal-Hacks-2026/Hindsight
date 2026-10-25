"""Campus scans on Apify (PROJECT.md §8.3, §10).

We run the Store actor apify/cheerio-scraper over data/sources.json with our own
pageFunction (extractors/page_function.js), then normalize and upsert the dataset. Two ways in:
- `run_scan(campus)`: start, wait, ingest. Used by `python -m app.scan`.
- `start_scan(campus, webhook_url)`: start with an ad-hoc webhook; Apify then POSTs
  /webhooks/apify, which calls `ingest_run(run_id)`.

`ingest_run` trusts nothing in the webhook body but the run id: it re-reads the run
with our token and only ingests a SUCCEEDED Cheerio Scraper run. Calling it again on
the same run re-extracts the same fetched pages with the extractors now on disk,
which is how the agent checks a patched extractor (apps/agent, DECISIONS.md D-006).
"""

import json
import logging
import os
import re
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Literal

from apify_client import ApifyClient
from apify_client.errors import ApifyApiError

from app.models.contracts import Campus
from app.services.radar import classify, extract, normalize, sources, store

log = logging.getLogger(__name__)

ACTOR = "apify/cheerio-scraper"
RUN_TIMEOUT = timedelta(minutes=10)
WEBHOOK_SECRET_HEADER = "X-Hindsight-Webhook-Secret"
RUN_ID = re.compile(r"^[A-Za-z0-9]{1,64}$")


class ScanError(Exception):
    pass


@dataclass
class ScanResult:
    run_id: str
    stored: int
    per_source: dict[str, int]
    skipped: dict[str, int]
    fetched: dict[str, int] = field(default_factory=dict)
    fetch_failed: dict[str, int] = field(default_factory=dict)
    parsed: dict[str, int] = field(default_factory=dict)
    errors: dict[str, str] = field(default_factory=dict)


SourceStatus = Literal["ok", "empty", "extractor_error", "fetch_failed", "missing"]


@dataclass
class SourceReport:
    source_id: str
    kind: str
    extractor: str  # path under extractors/
    status: SourceStatus
    parsed: int  # listings the extractor returned
    kept: int  # of those, items stored (current, http(s) URL, not a duplicate)
    error: str | None = None


def source_reports(result: ScanResult, campus: Campus) -> list[SourceReport]:
    """One row per source the campus scans. `empty` and `extractor_error` are what an
    extractor patch can fix; `fetch_failed` and `missing` (no page came back) are not."""
    out = []
    for s in sources.for_campus(campus):
        parsed = result.parsed.get(s.id, 0)
        if s.id in result.errors:
            status: SourceStatus = "extractor_error"
        elif not result.fetched.get(s.id):
            status = "missing"
        elif result.fetch_failed.get(s.id, 0) >= result.fetched[s.id]:
            status = "fetch_failed"
        else:
            status = "ok" if parsed else "empty"
        out.append(SourceReport(source_id=s.id, kind=s.kind, extractor=f"{s.kind}.py", status=status,
                                parsed=parsed, kept=result.per_source.get(s.id, 0), error=result.errors.get(s.id)))
    return out


@contextmanager
def _apify_errors():
    try:
        yield
    except ApifyApiError as e:
        raise ScanError(f"Apify: {e}") from e


def client() -> ApifyClient:
    token = os.getenv("APIFY_TOKEN")
    if not token:
        raise ScanError("APIFY_TOKEN is not set")
    return ApifyClient(token)


def build_input(campuses: list[Campus]) -> dict:
    start_urls, seen = [], set()
    for campus in campuses:
        for s in sources.for_campus(campus):
            key = (s.id, campus)
            if key in seen:
                continue
            seen.add(key)
            user_data = {"sourceId": s.id, "campus": campus}
            if s.json_selector:
                user_data["jsonSelector"] = s.json_selector
            start_urls.append({"url": str(s.url), "userData": user_data})
    return {
        "startUrls": start_urls,
        "pageFunction": extract.page_function(),
        # Feeds are JSON or RSS, not HTML; without these Cheerio Scraper rejects them.
        "additionalMimeTypes": ["application/json", "application/xml", "text/xml", "application/rss+xml"],
        "proxyConfiguration": {"useApifyProxy": True},
        "maxRequestRetries": 5,  # some campus sites 403 the first proxy IP they see
        "maxCrawlingDepth": 0,  # fetch exactly the listed URLs
        "maxConcurrency": 5,
    }


def _start_kwargs() -> dict:
    # Cheerio Scraper asks for full account access by default; it only needs its own storages.
    return {"run_timeout": RUN_TIMEOUT, "force_permission_level": "LIMITED_PERMISSIONS"}


def run_scan(campuses: list[Campus], apify: ApifyClient | None = None) -> ScanResult:
    apify = apify or client()
    with _apify_errors():
        run = apify.actor(ACTOR).call(run_input=build_input(campuses), **_start_kwargs())
    if run is None:
        raise ScanError("Apify run did not start")
    return ingest_run(run.id, apify)


def start_scan(campuses: list[Campus], webhook_url: str, secret: str,
               apify: ApifyClient | None = None) -> str:
    apify = apify or client()
    with _apify_errors():
        run = apify.actor(ACTOR).start(
            run_input=build_input(campuses),
            webhooks=[{
                "event_types": ["ACTOR.RUN.SUCCEEDED"],
                "request_url": webhook_url,
                "headers_template": json.dumps({WEBHOOK_SECRET_HEADER: secret}),
            }],
            **_start_kwargs(),
        )
    return run.id


def _actor_id(apify: ApifyClient) -> str:
    actor = apify.actor(ACTOR).get()
    if actor is None:
        raise ScanError(f"{ACTOR} not found on Apify")
    return actor.id


def _dataset(run_id: str, apify: ApifyClient | None) -> list[dict]:
    """The dataset of one of our SUCCEEDED Cheerio Scraper runs; anything else is refused."""
    if not RUN_ID.match(run_id):
        raise ScanError("Invalid Apify run id")
    apify = apify or client()
    with _apify_errors():
        run = apify.run(run_id).get()
        if run is None:
            raise ScanError(f"Apify run {run_id} not found")
        if run.act_id != _actor_id(apify):
            raise ScanError(f"Apify run {run_id} is not a {ACTOR} run")
        if run.status != "SUCCEEDED":
            raise ScanError(f"Apify run {run_id} is {run.status}, not SUCCEEDED")
        return list(apify.dataset(run.default_dataset_id).iterate_items())


def raw_items(run_id: str, source_id: str, apify: ApifyClient | None = None) -> list[dict]:
    """What page_function.js returned for one source in a run (for diagnosing an extractor)."""
    return [r for r in _dataset(run_id, apify) if r.get("sourceId") == source_id]


def _label_leftovers(campuses: list[Campus]) -> None:
    """One cached Claude batch for listings the category rules can't place. Never fails the scan."""
    try:
        rows = {str(r["id"]): r for c in campuses for r in store.candidates(c)}
        run = classify.label_leftovers(list(rows.values()))
        log.info("radar: labels: %d by rule, %d stored, %d new from Claude, %d by type",
                 run.by_rule, run.already_stored, run.by_claude, run.unlabeled)
    except store.StoreError as e:
        log.warning("radar: labeling skipped: %s", e)


def ingest_run(run_id: str, apify: ApifyClient | None = None, now: datetime | None = None) -> ScanResult:
    raw = _dataset(run_id, apify)
    result = normalize.normalize(raw, now or datetime.now(timezone.utc))
    stored = store.upsert(result.items) if result.items else 0
    if stored:
        _label_leftovers(sorted({i.campus for i in result.items}))
    log.info("radar: run %s → %d items stored; per source %s; skipped %s; extractor errors %s",
             run_id, stored, dict(result.per_source), dict(result.skipped), result.errors)
    return ScanResult(run_id=run_id, stored=stored, per_source=dict(result.per_source),
                      skipped=dict(result.skipped), fetched=dict(result.fetched),
                      fetch_failed=dict(result.fetch_failed), parsed=dict(result.parsed),
                      errors=dict(result.errors))
