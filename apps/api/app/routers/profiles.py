import json
import logging
import uuid

from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, Query, Response, UploadFile
from fastapi.concurrency import run_in_threadpool

from app.config import ASSIST_YEAR_ID
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
    RankedOpportunity,
    UpdateCoursesRequest,
)
from app.services import agent_client, claude_limits, counselor, planner, profile_limits, profile_store, transcript
from app.services.assist import AssistError, AssistNotFound, get_service
from app.services.assist import limits as assist_limits
from app.services.db import StoreError
from app.services.radar import rank, store as radar_store

log = logging.getLogger(__name__)

router = APIRouter(prefix="/profiles", tags=["profiles"])

ALLOWED_UPLOAD_TYPES = {"application/pdf", "image/png", "image/jpeg", "image/webp", "image/heic"}
TRANSCRIPT_NOTES_HEADER = "X-Transcript-Notes"


def _get_profile(profile_id: str) -> Profile:
    profile = profile_store.get_profile(profile_id)
    if profile is None:
        raise HTTPException(status_code=404, detail="Profile not found")
    return profile


@router.post("", response_model=ProfileResponse, dependencies=[Depends(profile_limits.per_ip)])
def create_profile(body: CreateProfileRequest, background: BackgroundTasks) -> ProfileResponse:
    profile = profile_store.create_profile(body)
    # Trigger: a new profile gets its own Droid run (rank + alerts) once the response is sent.
    background.add_task(agent_client.start_run, str(uuid.uuid4()), profile.campus, "profile_created", profile.id)
    return ProfileResponse(profile=profile)


@router.get("/{profile_id}", response_model=ProfileResponse)
def get_profile(profile_id: str) -> ProfileResponse:
    return ProfileResponse(profile=_get_profile(profile_id))


@router.post("/{profile_id}/transcript", response_model=CoursesResponse,
             response_model_exclude_none=True, dependencies=[Depends(claude_limits.per_ip)])
async def upload_transcript(profile_id: str, response: Response,
                            file: UploadFile = File(...)) -> CoursesResponse:
    await run_in_threadpool(_get_profile, profile_id)  # blocking Supabase read
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
    profile_store.replace_courses(profile_id, confirmed)
    return CoursesResponse(courses=confirmed)


@router.post("/{profile_id}/match", response_model=MatchResult,
             response_model_exclude_none=True, dependencies=[Depends(assist_limits.per_ip)])
def match(profile_id: str, body: MatchRequest) -> MatchResult:
    profile = _get_profile(profile_id)
    courses = profile_store.confirmed_courses(profile_id)
    try:
        return get_service().match(
            profile.sending_institution_id,
            profile.receiving_institution_id,
            ASSIST_YEAR_ID,
            body.major_label,
            courses,
        )
    except AssistNotFound as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except AssistError as e:
        raise HTTPException(status_code=502, detail=f"ASSIST unavailable: {e}") from e


@router.get("/{profile_id}/plan", response_model=PlanResponse)
def plan(profile_id: str, majors: str | None = Query(None, description="Comma-separated major labels")) -> PlanResponse:
    profile = _get_profile(profile_id)
    try:
        chosen = planner.resolve_majors(majors, profile.majors, profile.campus, planner.load_majors())
        # Match results aren't persisted yet; once /match stores them, add
        # planner.satisfied_from_match(result) for each chosen major here.
        satisfied = planner.satisfied_from_courses(profile_store.confirmed_courses(profile_id))
        semesters = planner.build_plan(chosen, satisfied)
    except planner.PlannerError as e:
        raise HTTPException(status_code=e.status, detail=str(e)) from e
    return PlanResponse(semesters=semesters)


@router.get("/{profile_id}/opportunities", response_model=OpportunitiesResponse,
            response_model_exclude_none=True, dependencies=[Depends(claude_limits.per_ip)])
def opportunities(profile_id: str, background: BackgroundTasks) -> OpportunitiesResponse:
    profile = _get_profile(profile_id)
    items = rank.ranked_opportunities(profile, radar_store.candidates(profile.campus))
    background.add_task(_record_ranked, profile_id, items)
    return OpportunitiesResponse(items=items)


def _record_ranked(profile_id: str, items: list[RankedOpportunity]) -> None:
    """After the response is sent; the feed is already served, so a failure is only logged."""
    try:
        radar_store.record_ranked(profile_id, items)
    except StoreError as e:
        log.warning("profile_opportunities write failed for %s: %s", profile_id, e)


@router.post("/{profile_id}/counselor", response_model=CounselorResponse,
             response_model_exclude_none=True, dependencies=[Depends(claude_limits.per_ip)])
def counselor_reply(profile_id: str, body: CounselorRequest) -> CounselorResponse:
    profile = _get_profile(profile_id)
    try:
        reply, citations = counselor.answer(profile, profile_store.confirmed_courses(profile_id),
                                            body.message, body.history)
    except counselor.CounselorError as e:
        raise HTTPException(status_code=e.status, detail=str(e)) from e
    return CounselorResponse(reply=reply, citations=citations)
