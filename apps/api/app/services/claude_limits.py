"""In-memory rate limits for endpoints that call Claude (transcript; counselor next).

Two limits, both answered with 429 + Retry-After:
- per client IP: CLAUDE_PER_IP_PER_MIN requests per rolling minute (default 10),
  charged on every request to a Claude endpoint, via the `per_ip` dependency;
- global: CLAUDE_DAILY_CAP Claude calls per UTC day (default 500), charged by
  `take_daily()` right before the API call, so rejected uploads don't spend it.

Wiring a new Claude endpoint: add `dependencies=[Depends(claude_limits.per_ip)]` to
the route and call `claude_limits.limiter.take_daily()` before calling Claude.

State is per process and resets on restart; run one worker, or move this to
Supabase/Redis before scaling out.

Behind a proxy (Railway/Render) every request arrives from the proxy, so set
TRUSTED_PROXY_HOPS to the number of proxies that append to X-Forwarded-For
(usually 1). The client IP is then read that many entries from the right; entries
further left are client-supplied and can be spoofed.
"""

import os
import threading
import time
from collections import deque
from datetime import datetime, timedelta, timezone

from fastapi import Request

WINDOW_SECONDS = 60
MAX_TRACKED_IPS = 10_000


class RateLimited(Exception):
    def __init__(self, detail: str, retry_after: int):
        super().__init__(detail)
        self.detail = detail
        self.retry_after = max(retry_after, 1)


class ClaudeLimiter:
    def __init__(self, per_ip_per_min: int, daily_cap: int, clock=time.time):
        self.per_ip_per_min = per_ip_per_min
        self.daily_cap = daily_cap
        self.clock = clock
        self._lock = threading.Lock()
        self._hits: dict[str, deque[float]] = {}
        self._day: str = ""
        self._day_count = 0

    @classmethod
    def from_env(cls) -> "ClaudeLimiter":
        return cls(
            per_ip_per_min=int(os.getenv("CLAUDE_PER_IP_PER_MIN") or 10),
            daily_cap=int(os.getenv("CLAUDE_DAILY_CAP") or 500),
        )

    def check_ip(self, ip: str) -> None:
        now = self.clock()
        with self._lock:
            if len(self._hits) > MAX_TRACKED_IPS:
                self._hits = {k: v for k, v in self._hits.items() if v and v[-1] > now - WINDOW_SECONDS}
            hits = self._hits.setdefault(ip, deque())
            while hits and hits[0] <= now - WINDOW_SECONDS:
                hits.popleft()
            if len(hits) >= self.per_ip_per_min:
                raise RateLimited("Too many requests; try again in a minute",
                                  retry_after=int(hits[0] + WINDOW_SECONDS - now) + 1)
            hits.append(now)

    def take_daily(self) -> None:
        now = datetime.fromtimestamp(self.clock(), timezone.utc)
        with self._lock:
            day = now.date().isoformat()
            if day != self._day:
                self._day, self._day_count = day, 0
            if self._day_count >= self.daily_cap:
                midnight = datetime.combine(now.date() + timedelta(days=1), datetime.min.time(), timezone.utc)
                raise RateLimited("Daily Claude limit reached; try again tomorrow",
                                  retry_after=int((midnight - now).total_seconds()) + 1)
            self._day_count += 1


limiter = ClaudeLimiter.from_env()


def client_ip(request: Request) -> str:
    hops = int(os.getenv("TRUSTED_PROXY_HOPS") or 0)
    if hops > 0:
        forwarded = [p.strip() for p in request.headers.get("x-forwarded-for", "").split(",") if p.strip()]
        if len(forwarded) >= hops:
            return forwarded[-hops]
    return request.client.host if request.client else "unknown"


def per_ip(request: Request) -> None:
    """FastAPI dependency for every route that calls Claude."""
    limiter.check_ip(client_ip(request))
