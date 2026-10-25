import json
import logging
import uuid
from dataclasses import dataclass
from datetime import timedelta
from typing import Literal

from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, Query, Request, Response, UploadFile
from fastapi.concurrency import run_in_threadpool

from app.models import (
    CounselorRequest,
    CounselorResponse,
    Course,
    CoursesResponse,
    CreateProfileRequest,
    GeResponse,
    MatchRequest,
    MatchResult,
    OpportunitiesResponse,
    OpportunityModality,
    PlanResponse,
    Profile,
    ProfileResponse,
    RankedOpportunity,
    UpdateCoursesRequest,
)
from app.services import agent_client, campuses, claude_limits, counselor, planner, profile_limits, profile_store, transcript
from app.services import ge as ge_service
from app.services.assist import AssistError, AssistNotFound, get_service
from app.services.assist import limits as assist_limits
from app.services.db import StoreError
from app.services.ge import plan as ge_plan
from app.services.radar import classify, feeds, rank, store as radar_store
from app.services.radar import programs as radar_programs
from app.services.radar.normalize import parse_when
from app.services.schedule import store as schedule_store, week as schedule_week

log = logging.getLogger(__name__)

router = APIRouter(prefix="/profiles", tags=["profiles"])

TRANSCRIPT_NOTES_HEADER = "X-Transcript-Notes"


def _named(profile: Profile) -> Profile:
    """With ASSIST's names for the two institutions (cached), when ASSIST can give them."""
    service = get_service()
    return profile.model_copy(update={
        "sending_institution_name": service.institution_name(profile.sending_institution_id),
        "receiving_institution_name": service.institution_name(profile.receiving_institution_id),
    })


def _get_profile(profile_id: str) -> Profile:
    profile = profile_store.get_profile(profile_id)
    if profile is None:
        raise HTTPException(status_code=404, detail="Profile not found")
    return _named(profile)


@router.post("", response_model=ProfileResponse, response_model_exclude_none=True,
             dependencies=[Depends(profile_limits.per_ip)])
def create_profile(body: CreateProfileRequest, background: BackgroundTasks) -> ProfileResponse:
    # The legacy campus column follows the university picked, whatever the client sent; schools
    # are always found by ASSIST id, so a profile never reads another campus's data.
    profile = profile_store.create_profile(
        body.model_copy(update={"campus": campuses.profile_feed(body.receiving_institution_id)}))
    if read := feeds.for_profile(profile):
        # Trigger: a new profile gets its own Droid run (rank + alerts) once the response is sent. One
        # run is enough: it ranks the profile across every feed it reads.
        background.add_task(agent_client.start_run, str(uuid.uuid4()), read[0].key, "profile_created", profile.id)
    return ProfileResponse(profile=_named(profile))


@router.get("/{profile_id}", response_model=ProfileResponse, response_model_exclude_none=True)
def get_profile(profile_id: str) -> ProfileResponse:
    return ProfileResponse(profile=_get_profile(profile_id))


@router.post("/{profile_id}/transcript", response_model=CoursesResponse,
             response_model_exclude_none=True, dependencies=[Depends(claude_limits.per_ip)])
async def upload_transcript(profile_id: str, response: Response,
                            file: UploadFile = File(...)) -> CoursesResponse:
    await run_in_threadpool(_get_profile, profile_id)  # blocking Supabase read
    try:
        transcript.check_upload_type(file.content_type)  # before reading the body
    except transcript.TranscriptError as e:
        raise HTTPException(status_code=e.status, detail=str(e)) from e
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
    service = get_service()
    sending, receiving = profile.sending_institution_id, profile.receiving_institution_id
    try:
        return service.match(sending, receiving, service.year_for(sending, receiving), body.major_label, courses)
    except AssistNotFound as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except AssistError as e:
        raise HTTPException(status_code=502, detail=f"ASSIST unavailable: {e}") from e


@dataclass
class Planned:
    """A /plan result with what went into it: the ASSIST matches (in-progress courses as passed),
    GE progress, and the saved classes counted as in progress."""
    response: PlanResponse
    matches: list[MatchResult]
    ge: GeResponse | None
    scheduled: list[Course]


@router.get("/{profile_id}/plan", response_model=PlanResponse,
            response_model_exclude_none=True, dependencies=[Depends(assist_limits.per_ip)])
def plan(profile_id: str, majors: str | None = Query(None, description="Comma-separated major labels"),
         transfer_term: str | None = Query(None, description="'Fall 2028' or 'Spring 2028'; default: the "
                                                             "first Fall after the community-college terms"),
         start_term: str | None = Query(None, description="First community-college term, e.g. 'Winter 2027'; "
                                                          "default: next Fall with no courses, else the next term"),
         ge: bool = Query(False, description="Plan missing GE areas in the community-college terms"),
         ge_pattern: Literal["calgetc", "igetc"] | None = Query(None, description="GE pattern override")
         ) -> PlanResponse:
    return planned(profile_id, majors, transfer_term, start_term, ge, ge_pattern).response


def planned(profile_id: str, majors: str | None, transfer_term: str | None, start_term: str | None,
            ge: bool, ge_pattern: str | None) -> Planned:
    """GET /plan, with its inputs; GET /schedule/planned reads the same plan."""
    profile = _get_profile(profile_id)
    try:
        chosen, uncurated, full = planner.plan_majors(majors, profile.majors, profile.receiving_institution_id,
                                                      planner.load_majors())
    except planner.PlannerError as e:
        raise HTTPException(status_code=e.status, detail=str(e)) from e
    # Same rule as the counselor: done = passed (or in progress) on the transcript, or satisfied
    # per ASSIST for a chosen major, matching in-progress courses as if passed. Classes on the
    # saved schedule are in progress too: the student is registered for them.
    transcript = profile_store.confirmed_courses(profile_id)
    scheduled = schedule_week.as_in_progress(_saved_schedule(profile_id), transcript)
    courses = transcript + scheduled
    planning = planner.assume_in_progress_passed(courses)
    service = get_service()
    sending, receiving = profile.sending_institution_id, profile.receiving_institution_id
    matches: dict[str, MatchResult] = {}

    def planning_match(label: str) -> MatchResult | None:
        try:
            matches[label] = service.match(sending, receiving, service.year_for(sending, receiving), label, planning)
            return matches[label]
        except AssistNotFound:
            return None  # no agreement for this major: only the transcript counts
        except AssistError as e:
            log.warning("plan: ASSIST match for %r failed: %s", label, e)
            return None

    ge_progress = _ge_progress(profile, courses, ge_pattern) if ge else None
    try:
        roadmap = planner.roadmap_for(profile, courses, chosen, uncurated, planning_match,
                                      transfer_term=transfer_term, start_term=start_term,
                                      ge_slots=ge_plan.slots(ge_progress) if ge_progress else ())
    except planner.PlannerError as e:
        raise HTTPException(status_code=e.status, detail=str(e)) from e
    # Without curated requirements every major is "uncurated"; full_plan=False says that once.
    response = PlanResponse(semesters=roadmap.semesters, uncurated_majors=(uncurated if full else None) or None,
                            full_plan=full,
                            transfer_term=roadmap.transfer_term, earliest_transfer_term=roadmap.earliest_transfer_term,
                            start_term=roadmap.start_term, default_start_term=roadmap.default_start_term,
                            start_term_choices=roadmap.start_term_choices,
                            not_before_transfer=roadmap.not_before_transfer or None,
                            ge_pattern=ge_progress.pattern if ge_progress else None,
                            ge_not_before_transfer=roadmap.ge_not_before_transfer or None)
    return Planned(response, list(matches.values()), ge_progress, scheduled)


def _saved_schedule(profile_id: str) -> list:
    """The schedule is extra on the plan: if it can't be read, plan from the transcript alone."""
    try:
        return schedule_store.schedule(profile_id)
    except StoreError as e:
        log.warning("plan: class schedule unavailable for %s: %s", profile_id, e)
        return []


def _ge_progress(profile: Profile, courses: list, pattern: str | None) -> GeResponse | None:
    """GE is extra on the plan: if ASSIST can't give the lists, plan without it (no ge_pattern)."""
    try:
        return ge_service.progress(courses, profile.sending_institution_id, ge_service.get_store(), pattern,
                                   profile.receiving_institution_id)
    except AssistError as e:
        log.warning("plan: GE lists unavailable: %s", e)
        return None


@router.get("/{profile_id}/opportunities", response_model=OpportunitiesResponse,
            response_model_exclude_none=True)
def opportunities(profile_id: str, background: BackgroundTasks, request: Request,
                  category: str | None = None, subcategory: str | None = None,
                  start: str | None = Query(None, alias="from"), end: str | None = Query(None, alias="to"),
                  modality: OpportunityModality | None = None,
                  location: str | None = Query(None, max_length=100)) -> OpportunitiesResponse:
    filters = _opportunity_filters(category, subcategory, start, end, modality, location)
    if not filters.active():  # only the unfiltered feed asks Claude for reasons
        claude_limits.per_ip(request)
    profile = _get_profile(profile_id)
    if not feeds.for_profile(profile):
        # Neither school has sources: an empty feed, never another campus's listings.
        return OpportunitiesResponse(items=[])
    rows = feeds.candidates(profile)
    items, categories = rank.feed(profile, rows, filters)
    if not filters.active():  # only the default feed is what Droid alerts on
        background.add_task(_record_ranked, profile_id, [i for i in items if not radar_programs.is_program(i.id)])
    alerted = _notified_ids(profile_id)
    return OpportunitiesResponse(items=[i.model_copy(update={"notified": i.id in alerted}) for i in items],
                                 categories=categories)


def _opportunity_filters(category: str | None, subcategory: str | None, start: str | None, end: str | None,
                         modality: str | None, location: str | None) -> rank.Filters:
    if category and category not in classify.TAXONOMY:
        raise HTTPException(status_code=422, detail=f"Unknown category: {category}")
    if subcategory and not any(classify.is_label(c, subcategory) for c in ([category] if category else classify.TAXONOMY)):
        raise HTTPException(status_code=422, detail=f"Unknown subcategory: {subcategory}")
    lo, hi = parse_when(start), parse_when(end)
    if (start and lo is None) or (end and hi is None):
        raise HTTPException(status_code=422, detail="Use ISO dates for from and to, like 2026-10-26")
    if hi is not None and end and len(end.strip()) == 10:
        hi += timedelta(days=1) - timedelta(microseconds=1)  # a date means through the end of that day
    if lo and hi and hi < lo:
        raise HTTPException(status_code=422, detail="to is before from")
    return rank.Filters(category=category or None, subcategory=subcategory or None, start=lo, end=hi,
                        modality=modality, location=(location or "").strip() or None)


def _notified_ids(profile_id: str) -> set[str]:
    """The "New" marks are extra; if they can't be read, serve the feed without them."""
    try:
        return radar_store.notified_ids(profile_id)
    except StoreError as e:
        log.warning("profile_opportunities read failed for %s: %s", profile_id, e)
        return set()


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
