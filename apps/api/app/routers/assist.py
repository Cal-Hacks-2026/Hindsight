from fastapi import APIRouter, HTTPException

from app.models import AssistMajorsResponse
from app.services.assist import AssistError, get_service

router = APIRouter(prefix="/assist", tags=["assist"])


@router.get("/majors", response_model=AssistMajorsResponse)
def majors(sending: int, receiving: int, year: int) -> AssistMajorsResponse:
    try:
        return AssistMajorsResponse(majors=get_service().majors(sending, receiving, year))
    except AssistError as e:
        raise HTTPException(status_code=502, detail=f"ASSIST unavailable: {e}") from e
