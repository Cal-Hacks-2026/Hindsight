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

    def candidates(self, campus, transport=None):
        return [r for r in self.rows if r["campus"] == campus or r["type"] == "hackathon"]

    def upsert(self, items, transport=None):
        self.upserts.append(items)
        return len(items)


@pytest.fixture(autouse=True)
def radar_fake(monkeypatch) -> FakeRadarStore:
    """No test reaches Supabase, Apify, or Claude for the Radar unless it opts in."""
    from app.services.radar import rank, store

    fake = FakeRadarStore()
    monkeypatch.setattr(store, "candidates", fake.candidates)
    monkeypatch.setattr(store, "upsert", fake.upsert)

    def no_claude(profile, items):
        raise AssertionError("test called Claude without faking rank.ask_claude")

    monkeypatch.setattr(rank, "ask_claude", no_claude)
    monkeypatch.setattr(rank, "reason_cache", rank._ReasonCache())
    monkeypatch.delenv("APIFY_TOKEN", raising=False)
    monkeypatch.delenv("APIFY_WEBHOOK_SECRET", raising=False)
    return fake
