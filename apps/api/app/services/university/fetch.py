"""Read a university's guide pages on Apify, the same way the Radar scans campus sites (D-002).

One Cheerio Scraper run fetches every source page with our pageFunction (page_function.js),
which returns the page's readable text. Pages that fail, redirect off the university's
sites, or come back nearly empty are left out, so nothing is written from them.
"""

import logging
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from apify_client import ApifyClient

from app.services.radar import scan
from app.services.university import sources

log = logging.getLogger(__name__)

PAGE_FUNCTION = Path(__file__).parent / "page_function.js"
MIN_TEXT = 200  # characters; less than this is a stub, an error page, or a JS-only app


@dataclass
class Page:
    source_id: str
    url: str
    title: str
    text: str
    retrieved_on: str  # YYYY-MM-DD


def build_input(university: sources.University) -> dict:
    return {
        "startUrls": [{"url": str(s.url), "userData": {"sourceId": s.id}} for s in university.sources],
        "pageFunction": PAGE_FUNCTION.read_text(),
        "proxyConfiguration": {"useApifyProxy": True},
        "maxRequestRetries": 5,  # some campus sites 403 the first proxy IP they see
        "maxCrawlingDepth": 0,  # fetch exactly the listed URLs
        "maxConcurrency": 5,
    }


def pages_from_dataset(items: list[dict], university: sources.University,
                       today: date | None = None) -> list[Page]:
    """Keep one usable page per listed source."""
    day = (today or date.today()).isoformat()
    allowed = {sources.host(str(s.url)) for s in university.sources}
    out: dict[str, Page] = {}
    for item in items:
        source = university.source(item.get("sourceId") or "")
        if source is None or source.id in out:
            continue
        loaded = item.get("loadedUrl") or item.get("url") or ""
        status, text = item.get("status"), (item.get("text") or "").strip()
        if sources.host(loaded) not in allowed:
            log.warning("university: %s redirected off-site to %s; skipped", source.id, loaded)
        elif status is not None and not 200 <= int(status) < 300:
            log.warning("university: %s returned %s; skipped", source.id, status)
        elif len(text) < MIN_TEXT:
            log.warning("university: %s has %d characters of text; skipped", source.id, len(text))
        else:
            out[source.id] = Page(source_id=source.id, url=str(source.url), title=source.title,
                                  text=text, retrieved_on=day)
    missing = [s.id for s in university.sources if s.id not in out]
    if missing:
        log.warning("university %d: no usable page for %s", university.id, missing)
    return [out[s.id] for s in university.sources if s.id in out]


def fetch_pages(university: sources.University, apify: ApifyClient | None = None) -> list[Page]:
    apify = apify or scan.client()
    with scan._apify_errors():
        run = apify.actor(scan.ACTOR).call(run_input=build_input(university), **scan._start_kwargs())
        if run is None:
            raise scan.ScanError("Apify run did not start")
        if run.status != "SUCCEEDED":
            raise scan.ScanError(f"Apify run {run.id} is {run.status}, not SUCCEEDED")
        items = list(apify.dataset(run.default_dataset_id).iterate_items())
    log.info("university %d: Apify run %s returned %d pages", university.id, run.id, len(items))
    return pages_from_dataset(items, university)
