"""What a saved schedule means for a week: free blocks, units per term, and which planned
courses are now scheduled. Pure functions over confirmed rows."""

import re
from datetime import date, timedelta

from app.models import (
    FreeBlock,
    FreeBlocksResponse,
    FreeDay,
    ScheduledClass,
    ScheduledPlanCourse,
    Semester,
    ScheduleTerm,
)
from app.services import planner
from app.services.schedule.normalize import WEEKDAYS, course_key, fmt, minutes

DAY_START = 7 * 60  # 7 AM
DAY_END = 22 * 60  # 10 PM
MIN_FREE_MINUTES = 15  # shorter gaps between classes aren't usable free time

_HHMM = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")


class InvalidSchedule(ValueError):
    status = 422


def validate(rows: list[ScheduledClass]) -> list[ScheduledClass]:
    """Confirmed rows, ready to store: checked times, async rows cleared, flags dropped."""
    out = []
    for i, row in enumerate(rows, start=1):
        label = f"Row {i} ({row.course or 'no course'})"
        if not row.course.strip() or not row.term.strip():
            raise InvalidSchedule(f"{label}: course and term are required")
        days, start, end = row.days, row.start_time, row.end_time
        if row.mode == "asynchronous":
            days, start, end = [], None, None
        if (start is None) != (end is None):
            raise InvalidSchedule(f"{label}: give both a start and an end time, or neither")
        if start is not None:
            if not (_HHMM.match(start) and _HHMM.match(end)):
                raise InvalidSchedule(f"{label}: times must look like 09:30")
            if minutes(end) <= minutes(start):
                raise InvalidSchedule(f"{label}: the end time must be after the start time")
        for value in (row.start_date, row.end_date):
            if value is not None:
                try:
                    date.fromisoformat(value)
                except ValueError as e:
                    raise InvalidSchedule(f"{label}: dates must look like 2026-09-21") from e
        if row.start_date and row.end_date and row.end_date < row.start_date:
            raise InvalidSchedule(f"{label}: the end date must be after the start date")
        out.append(row.model_copy(update={
            "days": [d for d in WEEKDAYS if d in set(days)],  # week order, no repeats
            "start_time": start, "end_time": end, "flags": None, "confirmed": True,
        }))
    return out


def _class_id(row: ScheduledClass) -> tuple:
    """A class with a lecture and a lab is two rows; count it once."""
    return (row.term, row.crn) if row.crn else (row.term, course_key(row.course), row.section)


def term_totals(rows: list[ScheduledClass]) -> list[ScheduleTerm]:
    """Units and class count per term, in calendar order (unparsed terms last)."""
    seen: dict[str, dict[tuple, float]] = {}
    for row in rows:
        classes = seen.setdefault(row.term, {})
        classes[_class_id(row)] = max(classes.get(_class_id(row), 0.0), row.units or 0.0)
    order = sorted(seen, key=lambda t: (planner.term_key(t) is None, planner.term_key(t) or 0, t))
    return [ScheduleTerm(term=t, units=sum(seen[t].values()), classes=len(seen[t])) for t in order]


def monday_of(day: date) -> date:
    return day - timedelta(days=day.weekday())


def _meets_on(row: ScheduledClass, day: date) -> bool:
    if row.mode == "asynchronous" or not row.start_time or not row.end_time:
        return False
    if WEEKDAYS[day.weekday()] not in row.days:
        return False
    if row.start_date and day.isoformat() < row.start_date:
        return False
    if row.end_date and day.isoformat() > row.end_date:
        return False
    return True


def free_blocks(rows: list[ScheduledClass], week: date) -> FreeBlocksResponse:
    """Mon–Sun of the week containing `week`, 7 AM–10 PM, minus class meetings.

    Rows with printed class dates only count in the weeks they run; rows without dates
    count every week. Asynchronous and TBA classes don't block time.
    """
    monday = monday_of(week)
    days = []
    for offset in range(7):
        day = monday + timedelta(days=offset)
        busy = sorted(
            (max(minutes(r.start_time), DAY_START), min(minutes(r.end_time), DAY_END))
            for r in rows if _meets_on(r, day)
        )
        blocks, cursor = [], DAY_START
        for start, end in busy:
            if start > cursor and start - cursor >= MIN_FREE_MINUTES:
                blocks.append((cursor, start))
            cursor = max(cursor, end)
        if DAY_END - cursor >= MIN_FREE_MINUTES:
            blocks.append((cursor, DAY_END))
        days.append(FreeDay(day=WEEKDAYS[offset], date=day.isoformat(), blocks=[
            FreeBlock(start=fmt(s), end=fmt(e), minutes=e - s) for s, e in blocks
        ]))
    return FreeBlocksResponse(week=monday.isoformat(), day_start=fmt(DAY_START), day_end=fmt(DAY_END), days=days)


def scheduled_plan_courses(semesters: list[Semester], rows: list[ScheduledClass]) -> list[ScheduledPlanCourse]:
    """Planned courses that appear on the schedule, matched by course code (any term), in plan order."""
    by_key: dict[str, ScheduledClass] = {}
    for row in rows:
        by_key.setdefault(course_key(row.course), row)
    out = []
    for semester in semesters:
        for course in semester.courses:
            row = by_key.get(course_key(course.code))
            if row is not None:
                out.append(ScheduledPlanCourse(code=course.code, planned_term=semester.term,
                                               scheduled_term=row.term, crn=row.crn))
    return out
