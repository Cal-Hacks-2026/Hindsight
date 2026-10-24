"""Hands runs to apps/agent, the Droid service in the same container (DECISIONS.md D-006).

The agent listens on AGENT_URL (default 127.0.0.1:8787, not exposed publicly) and checks
AGENT_SECRET on every request. A manual run the agent can't take becomes an `error` event on
that run, so /agent/events explains what happened to the run id the client holds.
"""

import logging
import os
from typing import Literal

import httpx

from app.models.contracts import Campus
from app.services import agent_events
from app.services.db import StoreError

log = logging.getLogger(__name__)

SECRET_HEADER = "X-Agent-Secret"
Trigger = Literal["manual", "profile_created"]


def _record_error(run_id: str, trigger: Trigger, message: str) -> None:
    if trigger != "manual":  # nobody holds a profile_created run id; the server log is enough
        log.warning("agent: %s run %s not started: %s", trigger, run_id, message)
        return
    try:
        agent_events.record(run_id, "error", message)
    except StoreError as e:
        log.error("agent: could not record error for run %s (%s): %s", run_id, message, e)


def start_run(run_id: str, campus: Campus, trigger: Trigger, profile_id: str | None = None,
              transport: httpx.BaseTransport | None = None) -> str:
    """Queue a run on the agent. Returns the run id the agent will log under: the agent
    folds a request into an identical pending run, so it may hand back that run's id."""
    url, secret = os.getenv("AGENT_URL", "http://127.0.0.1:8787").rstrip("/"), os.getenv("AGENT_SECRET")
    if not secret:
        _record_error(run_id, trigger, "The agent is not configured on this server (AGENT_SECRET is not set).")
        return run_id
    body = {"run_id": run_id, "campus": campus, "trigger": trigger, "profile_id": profile_id}
    try:
        with httpx.Client(timeout=5.0, transport=transport) as http:
            res = http.post(f"{url}/runs", json=body, headers={SECRET_HEADER: secret})
            res.raise_for_status()
            queued = res.json().get("run_id")
            return queued if isinstance(queued, str) and queued else run_id
    except httpx.HTTPStatusError as e:
        log.warning("agent: refused run %s (%s): %s", run_id, e.response.status_code, e.response.text[:200])
        reason = "its queue is full" if e.response.status_code == 429 else f"it answered {e.response.status_code}"
        _record_error(run_id, trigger, f"The agent did not take this run: {reason}.")
    except (httpx.HTTPError, ValueError) as e:
        log.warning("agent: unreachable for run %s: %s", run_id, e)
        _record_error(run_id, trigger, "The agent service is not reachable.")
    return run_id
