"""Apify scan → ingest → Supabase upsert, and the /webhooks/apify route (no network)."""

import json
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.routers import webhooks
from app.services.radar import scan, sources
from app.services.radar.normalize import RadarItem
from app.services.radar.store import StoreError, StoreNotConfigured
from app.services.radar.store import candidates as real_candidates
from app.services.radar.store import upsert as real_upsert

client = TestClient(app)
DATASET = json.loads((Path(__file__).parent / "fixtures" / "radar" / "dataset-2026-10-24.json").read_text())
NOW = datetime(2026, 10, 24, 9, 0, tzinfo=timezone.utc)
CHEERIO_ID = "YrQuEkowkNCLdk4j2"
SECRET = {"X-Hindsight-Webhook-Secret": "s3cret"}


class FakeApify:
    def __init__(self, run=None, items=None):
        self.runs = {run.id: run} if run else {}
        self.items = items or []
        self.started: list[dict] = []

    def actor(self, name):
        assert name == "apify/cheerio-scraper"
        fake = self

        class _Actor:
            def get(self):
                return SimpleNamespace(id=CHEERIO_ID)

            def call(self, **kwargs):
                fake.started.append(kwargs)
                return next(iter(fake.runs.values()))

            def start(self, **kwargs):
                fake.started.append(kwargs)
                return SimpleNamespace(id="newrun1")

        return _Actor()

    def run(self, run_id):
        return SimpleNamespace(get=lambda: self.runs.get(run_id))

    def dataset(self, dataset_id):
        assert dataset_id == "ds1"
        return SimpleNamespace(iterate_items=lambda: iter(self.items))


def a_run(**overrides):
    return SimpleNamespace(**{"id": "run1", "act_id": CHEERIO_ID, "status": "SUCCEEDED",
                              "default_dataset_id": "ds1", **overrides})


def test_build_input_covers_campus_and_shared_sources():
    inp = scan.build_input(["sjsu"])
    ids = [u["userData"]["sourceId"] for u in inp["startUrls"]]
    assert ids == [s.id for s in sources.for_campus("sjsu")]
    assert all(u["userData"]["campus"] == "sjsu" for u in inp["startUrls"])
    mlh = next(u for u in inp["startUrls"] if u["userData"]["sourceId"] == "mlh-2027-california")
    assert mlh["userData"]["jsonSelector"] == "script[data-page=app]"
    assert "async function pageFunction" in inp["pageFunction"]
    assert inp["maxCrawlingDepth"] == 0
    both = scan.build_input(["sjsu", "berkeley"])["startUrls"]
    assert sum(u["userData"]["sourceId"] == "mlh-2027-california" for u in both) == 2  # once per campus


def test_ingest_run_normalizes_and_upserts(radar_fake):
    result = scan.ingest_run("run1", FakeApify(a_run(), DATASET), now=NOW)
    (sent,) = radar_fake.upserts
    assert result.stored == len(sent) > 0
    assert len({i.url for i in sent}) == len(sent)
    assert result.per_source["berkeley-devpost"] == 3


@pytest.mark.parametrize("run,error", [
    (a_run(act_id="someOtherActor"), "not a apify/cheerio-scraper run"),
    (a_run(status="FAILED"), "FAILED, not SUCCEEDED"),
])
def test_ingest_run_refuses_runs_it_should_not_trust(radar_fake, run, error):
    with pytest.raises(scan.ScanError, match=error):
        scan.ingest_run("run1", FakeApify(run, DATASET), now=NOW)
    assert radar_fake.upserts == []


def test_ingest_run_validates_id():
    with pytest.raises(scan.ScanError, match="Invalid"):
        scan.ingest_run("../../etc", FakeApify())
    with pytest.raises(scan.ScanError, match="not found"):
        scan.ingest_run("missing", FakeApify(a_run()))


def test_run_scan_waits_then_ingests(radar_fake):
    fake = FakeApify(a_run(), DATASET)
    result = scan.run_scan(["berkeley"], fake)
    assert result.run_id == "run1" and radar_fake.upserts
    assert fake.started[0]["force_permission_level"] == "LIMITED_PERMISSIONS"


def test_start_scan_attaches_secret_webhook():
    fake = FakeApify()
    run_id = scan.start_scan(["sjsu"], "https://api.example.edu/webhooks/apify", "s3cret", fake)
    (hook,) = fake.started[0]["webhooks"]
    assert run_id == "newrun1"
    assert hook["event_types"] == ["ACTOR.RUN.SUCCEEDED"]
    assert json.loads(hook["headers_template"]) == SECRET


def test_scan_needs_token():
    with pytest.raises(scan.ScanError, match="APIFY_TOKEN"):
        scan.client()


# ---- /webhooks/apify ----


def post_webhook(headers=None, **payload):
    body = {"eventType": "ACTOR.RUN.SUCCEEDED", "eventData": {"actorRunId": "run1"}, **payload}
    return client.post("/webhooks/apify", json=body, headers=headers or {})


@pytest.fixture
def ingested(monkeypatch):
    calls = []
    monkeypatch.setenv("APIFY_WEBHOOK_SECRET", "s3cret")
    monkeypatch.setattr(webhooks.scan, "ingest_run", lambda run_id: calls.append(run_id))
    return calls


def test_webhook_ingests_successful_run(ingested):
    res = post_webhook(SECRET)
    assert res.status_code == 200 and res.json() == {"ok": True}
    assert ingested == ["run1"]


def test_webhook_rejects_missing_or_wrong_secret(ingested):
    assert post_webhook().status_code == 401
    assert post_webhook({"X-Hindsight-Webhook-Secret": "nope"}).status_code == 401
    assert ingested == []


def test_webhook_disabled_without_configured_secret():
    assert post_webhook(SECRET).status_code == 503


def test_webhook_ignores_other_events_and_bad_ids(ingested):
    assert post_webhook(SECRET, eventType="ACTOR.RUN.FAILED").json() == {"ok": True}
    assert post_webhook(SECRET, eventData={"actorRunId": "../x"}).status_code == 422
    assert ingested == []


def test_webhook_ingest_failure_is_logged_not_raised(monkeypatch, caplog):
    def boom(run_id):
        raise scan.ScanError("Apify run run1 is FAILED")

    monkeypatch.setattr(webhooks.scan, "ingest_run", boom)
    webhooks._ingest("run1")
    assert "run1" in caplog.text


# ---- Supabase store (PostgREST shape) ----


ITEM = RadarItem(title="Cal Hacks 13.0", type="hackathon", org="Cal Hacks", campus="berkeley",
                 starts_at="2026-10-23T00:00:00-07:00", deadline="2026-10-25T00:00:00-07:00",
                 url="https://cal-hacks-13-0.devpost.com/", description="", tags=["hackathon"],
                 scraped_at=NOW.isoformat())


@pytest.fixture
def supabase_env(monkeypatch):
    monkeypatch.setenv("SUPABASE_URL", "https://proj.supabase.co/rest/v1/")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "sb_secret_test")


def test_upsert_dedupes_on_url(supabase_env):
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(201)

    assert real_upsert([ITEM], transport=httpx.MockTransport(handler)) == 1
    (req,) = seen
    assert str(req.url) == "https://proj.supabase.co/rest/v1/opportunities?on_conflict=url"
    assert req.headers["prefer"] == "resolution=merge-duplicates,return=minimal"
    assert req.headers["apikey"] == "sb_secret_test"
    (row,) = json.loads(req.content)
    assert "id" not in row and row["url"] == ITEM.url


def test_candidates_filters_campus_or_hackathon(supabase_env):
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params["or"] == "(campus.eq.sjsu,type.eq.hackathon)"
        return httpx.Response(200, json=[{"id": "1"}])

    assert real_candidates("sjsu", transport=httpx.MockTransport(handler)) == [{"id": "1"}]


def test_candidates_drop_hackathons_from_other_campus_event_sites(supabase_env):
    rows = [
        {"id": "1", "campus": "sjsu", "type": "event", "url": "https://events.sjsu.edu/e/1"},
        {"id": "2", "campus": "berkeley", "type": "hackathon", "url": "https://events.berkeley.edu/h/2"},
        {"id": "3", "campus": "berkeley", "type": "hackathon", "url": "https://calhacks.devpost.com/"},
    ]
    got = real_candidates("sjsu", transport=httpx.MockTransport(lambda r: httpx.Response(200, json=rows)))
    assert [r["id"] for r in got] == ["1", "3"]


def test_store_errors(supabase_env, monkeypatch):
    with pytest.raises(StoreError, match="409"):
        real_upsert([ITEM], transport=httpx.MockTransport(lambda r: httpx.Response(409, text="conflict")))
    monkeypatch.delenv("SUPABASE_URL")
    with pytest.raises(StoreNotConfigured):
        real_candidates("sjsu")
