import pytest

from app.services import claude_limits


@pytest.fixture(autouse=True)
def fresh_claude_limiter(monkeypatch):
    """Every test starts with empty rate-limit state (TestClient always uses one IP)."""
    limiter = claude_limits.ClaudeLimiter(per_ip_per_min=10, daily_cap=500)
    monkeypatch.setattr(claude_limits, "limiter", limiter)
    return limiter
