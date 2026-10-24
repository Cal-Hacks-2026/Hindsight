"""Claude rate limits: per-IP rolling minute, global UTC-day cap, 429 + CORS exposure."""

from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services import claude_limits, transcript
from app.services.claude_limits import ClaudeLimiter, RateLimited
from app.services.transcript import _Row

from .test_contract import make_profile

client = TestClient(app)
NOON = datetime(2026, 10, 24, 12, tzinfo=timezone.utc).timestamp()


class Clock:
    def __init__(self, t: float):
        self.t = t

    def __call__(self) -> float:
        return self.t


def test_per_ip_rolling_window():
    clock = Clock(NOON)
    lim = ClaudeLimiter(per_ip_per_min=2, daily_cap=100, clock=clock)
    lim.check_ip("1.1.1.1")
    clock.t += 30
    lim.check_ip("1.1.1.1")
    with pytest.raises(RateLimited) as e:
        lim.check_ip("1.1.1.1")
    assert e.value.retry_after == 31
    lim.check_ip("2.2.2.2")  # other IPs unaffected
    clock.t += 31  # first hit has aged out
    lim.check_ip("1.1.1.1")


def test_daily_cap_resets_at_utc_midnight():
    clock = Clock(NOON)
    lim = ClaudeLimiter(per_ip_per_min=100, daily_cap=2, clock=clock)
    lim.take_daily()
    lim.take_daily()
    with pytest.raises(RateLimited) as e:
        lim.take_daily()
    assert e.value.retry_after == 12 * 3600 + 1
    clock.t += 12 * 3600
    lim.take_daily()


def test_from_env(monkeypatch):
    monkeypatch.setenv("CLAUDE_PER_IP_PER_MIN", "3")
    monkeypatch.setenv("CLAUDE_DAILY_CAP", "7")
    lim = ClaudeLimiter.from_env()
    assert (lim.per_ip_per_min, lim.daily_cap) == (3, 7)
    monkeypatch.delenv("CLAUDE_PER_IP_PER_MIN")
    monkeypatch.delenv("CLAUDE_DAILY_CAP")
    lim = ClaudeLimiter.from_env()
    assert (lim.per_ip_per_min, lim.daily_cap) == (10, 500)


class _Req:
    def __init__(self, xff: str | None, peer: str = "10.0.0.1"):
        self.headers = {"x-forwarded-for": xff} if xff else {}
        self.client = type("C", (), {"host": peer})()


def test_client_ip_trusts_only_configured_hops(monkeypatch):
    req = _Req("6.6.6.6, 203.0.113.9")  # leftmost is client-supplied, rightmost added by our proxy
    assert claude_limits.client_ip(req) == "10.0.0.1"
    monkeypatch.setenv("TRUSTED_PROXY_HOPS", "1")
    assert claude_limits.client_ip(req) == "203.0.113.9"
    assert claude_limits.client_ip(_Req(None)) == "10.0.0.1"


def upload(pid: str, content_type: str = "application/pdf"):
    return client.post(f"/profiles/{pid}/transcript", files={"file": ("t.pdf", b"%PDF-1.4", content_type)},
                       headers={"Origin": "http://localhost:5173"})


@pytest.fixture
def fake_claude(monkeypatch):
    calls = []

    async def fake_extract(data, media_type):
        calls.append(media_type)
        return [_Row(prefix="MATH", number="1A", title="Calc", units=5, grade="A", term="Fall 2023", legible=True)]

    monkeypatch.setattr(transcript, "extract_rows", fake_extract)
    return calls


def test_transcript_per_ip_429(monkeypatch, fake_claude):
    monkeypatch.setattr(claude_limits, "limiter", ClaudeLimiter(per_ip_per_min=2, daily_cap=100))
    pid = make_profile()
    assert [upload(pid).status_code for _ in range(3)] == [200, 200, 429]
    res = upload(pid)
    assert int(res.headers["retry-after"]) > 0
    assert res.headers["access-control-allow-origin"] == "http://localhost:5173"
    assert len(fake_claude) == 2


def test_transcript_daily_cap_429_and_rejected_uploads_dont_spend_it(monkeypatch, fake_claude):
    monkeypatch.setattr(claude_limits, "limiter", ClaudeLimiter(per_ip_per_min=100, daily_cap=1))
    pid = make_profile()
    assert upload(pid, "image/heic").status_code == 415
    assert upload(pid).status_code == 200
    res = upload(pid)
    assert res.status_code == 429 and "Daily" in res.json()["detail"]
    assert len(fake_claude) == 1


def test_cors_exposes_notes_and_retry_after(fake_claude):
    res = upload(make_profile())
    exposed = {h.strip().lower() for h in res.headers["access-control-expose-headers"].split(",")}
    assert {"x-transcript-notes", "retry-after"} <= exposed
