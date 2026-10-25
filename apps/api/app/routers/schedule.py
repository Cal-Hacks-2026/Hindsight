"""Class schedule: upload → confirm → save, then free blocks and planned-course marks."""

from datetime import date
from typing import Literal

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from fastapi.concurrency import run_in_threadpool

from app.models import (
    FreeBlocksResponse,
    ScheduledPlanResponse,
    ScheduleResponse,
    UpdateScheduleRequest,
)
from app.routers import profiles
from app.services import claude_limits
from app.services.assist import limits as assist_limits
from app.services.schedule import parser, store, week

router = APIRouter(prefix="/profiles", tags=["schedule"])


def _saved(profile_id: str) -> ScheduleResponse:
    rows = store.schedule(profile_id)
    return ScheduleResponse(rows=rows, terms=week.term_totals(rows))


@router.post("/{profile_id}/schedule", response_model=ScheduleResponse,
             response_model_exclude_none=True, dependencies=[Depends(claude_limits.per_ip)])
async def upload_schedule(profile_id: str, file: UploadFile = File(...)) -> ScheduleResponse:
    """Parsed, unconfirmed rows for the confirm table; nothing is saved until PUT."""
    await run_in_threadpool(profiles._get_profile, profile_id)  # blocking Supabase read
    try:
        parser.check_upload_type(file.content_type)  # before reading the body
        # Read at most one byte past the cap so an oversized upload is rejected without buffering it.
        data = await file.read(parser.MAX_UPLOAD_BYTES + 1)
        rows = await parser.parse_schedule(data, file.content_type)
    except parser.ScheduleError as e:
        raise HTTPException(status_code=e.status, detail=str(e)) from e
    return ScheduleResponse(rows=rows)


@router.put("/{profile_id}/schedule", response_model=ScheduleResponse, response_model_exclude_none=True)
def save_schedule(profile_id: str, body: UpdateScheduleRequest) -> ScheduleResponse:
    profiles._get_profile(profile_id)
    try:
        rows = week.validate(body.rows)
    except week.InvalidSchedule as e:
        raise HTTPException(status_code=e.status, detail=str(e)) from e
    store.replace_schedule(profile_id, rows)
    return ScheduleResponse(rows=rows, terms=week.term_totals(rows))


@router.get("/{profile_id}/schedule", response_model=ScheduleResponse, response_model_exclude_none=True)
def get_schedule(profile_id: str) -> ScheduleResponse:
    profiles._get_profile(profile_id)
    return _saved(profile_id)


@router.get("/{profile_id}/schedule/free-blocks", response_model=FreeBlocksResponse)
def free_blocks(profile_id: str,
                week_of: str = Query(..., alias="week", description="Any date in the week, YYYY-MM-DD"),
                term: str | None = Query(None, description="Only this term's classes, e.g. 'Fall 2026'")
                ) -> FreeBlocksResponse:
    profiles._get_profile(profile_id)
    try:
        day = date.fromisoformat(week_of)
    except ValueError as e:
        raise HTTPException(status_code=422, detail="week must be a date like 2026-10-26") from e
    rows = store.schedule(profile_id)
    if term:
        rows = [r for r in rows if r.term.lower() == term.strip().lower()]
    return week.free_blocks(rows, day)


@router.get("/{profile_id}/schedule/planned", response_model=ScheduledPlanResponse,
            response_model_exclude_none=True, dependencies=[Depends(assist_limits.per_ip)])
def planned(profile_id: str, majors: str | None = Query(None, description="Same as GET /plan"),
            transfer_term: str | None = Query(None, description="Same as GET /plan"),
            start_term: str | None = Query(None, description="Same as GET /plan"),
            ge: bool = Query(False, description="Same as GET /plan"),
            ge_pattern: Literal["calgetc", "igetc"] | None = Query(None, description="Same as GET /plan")
            ) -> ScheduledPlanResponse:
    """Which courses on the student's plan (same query as GET /plan) are now on their schedule."""
    profiles._get_profile(profile_id)
    rows = store.schedule(profile_id)
    if not rows:  # no plan (or ASSIST) needed
        return ScheduledPlanResponse(courses=[])
    # Every argument is passed: called directly, plan()'s defaults are Query objects, not values.
    plan = profiles.plan(profile_id, majors=majors, transfer_term=transfer_term, start_term=start_term,
                         ge=ge, ge_pattern=ge_pattern)
    return ScheduledPlanResponse(courses=week.scheduled_plan_courses(plan.semesters, rows))
