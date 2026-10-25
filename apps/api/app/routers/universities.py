from typing import Annotated

from fastapi import APIRouter, Depends, Path

from app.models import UniversityGuideResponse
from app.services.assist import get_service, limits
from app.services.university import store

router = APIRouter(prefix="/universities", tags=["universities"])


@router.get("/{university_id}/guide", response_model=UniversityGuideResponse, response_model_exclude_none=True,
            dependencies=[Depends(limits.per_ip)])
def guide(university_id: Annotated[int, Path(ge=1, le=100_000)]) -> UniversityGuideResponse:
    """The "What to Expect" guide for an ASSIST university id. No guide yet is not an error:
    `available` is false, with ASSIST's name for the university when it can be looked up."""
    found = store.get_guide(university_id)
    if found is not None:
        return UniversityGuideResponse(university_id=university_id, available=True,
                                       university_name=found.university_name, guide=found)
    return UniversityGuideResponse(university_id=university_id, available=False,
                                   university_name=get_service().institution_name(university_id))
