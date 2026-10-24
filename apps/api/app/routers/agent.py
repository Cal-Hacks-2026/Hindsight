import uuid

from fastapi import APIRouter, Depends

from app.models import AgentEventsResponse, AgentLatestRunResponse, AgentRunRequest, AgentRunResponse
from app.models.contracts import Campus
from app.services import agent_client, agent_events, claude_limits

router = APIRouter(prefix="/agent", tags=["agent"])


@router.post("/run", response_model=AgentRunResponse, dependencies=[Depends(claude_limits.per_ip)])
def run(body: AgentRunRequest) -> AgentRunResponse:
    """Queue a Droid run (scan → rank → alerts) for body.campus on apps/agent."""
    run_id = agent_client.start_run(str(uuid.uuid4()), body.campus, "manual")
    return AgentRunResponse(run_id=run_id)


@router.get("/events", response_model=AgentEventsResponse, response_model_exclude_none=True)
def events(run_id: str) -> AgentEventsResponse:
    return AgentEventsResponse(events=agent_events.for_run(run_id))


@router.get("/runs/latest", response_model=AgentLatestRunResponse)
def latest_run(campus: Campus) -> AgentLatestRunResponse:
    """The newest manual or scheduled scan for a campus, so /agent can open on it."""
    return AgentLatestRunResponse(run_id=agent_events.latest_run_id(campus))
