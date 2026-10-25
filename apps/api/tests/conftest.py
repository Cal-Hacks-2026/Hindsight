import uuid
from datetime import datetime, timezone

import pytest

from app.services import claude_limits
from app.services.assist import limits as assist_limits
from app.services.assist import set_service
from tests.assist_fake import FakeAssist, fake_service


@pytest.fixture(autouse=True)
def fresh_claude_limiter(monkeypatch):
    """Every test starts with empty rate-limit state (TestClient always uses one IP)."""
    limiter = claude_limits.ClaudeLimiter(per_ip_per_min=10, daily_cap=500)
    monkeypatch.setattr(claude_limits, "limiter", limiter)
    return limiter


@pytest.fixture(autouse=True)
def fresh_profile_limiter(monkeypatch):
    from app.services import profile_limits

    limiter = claude_limits.ClaudeLimiter(per_ip_per_min=profile_limits.PER_IP_PER_MIN, daily_cap=0)
    monkeypatch.setattr(profile_limits, "limiter", limiter)
    return limiter


@pytest.fixture(autouse=True)
def fresh_assist_limiter(monkeypatch):
    limiter = claude_limits.ClaudeLimiter(per_ip_per_min=assist_limits.PER_IP_PER_MIN, daily_cap=0)
    monkeypatch.setattr(assist_limits, "limiter", limiter)
    return limiter


@pytest.fixture(autouse=True)
def assist_fake() -> FakeAssist:
    """No test talks to the real assist.org unless it opts in (see test_assist_live)."""
    service, fake = fake_service()
    set_service(service)
    yield fake
    set_service(None)


@pytest.fixture(autouse=True)
def ge_store(assist_fake):
    """GE lists come from the fake ASSIST and stay in memory (no Supabase)."""
    from app.services import ge
    from app.services.assist import get_service

    store = ge.GeListStore(get_service().client)
    ge.set_store(store)
    yield store
    ge.set_store(None)


@pytest.fixture(autouse=True)
def no_saved_schedule(monkeypatch):
    """/plan reads the saved class schedule; with no fake in place, nobody has one (no Supabase)."""
    from app.services.schedule import store

    monkeypatch.setattr(store, "schedule", lambda profile_id, transport=None: [])


class FakeRadarStore:
    """Stands in for Supabase `opportunities`; rows look like PostgREST's."""

    def __init__(self):
        self.rows: list[dict] = []
        self.upserts: list[list] = []
        self.ranked: dict[str, list] = {}
        self.notified: dict[str, set[str]] = {}
        self.labels: dict[str, dict] = {}  # opportunity_labels, by opportunity_id

    def candidates(self, campus, transport=None):
        return [r for r in self.rows if r["campus"] == campus or r["type"] == "hackathon"]

    def upsert(self, items, transport=None):
        self.upserts.append(items)
        return len(items)

    def record_ranked(self, profile_id, items, transport=None):
        self.ranked[profile_id] = items
        return len(items)

    def notified_ids(self, profile_id, transport=None):
        return self.notified.get(profile_id, set())

    def read_labels(self, opportunity_ids, transport=None):
        return [self.labels[i] for i in opportunity_ids if i in self.labels]

    def save_labels(self, rows, transport=None):
        self.labels.update({r["opportunity_id"]: r for r in rows})
        return len(rows)


@pytest.fixture(autouse=True)
def radar_fake(monkeypatch) -> FakeRadarStore:
    """No test reaches Supabase, Apify, or Claude for the Radar unless it opts in."""
    from app.services.radar import classify, rank, store

    fake = FakeRadarStore()
    monkeypatch.setattr(store, "candidates", fake.candidates)
    monkeypatch.setattr(store, "upsert", fake.upsert)
    monkeypatch.setattr(store, "record_ranked", fake.record_ranked)
    monkeypatch.setattr(store, "notified_ids", fake.notified_ids)
    monkeypatch.setattr(store, "labels", fake.read_labels)
    monkeypatch.setattr(store, "save_labels", fake.save_labels)

    def no_claude(profile, items):
        raise AssertionError("test called Claude without faking rank.ask_claude")

    monkeypatch.setattr(rank, "ask_claude", no_claude)

    def no_claude_labels(rows):
        raise AssertionError("test called Claude without faking classify.ask_claude")

    monkeypatch.setattr(classify, "ask_claude", no_claude_labels)
    monkeypatch.setattr(rank, "reason_cache", rank._ReasonCache())
    monkeypatch.delenv("APIFY_TOKEN", raising=False)
    monkeypatch.delenv("APIFY_WEBHOOK_SECRET", raising=False)
    return fake


class FakeProfileStore:
    """Stands in for Supabase `profiles` and `transcript_courses`."""

    def __init__(self):
        self.profiles: dict = {}
        self.courses: dict[str, list] = {}

    def create_profile(self, body, transport=None):
        from app.models import Profile

        profile = Profile(id=str(uuid.uuid4()), created_at=datetime.now(timezone.utc).isoformat(),
                          **body.model_dump())
        self.profiles[profile.id] = profile
        return profile

    def get_profile(self, profile_id, transport=None):
        return self.profiles.get(profile_id)

    def replace_courses(self, profile_id, courses, transport=None):
        self.courses[profile_id] = list(courses)

    def confirmed_courses(self, profile_id, transport=None):
        return [c for c in self.courses.get(profile_id, []) if c.confirmed]


@pytest.fixture(autouse=True)
def profile_fake(monkeypatch) -> FakeProfileStore:
    """No test reaches Supabase for profiles unless it opts in (see test_profile_store)."""
    from app.services import profile_store

    fake = FakeProfileStore()
    for name in ("create_profile", "get_profile", "replace_courses", "confirmed_courses"):
        monkeypatch.setattr(profile_store, name, getattr(fake, name))
    return fake


class FakeCounselorClaude:
    """Stands in for `anthropic.Anthropic()` in the counselor. Each scripted step is a
    function of the request kwargs that returns a parse() response (see test_counselor)."""

    def __init__(self):
        self.steps: list = []
        self.requests: list[dict] = []
        self.beta = self
        self.messages = self

    def parse(self, **kwargs):
        # Snapshot: the counselor appends to the same list after each call.
        self.requests.append({**kwargs, "messages": list(kwargs["messages"])})
        if not self.steps:
            raise AssertionError("counselor called Claude more times than the test scripted")
        return self.steps.pop(0)(kwargs)


@pytest.fixture(autouse=True)
def counselor_claude(monkeypatch) -> FakeCounselorClaude:
    """No test reaches Claude for the counselor; tests script its responses."""
    from app.services import counselor

    fake = FakeCounselorClaude()
    monkeypatch.setattr(counselor, "_client", lambda: fake)
    return fake


class FakeAgent:
    """Stands in for Supabase `agent_events` and for apps/agent (agent_client.start_run's HTTP call)."""

    def __init__(self):
        self.events: list[dict] = []
        self.started: list[dict] = []

    def record(self, run_id, kind, message, payload=None, transport=None):
        from app.services.agent_events import _is_uuid

        if not _is_uuid(run_id):
            raise ValueError("run_id must be a UUID")
        self.events.append({"run_id": run_id, "kind": kind, "message": message, "payload": payload,
                            "created_at": datetime.now(timezone.utc).isoformat()})

    def for_run(self, run_id, transport=None):
        from app.models import AgentEvent

        return [AgentEvent(**e) for e in self.events if e["run_id"] == run_id]

    def latest_run_id(self, campus, transport=None):
        from app.services.agent_events import PUBLIC_TRIGGERS

        tagged = [e for e in self.events if isinstance(e["payload"], dict) and e["payload"].get("campus") == campus
                  and e["payload"].get("trigger") in PUBLIC_TRIGGERS]
        return tagged[-1]["run_id"] if tagged else None


@pytest.fixture(autouse=True)
def agent_fake(monkeypatch) -> FakeAgent:
    """No test writes agent_events to Supabase or reaches apps/agent unless it opts in."""
    import httpx

    from app.services import agent_client, agent_events

    fake = FakeAgent()
    monkeypatch.setattr(agent_events, "record", fake.record)
    monkeypatch.setattr(agent_events, "for_run", fake.for_run)
    monkeypatch.setattr(agent_events, "latest_run_id", fake.latest_run_id)
    monkeypatch.delenv("AGENT_SECRET", raising=False)
    monkeypatch.delenv("AGENT_URL", raising=False)

    def agent_app(request: httpx.Request) -> httpx.Response:
        import json

        fake.started.append(json.loads(request.content))
        return httpx.Response(202, json={"run_id": fake.started[-1]["run_id"]})

    real_start = agent_client.start_run
    monkeypatch.setattr(agent_client, "start_run",
                        lambda *a, transport=None, **kw: real_start(
                            *a, transport=transport or httpx.MockTransport(agent_app), **kw))
    return fake
