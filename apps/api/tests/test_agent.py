"""/agent/run, /agent/events, the profile-created trigger, and /internal/agent/* (DECISIONS.md D-006)."""

import json
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.models import AgentEventsResponse, AgentRunResponse
from app.services import agent_client
from app.services.agent_events import for_run as real_for_run
from app.services.agent_events import record as real_record
from app.services.radar import alerts, scan, store
from app.services.radar.normalize import RadarItem
from tests.test_radar_scan import CHEERIO_ID, DATASET, NOW, FakeApify, a_run

client = TestClient(app)
SECRET = {"X-Agent-Secret": "agent-s3cret"}
PROFILE = {"name": "Test Student", "campus": "sjsu", "sending_institution_id": 113,
           "receiving_institution_id": 39, "majors": ["Data Science, B.S."], "goals": "", "interests": ["ai"]}


@pytest.fixture
def agent_env(monkeypatch):
    monkeypatch.setenv("AGENT_SECRET", "agent-s3cret")


# ---- public contract: /agent/run, /agent/events ----


def test_run_without_agent_secret_logs_why(agent_fake):
    run_id = AgentRunResponse.model_validate(client.post("/agent/run", json={"campus": "sjsu"}).json()).run_id
    assert agent_fake.started == []
    events = AgentEventsResponse.model_validate(client.get("/agent/events", params={"run_id": run_id}).json()).events
    assert [(e.kind, "AGENT_SECRET" in e.message) for e in events] == [("error", True)]


def test_run_queues_on_the_agent(agent_fake, agent_env):
    res = client.post("/agent/run", json={"campus": "berkeley"})
    assert res.status_code == 200 and set(res.json()) == {"run_id"}
    (started,) = agent_fake.started
    assert started == {"run_id": res.json()["run_id"], "campus": "berkeley", "trigger": "manual", "profile_id": None}
    uuid.UUID(res.json()["run_id"])


def test_run_returns_the_id_of_a_pending_identical_run(agent_env):
    pending = str(uuid.uuid4())
    transport = httpx.MockTransport(lambda r: httpx.Response(202, json={"run_id": pending}))
    assert agent_client.start_run(str(uuid.uuid4()), "sjsu", "manual", transport=transport) == pending


@pytest.mark.parametrize("response,expected", [
    (httpx.Response(429, json={"detail": "queue full"}), "queue is full"),
    (httpx.Response(401), "answered 401"),
])
def test_refused_run_becomes_an_error_event(agent_fake, agent_env, response, expected):
    run_id = str(uuid.uuid4())
    assert agent_client.start_run(run_id, "sjsu", "manual", transport=httpx.MockTransport(lambda r: response)) == run_id
    assert expected in agent_fake.events[-1]["message"] and agent_fake.events[-1]["kind"] == "error"


def test_unreachable_agent_becomes_an_error_event(agent_fake, agent_env):
    def down(request):
        raise httpx.ConnectError("refused")

    run_id = str(uuid.uuid4())
    agent_client.start_run(run_id, "sjsu", "manual", transport=httpx.MockTransport(down))
    assert agent_fake.events[-1]["message"] == "The agent service is not reachable."


def test_events_for_a_malformed_run_id_are_empty():
    assert client.get("/agent/events", params={"run_id": "not-a-uuid"}).json() == {"events": []}


def test_new_profile_triggers_a_run(agent_fake, agent_env):
    profile = client.post("/profiles", json=PROFILE).json()["profile"]
    (started,) = agent_fake.started
    assert started["trigger"] == "profile_created" and started["profile_id"] == profile["id"]
    assert started["campus"] == "sjsu"


def test_profile_is_created_even_when_the_agent_is_down(agent_fake, caplog):
    res = client.post("/profiles", json=PROFILE)  # AGENT_SECRET unset
    assert res.status_code == 200
    assert agent_fake.events == []  # no orphan error rows for a run id nobody holds
    assert "profile_created run" in caplog.text


# ---- /internal/agent/* ----


def test_internal_endpoints_need_the_secret(agent_env):
    assert client.post("/internal/agent/scan", json={"campus": "sjsu"}).status_code == 401
    assert client.post("/internal/agent/scan", json={"campus": "sjsu"},
                       headers={"X-Agent-Secret": "wrong"}).status_code == 401


def test_internal_endpoints_disabled_without_secret():
    assert client.post("/internal/agent/events", json={}, headers=SECRET).status_code == 503


def test_scan_reports_every_source(monkeypatch, agent_env, radar_fake):
    apify = FakeApify(a_run(), DATASET)
    monkeypatch.setattr(scan, "client", lambda: apify)
    monkeypatch.setattr(scan.normalize, "normalize", _at_now(scan.normalize.normalize))
    report = client.post("/internal/agent/scan", json={"campus": "sjsu"}, headers=SECRET).json()
    assert report["apify_run_id"] == "run1" and report["stored"] > 0
    by_id = {r["source_id"]: r for r in report["sources"]}
    assert set(by_id) == {s.id for s in scan.sources.for_campus("sjsu")}
    assert by_id["sjsu-events-ai-tech"]["status"] == "ok" and by_id["sjsu-events-ai-tech"]["extractor"] == "localist.py"
    assert by_id["sjsu-events-workshops"]["status"] == "missing"  # not in the trimmed fixture


def _at_now(normalize_fn):
    return lambda raw, now: normalize_fn(raw, NOW)


def test_rescan_reextracts_with_the_extractors_on_disk(monkeypatch, agent_env, radar_fake):
    """The self-healing check: same Apify run, re-read, re-extracted."""
    broken = [dict(r, json={"renamed": r.get("json")}) if r["sourceId"] == "sjsu-events-ai-tech" else r
              for r in DATASET]
    apify = FakeApify(a_run(), broken)
    monkeypatch.setattr(scan, "client", lambda: apify)
    monkeypatch.setattr(scan.normalize, "normalize", _at_now(scan.normalize.normalize))
    body = {"campus": "sjsu", "apify_run_id": "run1"}
    report = client.post("/internal/agent/rescan", json=body, headers=SECRET).json()
    assert {r["source_id"]: r["status"] for r in report["sources"]}["sjsu-events-ai-tech"] == "empty"


def test_rescan_rejects_bad_run_ids(agent_env):
    res = client.post("/internal/agent/rescan", json={"campus": "sjsu", "apify_run_id": "../x"}, headers=SECRET)
    assert res.status_code == 502 and "Invalid" in res.json()["detail"]


def test_source_reports_statuses():
    result = scan.ScanResult(run_id="r", stored=0, per_source={"a": 2}, skipped={},
                             fetched={"a": 1, "b": 1, "c": 1, "d": 1}, fetch_failed={"c": 1},
                             parsed={"a": 3}, errors={"d": "localist.py: SyntaxError"})
    srcs = [SimpleNamespace(id=i, kind="localist") for i in "abcde"]
    orig = scan.sources.for_campus
    scan.sources.for_campus = lambda campus: srcs
    try:
        got = {r.source_id: (r.status, r.parsed, r.kept) for r in scan.source_reports(result, "sjsu")}
    finally:
        scan.sources.for_campus = orig
    assert got == {"a": ("ok", 3, 2), "b": ("empty", 0, 0), "c": ("fetch_failed", 0, 0),
                   "d": ("extractor_error", 0, 0), "e": ("missing", 0, 0)}


def test_raw_shows_a_trimmed_page(monkeypatch, agent_env):
    monkeypatch.setattr(scan, "client", lambda: FakeApify(a_run(), DATASET))
    res = client.get("/internal/agent/raw", params={"apify_run_id": "run1", "source_id": "sjsu-events-ai-tech"},
                     headers=SECRET).json()
    assert res["extractor"] == "localist.py"
    (item,) = res["items"]
    events = item["json"]["events"]
    assert len(events) <= 4 and (len(events) < 4 or events[-1].startswith("… (+"))
    assert len(json.dumps(res)) < 60_000


def test_raw_unknown_source(agent_env):
    res = client.get("/internal/agent/raw", params={"apify_run_id": "run1", "source_id": "nope"}, headers=SECRET)
    assert res.status_code == 404


def test_events_endpoint_records(agent_fake, agent_env):
    run_id = str(uuid.uuid4())
    body = {"run_id": run_id, "kind": "diff", "message": "Patched localist.py", "payload": {"diff": "--- a\n+++ b"}}
    assert client.post("/internal/agent/events", json=body, headers=SECRET).json() == {"ok": True}
    events = client.get("/agent/events", params={"run_id": run_id}).json()["events"]
    assert events[0]["kind"] == "diff" and events[0]["payload"] == {"diff": "--- a\n+++ b"}
    bad = client.post("/internal/agent/events", json={**body, "run_id": "x"}, headers=SECRET)
    assert bad.status_code == 422
    assert client.post("/internal/agent/events", json={**body, "kind": "chat"}, headers=SECRET).status_code == 422


def test_rank_and_alerts_for_one_profile(monkeypatch, agent_env, radar_fake, profile_fake):
    from app.services.radar import rank

    pid = client.post("/profiles", json=PROFILE).json()["profile"]["id"]
    soon = (datetime.now(timezone.utc) + timedelta(days=3)).isoformat()
    radar_fake.rows = [{"id": str(uuid.uuid4()), "campus": "sjsu", "type": "workshop", "title": "AI workshop",
                        "org": "SJSU", "starts_at": soon, "deadline": None, "url": "https://events.sjsu.edu/ai",
                        "description": "ai", "tags": ["ai"], "scraped_at": soon}]
    monkeypatch.setattr(rank, "ask_claude", lambda profile, items: {})
    ranked = client.post("/internal/agent/rank", json={"campus": "sjsu", "profile_id": pid}, headers=SECRET).json()
    assert ranked["profiles"][0]["ranked"] == 1 and len(radar_fake.ranked[pid]) == 1
    assert pid not in json.dumps(ranked)  # profile ids are bearer tokens; this reaches the public log

    marked = []
    monkeypatch.setattr(store, "top_ranked", lambda profile_id, limit: [
        {"opportunity_id": radar_fake.rows[0]["id"], "score": 1.0, "notified": False,
         "opportunities": {"title": "AI workshop", "url": "https://events.sjsu.edu/ai", "starts_at": soon}}])
    monkeypatch.setattr(store, "mark_notified", lambda profile_id, ids: marked.append(ids) or len(ids))
    res = client.post("/internal/agent/alerts", json={"campus": "sjsu", "profile_id": pid}, headers=SECRET).json()
    assert res["new"] == 1 and marked == [[radar_fake.rows[0]["id"]]]
    assert pid not in json.dumps(res)
    assert "within 7 days" in res["rule"]


def test_rank_unknown_or_other_campus_profile(agent_env, profile_fake):
    pid = client.post("/profiles", json=PROFILE).json()["profile"]["id"]
    assert client.post("/internal/agent/rank", json={"campus": "berkeley", "profile_id": pid},
                       headers=SECRET).status_code == 404


# ---- alerts rule ----


def _row(oid, notified=False, **opp):
    return {"opportunity_id": oid, "score": 1.0, "notified": notified, "opportunities": {"title": oid, "url": "", **opp}}


def test_due_within_uses_deadline_then_start():
    now = datetime(2026, 10, 24, tzinfo=timezone.utc)
    assert alerts.due_within(_row("a", deadline="2026-10-30T00:00:00Z"), now)
    assert alerts.due_within(_row("b", deadline="2026-11-05T00:00:00Z", starts_at="2026-10-25T00:00:00Z"), now) is None
    assert alerts.due_within(_row("c", starts_at="2026-10-31T00:00:00Z"), now)
    assert alerts.due_within(_row("d", starts_at="2026-10-23T00:00:00Z"), now) is None  # already past
    assert alerts.due_within(_row("e"), now) is None


def test_write_alerts_only_marks_new_rows(monkeypatch, profile_fake):
    from app.models import CreateProfileRequest

    profile = profile_fake.create_profile(CreateProfileRequest(**PROFILE))
    now = datetime(2026, 10, 24, tzinfo=timezone.utc)
    rows = [_row("a", deadline="2026-10-26T00:00:00Z"), _row("b", notified=True, starts_at="2026-10-27T00:00:00Z"),
            _row("c", deadline="2026-12-01T00:00:00Z")]
    marked = []
    monkeypatch.setattr(store, "top_ranked", lambda pid, limit: rows[:limit])
    monkeypatch.setattr(store, "mark_notified", lambda pid, ids: marked.append(ids) or len(ids))
    monkeypatch.setattr(alerts.profile_store, "list_profiles", lambda campus, limit: [profile])
    got = alerts.write_alerts("sjsu", now=now)
    assert [(a.opportunity_id, a.new) for a in got] == [("a", True), ("b", False)]
    assert marked == [["a"]]


# ---- Supabase shapes (PostgREST) ----


@pytest.fixture
def supabase_env(monkeypatch):
    monkeypatch.setenv("SUPABASE_URL", "https://proj.supabase.co")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "sb_secret_test")


def test_record_and_read_events(supabase_env):
    seen = []

    def handler(request):
        seen.append(request)
        if request.method == "POST":
            return httpx.Response(201)
        return httpx.Response(200, json=[{"run_id": "r", "kind": "step", "message": None, "payload": None,
                                          "created_at": "2026-10-24T09:00:00+00:00"}])

    run_id = str(uuid.uuid4())
    real_record(run_id, "step", "x" * 5000, {"big": "y" * 200_000}, transport=httpx.MockTransport(handler))
    row = json.loads(seen[0].content)
    assert len(row["message"]) == 2000 and row["payload"]["truncated"] is True
    (event,) = real_for_run(run_id, transport=httpx.MockTransport(handler))
    assert event.message == "" and seen[1].url.params["run_id"] == f"eq.{run_id}"
    assert real_for_run("nope") == []
    with pytest.raises(ValueError):
        real_record("nope", "step", "x")


def test_mark_notified_and_top_ranked_shapes(supabase_env):
    seen = []

    def handler(request):
        seen.append(request)
        return httpx.Response(200, json=[]) if request.method == "GET" else httpx.Response(204)

    t = httpx.MockTransport(handler)
    assert store.mark_notified("p1", [], transport=t) == 0 and seen == []
    assert store.mark_notified("p1", ["o1", "o2"], transport=t) == 2
    assert seen[0].method == "PATCH" and seen[0].url.params["opportunity_id"] == "in.(o1,o2)"
    assert json.loads(seen[0].content) == {"notified": True}
    store.top_ranked("p1", 5, transport=t)
    assert "opportunities(" in seen[1].url.params["select"] and seen[1].url.params["order"] == "score.desc"
