import pytest

from app.services import claude_limits
from app.services.assist import set_service
from tests.assist_fake import FakeAssist, fake_service


@pytest.fixture(autouse=True)
def fresh_claude_limiter(monkeypatch):
    """Every test starts with empty rate-limit state (TestClient always uses one IP)."""
    limiter = claude_limits.ClaudeLimiter(per_ip_per_min=10, daily_cap=500)
    monkeypatch.setattr(claude_limits, "limiter", limiter)
    return limiter


@pytest.fixture(autouse=True)
def assist_fake() -> FakeAssist:
    """No test talks to the real assist.org unless it opts in (see test_assist_live)."""
    service, fake = fake_service()
    set_service(service)
    yield fake
    set_service(None)
