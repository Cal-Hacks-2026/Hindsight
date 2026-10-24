"""Per-IP limit on routes that can reach assist.org: it's an unofficial API, and
getting our server's IP blocked would take matching down for everyone.

Reuses the Claude limiter's sliding window (and its proxy-aware client IP);
the daily cap is unused here.
"""

from fastapi import Request

from app.services import claude_limits

PER_IP_PER_MIN = 30

limiter = claude_limits.ClaudeLimiter(per_ip_per_min=PER_IP_PER_MIN, daily_cap=0)


def per_ip(request: Request) -> None:
    """FastAPI dependency for every route that may call ASSIST."""
    limiter.check_ip(claude_limits.client_ip(request))
