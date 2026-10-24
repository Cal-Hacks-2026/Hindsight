from fastapi import APIRouter

from app.models import AssistMajorsResponse
from app.services import mocks

router = APIRouter(prefix="/assist", tags=["assist"])


@router.get("/majors", response_model=AssistMajorsResponse)
def majors(sending: int, receiving: int, year: int) -> AssistMajorsResponse:
    # Phase 1: Shiv's ASSIST client, exact label match, cached in articulation_cache.
    return AssistMajorsResponse(majors=mocks.assist_majors())
