"""Class schedule parsing: PDF/image → Claude → unconfirmed ScheduledClass rows.

Same pattern as the transcript parser: Claude only copies what is printed; days, times,
mode, dates and terms are normalized by code here (normalize.py), and the student
confirms the rows before anything is saved.

Results are cached by file hash, so uploading the same schedule twice calls Claude once.
"""

import hashlib
import os
import threading
from collections import OrderedDict

import anthropic
from pydantic import BaseModel

from app.models import ScheduledClass
from app.services import claude_limits
from app.services.schedule import normalize
from app.services.transcript import (
    DEFAULT_MODEL,
    FALLBACK_MODELS,
    MAX_UPLOAD_BYTES,
    UPLOAD_TYPES,
    UPLOAD_TYPES_LABEL,
    _content_block,
)

CACHE_SIZE = 64


class ScheduleError(Exception):
    """Base class; `status` is the HTTP status the route should return."""

    status = 502


class UnsupportedUpload(ScheduleError):
    status = 415


class UploadTooLarge(ScheduleError):
    status = 413


class ParsingUnavailable(ScheduleError):
    status = 503


class UnreadableSchedule(ScheduleError):
    status = 422


# ---- Claude extraction ----


class _Row(BaseModel):
    term: str
    crn: str
    course: str
    title: str
    section: str
    professor: str
    units: str
    location: str
    instruction_mode: str
    days: str
    start_time: str
    end_time: str
    dates: str
    legible: bool


class _Extraction(BaseModel):
    classes: list[_Row]


SYSTEM = """You transcribe college class schedules (a "My Class Schedule" page, a registration
summary, or a screenshot of a schedule table) into structured rows.
Copy what is printed; never infer, correct, or fill in a value that is not on the page.
Use an empty string for any value that is not printed.

One row per meeting pattern. If a class meets at two different times (a lecture and a lab),
write two rows that repeat the class's term, CRN, course, title, section and units.
Skip dropped or waitlisted classes, totals, holds, fees and messages.
- term: the term the class is in as printed, e.g. "Fall 2026" or "2026 Fall Quarter".
- crn: the CRN / class number / registration number.
- course: subject and course number as printed, e.g. "MATH D001B" or "CIS 22C".
- title, section, professor (instructor), units as printed.
- location: building and room as printed, or "ONLINE" if that is what is printed.
- instruction_mode: the instruction method as printed (e.g. "In Person", "Online",
  "Hybrid", "Online Asynchronous"); empty if not printed.
- days: meeting days exactly as printed, e.g. "MW", "TTh", "M W F", "TBA".
- start_time, end_time: the meeting start and end as printed, e.g. "9:30 AM", "10:45".
- dates: the class start and end dates if printed, e.g. "09/21/2026 - 12/11/2026".
- legible: false if any field of the row was hard to read or you are unsure of it."""


async def extract_rows(data: bytes, media_type: str) -> list[_Row]:
    """Send the file to Claude and return the raw transcribed rows."""
    model = os.getenv("ANTHROPIC_MODEL") or DEFAULT_MODEL
    fallback = {"betas": ["server-side-fallback-2026-07-01"], "fallbacks": "default"} if model in FALLBACK_MODELS else {}
    try:
        client = anthropic.AsyncAnthropic()
        response = await client.beta.messages.parse(
            model=model,
            max_tokens=16000,
            output_config={"effort": "medium"},
            system=SYSTEM,
            messages=[{
                "role": "user",
                "content": [
                    _content_block(data, media_type),
                    {"type": "text", "text": "Transcribe every class meeting on this schedule."},
                ],
            }],
            output_format=_Extraction,
            **fallback,
        )
    except (anthropic.AuthenticationError, anthropic.PermissionDeniedError) as e:
        raise ParsingUnavailable("Schedule reading is not configured") from e
    except anthropic.BadRequestError as e:
        raise UnreadableSchedule("This file couldn't be read; try a clearer PDF or image") from e
    except (anthropic.RateLimitError, anthropic.APIConnectionError) as e:
        raise ParsingUnavailable("Schedule reading is busy; try again in a moment") from e
    except anthropic.APIStatusError as e:
        raise ScheduleError(f"Schedule reading failed ({e.status_code})") from e

    if response.stop_reason == "refusal":
        raise UnreadableSchedule("This file couldn't be read as a class schedule")
    if response.stop_reason == "max_tokens" or response.parsed_output is None:
        raise ScheduleError("Schedule reading returned an incomplete result")
    return response.parsed_output.classes


# ---- Deterministic normalization ----


def _blank(value: str) -> str | None:
    return value.strip() or None


def to_class(row: _Row) -> ScheduledClass:
    flags: list[str] = [] if row.legible else ["unclear_scan"]
    term, term_flags = normalize.term(row.term)
    start, end, time_flags = normalize.times(row.start_time, row.end_time)
    first, last, date_flags = normalize.dates(row.dates)
    days = normalize.days(row.days)
    if days is None:
        days, day_flags = [], ["days_unparsed"]
    else:
        day_flags = []
    has_meeting = bool(days) and start is not None
    mode = normalize.mode(row.instruction_mode, row.location, has_meeting)
    flags += term_flags + day_flags + time_flags + date_flags
    if mode != "asynchronous" and not has_meeting and not (day_flags or time_flags):
        # Not online-only, but no meeting time either (TBA): it won't show on the week grid.
        flags.append("no_meeting_time")
    if mode == "asynchronous":
        days, start, end = [], None, None  # asynchronous classes never block time
    return ScheduledClass(
        term=term,
        course=normalize.course(row.course),
        title=row.title.strip(),
        crn=_blank(row.crn),
        section=_blank(row.section),
        professor=_blank(row.professor),
        units=normalize.units(row.units),
        location=_blank(row.location),
        mode=mode,
        days=days,
        start_time=start,
        end_time=end,
        start_date=first,
        end_date=last,
        flags=flags,
        confirmed=False,
    )


class _Cache:
    """Parsed rows by file hash, least recently used evicted first."""

    def __init__(self, size: int = CACHE_SIZE):
        self.size = size
        self._rows: OrderedDict[str, list[_Row]] = OrderedDict()
        self._lock = threading.Lock()

    def get(self, key: str) -> list[_Row] | None:
        with self._lock:
            if key in self._rows:
                self._rows.move_to_end(key)
                return self._rows[key]
            return None

    def put(self, key: str, rows: list[_Row]) -> None:
        with self._lock:
            self._rows[key] = rows
            self._rows.move_to_end(key)
            while len(self._rows) > self.size:
                self._rows.popitem(last=False)


cache = _Cache()


def check_upload_type(media_type: str | None) -> None:
    if media_type == "image/heic":
        raise UnsupportedUpload("HEIC isn't supported; export the photo as JPEG or PNG")
    if media_type not in UPLOAD_TYPES:
        raise UnsupportedUpload(f"Upload a {UPLOAD_TYPES_LABEL} file")


async def parse_schedule(data: bytes, media_type: str) -> list[ScheduledClass]:
    """Uploaded file → unconfirmed rows, with flags for the confirm table."""
    check_upload_type(media_type)
    if len(data) > MAX_UPLOAD_BYTES:
        raise UploadTooLarge("Schedule must be under 20 MB")
    if not data:
        raise UnreadableSchedule("The uploaded file is empty")

    key = hashlib.sha256(media_type.encode() + b"\0" + data).hexdigest()
    rows = cache.get(key)
    if rows is None:
        claude_limits.limiter.take_daily()
        rows = await extract_rows(data, media_type)
        cache.put(key, rows)
    classes = [to_class(r) for r in rows]
    if not classes:
        raise UnreadableSchedule("No classes were found in this file; upload your class schedule page")
    return classes
