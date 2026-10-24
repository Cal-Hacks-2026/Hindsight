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


class FakeRadarStore:
    """Stands in for Supabase `opportunities`; rows look like PostgREST's."""

    def __init__(self):
        self.rows: list[dict] = []
        self.upserts: list[list] = []
        self.ranked: dict[str, list] = {}

    def candidates(self, campus, transport=None):
        return [r for r in self.rows if r["campus"] == campus or r["type"] == "hackathon"]

    def upsert(self, items, transport=None):
        self.upserts.append(items)
        return len(items)

    def record_ranked(self, profile_id, items, transport=None):
        self.ranked[profile_id] = items
        return len(items)


@pytest.fixture(autouse=True)
def radar_fake(monkeypatch) -> FakeRadarStore:
    """No test reaches Supabase, Apify, or Claude for the Radar unless it opts in."""
    from app.services.radar import rank, store

    fake = FakeRadarStore()
    monkeypatch.setattr(store, "candidates", fake.candidates)
    monkeypatch.setattr(store, "upsert", fake.upsert)
    monkeypatch.setattr(store, "record_ranked", fake.record_ranked)

    def no_claude(profile, items):
        raise AssertionError("test called Claude without faking rank.ask_claude")

    monkeypatch.setattr(rank, "ask_claude", no_claude)
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
