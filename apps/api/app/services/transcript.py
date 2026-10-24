"""Transcript parsing: PDF/image → Claude → unconfirmed Course[] (PROJECT.md §6, §8.1).

Claude only transcribes rows. Everything that drives matching — normalizing codes
and terms, the academic year, and course-renumbering flags — is deterministic code
here, and the student confirms the list before anything is matched.

The Course contract has no confidence/flags field, so renumbering notes travel
beside it: `assess()` is pure and can be re-run by the matcher on confirmed
courses, and the route also returns the notes in the X-Transcript-Notes header.
"""

import base64
import os
import re
from typing import Literal

import anthropic
from pydantic import BaseModel

from app.models import Course

DEFAULT_MODEL = "claude-opus-5-5"
# Models that accept server-side refusal fallbacks (`fallbacks: "default"`).
FALLBACK_MODELS = {"claude-opus-5-5", "claude-opus-5", "claude-fable-5-1", "claude-sonnet-5-5"}
MAX_UPLOAD_BYTES = 20 * 1024 * 1024

IMAGE_TYPES = {"image/png", "image/jpeg", "image/webp", "image/gif"}
PDF_TYPE = "application/pdf"

# CA community college Common Course Numbering went live Fall 2025 (academic year
# 2025–26, ASSIST year id 76). Phase I courses; extend as later phases roll out.
CCN_START_YEAR_ID = 76
CCN_COURSES = {"COMM C1000", "ENGL C1000", "ENGL C1001", "POLS C1000", "PSYC C1000", "STAT C1000"}
CCN_SUBJECTS = {code.split()[0] for code in CCN_COURSES}
CCN_NUMBER = re.compile(r"^C\d{4}[A-Z]{0,2}$")

SEASONS = ("Fall", "Winter", "Spring", "Summer")
TERM = re.compile(r"^(Fall|Winter|Spring|Summer)\s+(\d{4})$", re.IGNORECASE)

Confidence = Literal["high", "medium", "low"]


class TranscriptError(Exception):
    """Base class; `status` is the HTTP status the route should return."""

    status = 502


class UnsupportedUpload(TranscriptError):
    status = 415


class UploadTooLarge(TranscriptError):
    status = 413


class ParsingUnavailable(TranscriptError):
    status = 503


class UnreadableTranscript(TranscriptError):
    status = 422


class CourseNote(BaseModel):
    code: str
    term: str
    confidence: Confidence
    flags: list[str]


# ---- Claude extraction ----


class _Row(BaseModel):
    prefix: str
    number: str
    title: str
    units: float
    grade: str
    term: str
    legible: bool


class _Extraction(BaseModel):
    courses: list[_Row]


SYSTEM = """You transcribe California community college transcripts into structured rows.
Copy what is printed; never infer, correct, or fill in a value that is not on the page.

One row per course attempt, including repeats, withdrawals (grade "W"), and in-progress
courses (grade "IP"). Skip term/cumulative totals, GPA lines, and test credit (AP/IB/CLEP).
- prefix: subject code exactly as printed, e.g. "MATH", "CIS", "ENGL".
- number: course number exactly as printed, e.g. "1A", "22A", "C1001".
- title: course title as printed.
- units: units attempted as a number.
- grade: letter grade as printed with +/- (e.g. "A-"), or "P", "NP", "W", "IP". Empty string if none.
- term: "<Season> <YYYY>" with Season one of Fall, Winter, Spring, Summer, e.g. "Winter 2024".
  If the term is printed some other way, convert only when unambiguous; otherwise copy it as printed.
- legible: false if any field of the row was hard to read or you are unsure of it."""


def _content_block(data: bytes, media_type: str) -> dict:
    encoded = base64.standard_b64encode(data).decode()
    if media_type == PDF_TYPE:
        return {"type": "document", "source": {"type": "base64", "media_type": PDF_TYPE, "data": encoded}}
    return {"type": "image", "source": {"type": "base64", "media_type": media_type, "data": encoded}}


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
                    {"type": "text", "text": "Transcribe every course row on this transcript."},
                ],
            }],
            output_format=_Extraction,
            **fallback,
        )
    except (anthropic.AuthenticationError, anthropic.PermissionDeniedError) as e:
        raise ParsingUnavailable("Transcript parsing is not configured (Anthropic credentials)") from e
    except anthropic.BadRequestError as e:
        raise UnreadableTranscript("Claude could not read this file; try a clearer PDF or image") from e
    except (anthropic.RateLimitError, anthropic.APIConnectionError) as e:
        raise ParsingUnavailable("Transcript parser is busy; try again in a moment") from e
    except anthropic.APIStatusError as e:
        raise TranscriptError(f"Transcript parser failed ({e.status_code})") from e

    if response.stop_reason == "refusal":
        raise UnreadableTranscript("Claude declined to read this file")
    if response.stop_reason == "max_tokens" or response.parsed_output is None:
        raise TranscriptError("Transcript parser returned an incomplete result")
    return response.parsed_output.courses


# ---- Deterministic normalization ----


def normalize_term(raw: str) -> str | None:
    """'fall  2023' → 'Fall 2023'. None if not in '<Season> <YYYY>' form."""
    m = TERM.match(raw.strip())
    return f"{m.group(1).capitalize()} {m.group(2)}" if m else None


def academic_year_id(term: str) -> int | None:
    """ASSIST academic year id (fall year − 1949) for a normalized term.

    Fall Y starts year Y; Winter/Spring/Summer Y belong to the year that began Fall Y−1.
    """
    m = TERM.match(term)
    if not m:
        return None
    season, year = m.group(1).capitalize(), int(m.group(2))
    fall_year = year if season == "Fall" else year - 1
    return fall_year - 1949


def _code(prefix: str, number: str) -> str:
    return f"{prefix} {number}"


def to_course(row: _Row) -> Course:
    term = normalize_term(row.term)
    return Course(
        prefix=row.prefix.strip().upper(),
        number=re.sub(r"\s+", "", row.number).upper(),
        title=row.title.strip(),
        units=row.units,
        grade=row.grade.strip().upper(),
        term=term or row.term.strip(),
        academic_year_id=academic_year_id(term) if term else None,
        confirmed=False,
    )


def assess(course: Course, legible: bool = True) -> CourseNote:
    """Renumbering-aware confidence for one course; safe to re-run after confirmation.

    The matcher must look the course up in the agreement for the year it was taken
    (PROJECT.md §8.1). These flags say how much to trust that lookup.
    """
    code = _code(course.prefix, course.number)
    year = course.academic_year_id
    flags: list[str] = []
    confidence: Confidence = "high"

    def lower(to: Confidence) -> None:
        nonlocal confidence
        order = ("high", "medium", "low")
        confidence = max(confidence, to, key=order.index)

    if not legible:
        flags.append("unclear_scan")
        lower("low")
    if year is None:
        # No agreement year to look the course up in.
        flags.append("term_unparsed")
        lower("low")

    if CCN_NUMBER.match(course.number):
        flags.append("common_course_number")
        if year is not None and year < CCN_START_YEAR_ID:
            # A C-number before the rollout is likely a misread or a reissued transcript.
            flags.append("ccn_before_rollout")
            lower("low")
        elif code not in CCN_COURSES:
            flags.append("ccn_unrecognized")
            lower("medium")
    elif course.prefix in CCN_SUBJECTS and year is not None:
        if year < CCN_START_YEAR_ID:
            # Old number; valid in its own year's agreement, renumbered since.
            flags.append("pre_ccn_number")
        else:
            # Old-style number taken after the rollout: may be renumbered or not yet converted.
            flags.append("legacy_number_after_ccn")
            lower("medium")

    return CourseNote(code=code, term=course.term, confidence=confidence, flags=flags)


async def parse_transcript(data: bytes, media_type: str) -> tuple[list[Course], list[CourseNote]]:
    """Uploaded file → (unconfirmed courses, per-course renumbering notes), index-aligned."""
    if media_type == "image/heic":
        raise UnsupportedUpload("HEIC isn't supported; export the photo as JPEG or PNG")
    if media_type != PDF_TYPE and media_type not in IMAGE_TYPES:
        raise UnsupportedUpload("Upload a PDF or image")
    if len(data) > MAX_UPLOAD_BYTES:
        raise UploadTooLarge("Transcript must be under 20 MB")
    if not data:
        raise UnreadableTranscript("The uploaded file is empty")

    rows = await extract_rows(data, media_type)
    courses = [to_course(r) for r in rows]
    notes = [assess(c, legible=r.legible) for c, r in zip(courses, rows)]
    return courses, notes
