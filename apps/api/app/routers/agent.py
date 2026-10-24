import uuid

from fastapi import APIRouter

from app.models import AgentEventsResponse, AgentRunRequest, AgentRunResponse
from app.services import mocks

router = APIRouter(prefix="/agent", tags=["agent"])


@router.post("/run", response_model=AgentRunResponse)
def run(body: AgentRunRequest) -> AgentRunResponse:
    # Phase 3: kick off a Droid run for body.campus.
    return AgentRunResponse(run_id=str(uuid.uuid4()))


@router.get("/events", response_model=AgentEventsResponse, response_model_exclude_none=True)
def events(run_id: str) -> AgentEventsResponse:
    return AgentEventsResponse(events=mocks.agent_events(run_id))
