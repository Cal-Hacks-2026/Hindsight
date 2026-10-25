from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query

from app.models import GeResponse
from app.routers.profiles import _get_profile
from app.services import ge, profile_store
from app.services.assist import AssistError, AssistNotFound
from app.services.assist import limits as assist_limits

router = APIRouter(prefix="/profiles", tags=["ge"])


@router.get("/{profile_id}/ge", response_model=GeResponse, response_model_exclude_none=True,
            dependencies=[Depends(assist_limits.per_ip)])
def ge_progress(profile_id: str,
                pattern: Literal["calgetc", "igetc"] | None = Query(
                    None, description="Override the pattern chosen from the first term on the transcript")
                ) -> GeResponse:
    """Cal-GETC or IGETC progress, area by area, from the confirmed courses and the college's
    ASSIST lists for the years they were taken."""
    profile = _get_profile(profile_id)
    courses = profile_store.confirmed_courses(profile_id)
    try:
        return ge.progress(courses, profile.sending_institution_id, ge.get_store(), pattern,
                           profile.receiving_institution_id)
    except AssistNotFound as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except AssistError as e:
        raise HTTPException(status_code=502, detail=f"ASSIST unavailable: {e}") from e
