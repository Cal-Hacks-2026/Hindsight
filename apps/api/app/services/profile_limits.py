"""Per-IP limit on creating profiles. Each new profile queues an agent run whose ranking
asks Claude for reasons, so unlimited creation could spend the shared daily Claude cap
(and, past AGENT_PROFILE_RUNS_PER_HOUR, Droid credits) for everyone.

Its own bucket, so a booth on one wifi IP doesn't trade profiles against transcript
uploads; reuses the Claude limiter's sliding window and proxy-aware client IP.
"""

from fastapi import Request

from app.services import claude_limits

PER_IP_PER_MIN = 20

limiter = claude_limits.ClaudeLimiter(per_ip_per_min=PER_IP_PER_MIN, daily_cap=0)


def per_ip(request: Request) -> None:
    """FastAPI dependency for POST /profiles."""
    limiter.check_ip(claude_limits.client_ip(request))
