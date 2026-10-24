"""Campus scans on Apify (PROJECT.md §8.3, §10).

We run the Store actor apify/cheerio-scraper over data/sources.json with our own
pageFunction (page_function.js), then normalize and upsert the dataset. Two ways in:
- `run_scan(campus)`: start, wait, ingest. Used by `python -m app.scan`.
- `start_scan(campus, webhook_url)`: start with an ad-hoc webhook; Apify then POSTs
  /webhooks/apify, which calls `ingest_run(run_id)`.

`ingest_run` trusts nothing in the webhook body but the run id: it re-reads the run
with our token and only ingests a SUCCEEDED Cheerio Scraper run.
"""

import json
import logging
import os
import re
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

from apify_client import ApifyClient
from apify_client.errors import ApifyApiError

from app.models.contracts import Campus
from app.services.radar import normalize, sources, store

log = logging.getLogger(__name__)

ACTOR = "apify/cheerio-scraper"
PAGE_FUNCTION = (Path(__file__).parent / "page_function.js").read_text()
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
        "pageFunction": PAGE_FUNCTION,
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


def ingest_run(run_id: str, apify: ApifyClient | None = None, now: datetime | None = None) -> ScanResult:
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
        raw = list(apify.dataset(run.default_dataset_id).iterate_items())

    result = normalize.normalize(raw, now or datetime.now(timezone.utc))
    stored = store.upsert(result.items) if result.items else 0
    log.info("radar: run %s → %d items stored; per source %s; skipped %s",
             run_id, stored, dict(result.per_source), dict(result.skipped))
    return ScanResult(run_id=run_id, stored=stored, per_source=dict(result.per_source),
                      skipped=dict(result.skipped))
