from fastapi import APIRouter, Depends, HTTPException

from app.models import AssistMajorsResponse
from app.services.assist import AssistError, AssistNotFound, get_service, limits

router = APIRouter(prefix="/assist", tags=["assist"])


@router.get("/majors", response_model=AssistMajorsResponse, dependencies=[Depends(limits.per_ip)])
def majors(sending: int, receiving: int, year: int) -> AssistMajorsResponse:
    try:
        return AssistMajorsResponse(majors=get_service().majors(sending, receiving, year))
    except AssistNotFound as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except AssistError as e:
        raise HTTPException(status_code=502, detail=f"ASSIST unavailable: {e}") from e
