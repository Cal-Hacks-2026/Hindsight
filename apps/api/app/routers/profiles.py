import uuid

from fastapi import APIRouter, File, HTTPException, Query, UploadFile

from app.models import (
    CounselorRequest,
    CounselorResponse,
    CoursesResponse,
    CreateProfileRequest,
    MatchRequest,
    MatchResult,
    OpportunitiesResponse,
    PlanResponse,
    Profile,
    ProfileResponse,
    UpdateCoursesRequest,
)
from app.services import mocks, store

router = APIRouter(prefix="/profiles", tags=["profiles"])

ALLOWED_UPLOAD_TYPES = {"application/pdf", "image/png", "image/jpeg", "image/webp", "image/heic"}


def _get_profile(profile_id: str) -> Profile:
    profile = store.profiles.get(profile_id)
    if profile is None:
        raise HTTPException(status_code=404, detail="Profile not found")
    return profile


@router.post("", response_model=ProfileResponse)
def create_profile(body: CreateProfileRequest) -> ProfileResponse:
    profile = Profile(id=str(uuid.uuid4()), created_at=mocks.now_iso(), **body.model_dump())
    store.profiles[profile.id] = profile
    return ProfileResponse(profile=profile)


@router.get("/{profile_id}", response_model=ProfileResponse)
def get_profile(profile_id: str) -> ProfileResponse:
    return ProfileResponse(profile=_get_profile(profile_id))


@router.post("/{profile_id}/transcript", response_model=CoursesResponse,
             response_model_exclude_none=True)
async def upload_transcript(profile_id: str, file: UploadFile = File(...)) -> CoursesResponse:
    _get_profile(profile_id)
    if file.content_type not in ALLOWED_UPLOAD_TYPES:
        raise HTTPException(status_code=415, detail="Upload a PDF or image")
    # Phase 1: store in Supabase Storage `transcripts/` and parse with Claude.
    return CoursesResponse(courses=mocks.transcript_courses())


@router.put("/{profile_id}/courses", response_model=CoursesResponse,
            response_model_exclude_none=True)
def confirm_courses(profile_id: str, body: UpdateCoursesRequest) -> CoursesResponse:
    _get_profile(profile_id)
    confirmed = [c.model_copy(update={"confirmed": True}) for c in body.courses]
    store.courses[profile_id] = confirmed
    return CoursesResponse(courses=confirmed)


@router.post("/{profile_id}/match", response_model=MatchResult,
             response_model_exclude_none=True)
def match(profile_id: str, body: MatchRequest) -> MatchResult:
    _get_profile(profile_id)
    return mocks.match_result(body.major_label)


@router.get("/{profile_id}/plan", response_model=PlanResponse)
def plan(profile_id: str, majors: str | None = Query(None, description="Comma-separated major labels")) -> PlanResponse:
    _get_profile(profile_id)
    return PlanResponse(semesters=mocks.plan())


@router.get("/{profile_id}/opportunities", response_model=OpportunitiesResponse,
            response_model_exclude_none=True)
def opportunities(profile_id: str) -> OpportunitiesResponse:
    _get_profile(profile_id)
    return OpportunitiesResponse(items=mocks.opportunities())


@router.post("/{profile_id}/counselor", response_model=CounselorResponse,
             response_model_exclude_none=True)
def counselor(profile_id: str, body: CounselorRequest) -> CounselorResponse:
    _get_profile(profile_id)
    reply, citations = mocks.counselor_reply(body.message)
    return CounselorResponse(reply=reply, citations=citations)
