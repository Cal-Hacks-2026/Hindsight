import json
import uuid

from fastapi import APIRouter, Depends, File, HTTPException, Query, Response, UploadFile

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
from app.services import claude_limits, mocks, planner, store, transcript

router = APIRouter(prefix="/profiles", tags=["profiles"])

ALLOWED_UPLOAD_TYPES = {"application/pdf", "image/png", "image/jpeg", "image/webp", "image/heic"}
TRANSCRIPT_NOTES_HEADER = "X-Transcript-Notes"


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
             response_model_exclude_none=True, dependencies=[Depends(claude_limits.per_ip)])
async def upload_transcript(profile_id: str, response: Response,
                            file: UploadFile = File(...)) -> CoursesResponse:
    _get_profile(profile_id)
    if file.content_type not in ALLOWED_UPLOAD_TYPES:
        raise HTTPException(status_code=415, detail="Upload a PDF or image")
    # TODO: also store the file in Supabase Storage `transcripts/` once Supabase is wired.
    try:
        # Read at most one byte past the cap so an oversized upload is rejected without buffering it.
        data = await file.read(transcript.MAX_UPLOAD_BYTES + 1)
        courses, notes = await transcript.parse_transcript(data, file.content_type)
    except transcript.TranscriptError as e:
        raise HTTPException(status_code=e.status, detail=str(e)) from e
    # Course has no confidence field (frozen contract), so renumbering notes ride in a
    # header, index-aligned with `courses`.
    response.headers[TRANSCRIPT_NOTES_HEADER] = json.dumps([n.model_dump() for n in notes])
    return CoursesResponse(courses=courses)


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
    profile = _get_profile(profile_id)
    try:
        chosen = planner.resolve_majors(majors, profile.majors, profile.campus, planner.load_majors())
        # Match results aren't persisted yet; once /match stores them, add
        # planner.satisfied_from_match(result) for each chosen major here.
        satisfied = planner.satisfied_from_courses(store.courses.get(profile_id, []))
        semesters = planner.build_plan(chosen, satisfied)
    except planner.PlannerError as e:
        raise HTTPException(status_code=e.status, detail=str(e)) from e
    return PlanResponse(semesters=semesters)


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
