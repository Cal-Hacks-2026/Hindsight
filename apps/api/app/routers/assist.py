from fastapi import APIRouter, Depends, HTTPException

from app.models import AssistInstitution, AssistInstitutionsResponse, AssistMajorsResponse
from app.services import planner
from app.services.assist import AssistError, AssistNotFound, get_service, limits

router = APIRouter(prefix="/assist", tags=["assist"])


@router.get("/majors", response_model=AssistMajorsResponse, response_model_exclude_none=True,
            dependencies=[Depends(limits.per_ip)])
def majors(sending: int, receiving: int, year: int) -> AssistMajorsResponse:
    try:
        found, used, saved_at = get_service().majors_in_year(sending, receiving, year)
        # year_id: the year the majors come from, earlier than `year` when it has none yet
        # (MAJORS-YEAR). saved_on only when ASSIST failed and the pair's kept list was used
        # (MAJORS-FALLBACK).
        return AssistMajorsResponse(majors=found, year_id=used, saved_on=saved_at[:10] if saved_at else None)
    except AssistNotFound as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except AssistError as e:
        raise HTTPException(status_code=502, detail=f"ASSIST unavailable: {e}") from e


# The pickers load each list once and filter as the student types; both are cached for a day.
@router.get("/colleges", response_model=AssistInstitutionsResponse, response_model_exclude_none=True,
            dependencies=[Depends(limits.per_ip)])
def colleges() -> AssistInstitutionsResponse:
    """Every California community college in ASSIST, with its term system."""
    try:
        return AssistInstitutionsResponse(institutions=get_service().colleges())
    except AssistError as e:
        raise HTTPException(status_code=502, detail=f"ASSIST unavailable: {e}") from e


@router.get("/universities", response_model=AssistInstitutionsResponse, response_model_exclude_none=True,
            dependencies=[Depends(limits.per_ip)])
def universities(sending: int) -> AssistInstitutionsResponse:
    """Universities ASSIST has agreements with from `sending`, each with the year to read them from
    and whether we can plan the whole degree (curated requirements)."""
    try:
        found = get_service().universities(sending)
    except AssistNotFound as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except AssistError as e:
        raise HTTPException(status_code=502, detail=f"ASSIST unavailable: {e}") from e
    curated = {m.university_id for m in planner.load_majors()}
    return AssistInstitutionsResponse(institutions=[
        AssistInstitution(id=rid, name=name, year_id=year, full_plan=rid in curated)
        for rid, name, year in found
    ])
