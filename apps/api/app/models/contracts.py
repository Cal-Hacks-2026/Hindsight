"""Pydantic mirror of packages/contracts/src/index.ts (PROJECT.md §10).

Keep the two files in lockstep. Optional fields default to None and routes
serialize with response_model_exclude_none so they're omitted, matching the
TS `field?: T` shape.
"""

from typing import Any, Literal

from pydantic import BaseModel

Campus = Literal["sjsu", "berkeley"]  # campuses with Radar sources
# A profile's campus comes from receiving_institution_id (config.campus_for); "other" is any
# ASSIST university without Radar sources or curated requirements.
ProfileCampus = Literal["sjsu", "berkeley", "other"]
GePattern = Literal["calgetc", "igetc"]  # GE progress (feature: GE)

# ---- SKELETON: where the student is now, asked before the pathway ----
ProfileStage = Literal["high_school", "community_college", "transferred", "returning"]


class CreateProfileRequest(BaseModel):
    name: str
    campus: ProfileCampus
    sending_institution_id: int
    receiving_institution_id: int
    majors: list[str]
    goals: str
    interests: list[str]
    # SKELETON: optional so older profiles and clients still validate.
    stage: ProfileStage | None = None
    minor: str | None = None


class Profile(CreateProfileRequest):
    id: str
    created_at: str
    # ASSIST's names for the two institutions, filled in by the API when it can (not stored).
    sending_institution_name: str | None = None
    receiving_institution_name: str | None = None


class Course(BaseModel):
    prefix: str
    number: str
    title: str
    units: float
    grade: str
    term: str
    academic_year_id: int | None = None
    confirmed: bool


class Citation(BaseModel):
    source: Literal["assist", "catalog", "web"]
    label: str
    url: str
    ref: str | None = None


class Requirement(BaseModel):
    id: str
    group_title: str
    rule: Literal["all", "n_of"]
    n: int | None = None
    receiving_course: str
    status: Literal["satisfied", "partial", "missing", "at_university", "in_progress"]
    satisfied_by: list[str]
    flags: list[str]
    # What to take at the sending college, for rows not yet satisfied (I-02).
    options: list[str] | None = None
    citation: Citation
    confidence: Literal["high", "medium", "low"]


class MatchSummary(BaseModel):
    satisfied: int
    partial: int
    missing: int
    at_university: int
    in_progress: int = 0


class MatchResult(BaseModel):
    major_label: str
    agreement_key: str
    requirements: list[Requirement]
    summary: MatchSummary


class SemesterCourse(BaseModel):
    code: str
    title: str
    units: float
    reason: str
    prereqs: list[str]
    # ---- GE progress (feature: GE), only with /plan?ge=true ----
    # The GE area this course fills, e.g. "Cal-GETC 3A". A GE slot (pick any approved course)
    # also has `ge_options`, the approved courses at the college; a major course that also
    # counts for an area has `ge_area` only.
    ge_area: str | None = None
    ge_options: list[str] | None = None


class Semester(BaseModel):
    term: str
    courses: list[SemesterCourse]
    # Two-phase roadmap (I-03): community-college terms before transfer, university terms after.
    phase: Literal["before_transfer", "after_transfer"] | None = None
    institution: str | None = None  # e.g. "De Anza College"
    term_system: Literal["quarter", "semester"] | None = None  # how `units` are counted


class RankedOpportunity(BaseModel):
    id: str
    title: str
    type: str
    org: str
    url: str
    starts_at: str | None = None
    deadline: str | None = None
    score: float
    reason: str
    notified: bool = False  # Droid alerted on it (profile_opportunities.notified)


class AgentEvent(BaseModel):
    run_id: str
    kind: Literal["plan", "step", "diff", "result", "error"]
    message: str
    payload: Any | None = None
    created_at: str


class ChatMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str


class AssistMajor(BaseModel):
    label: str
    key: str


class AssistInstitution(BaseModel):
    id: int
    name: str
    term_system: Literal["quarter", "semester"] | None = None  # community colleges
    # Universities, for one community college: the ASSIST year their agreements are read from
    # (2026–27 = 77, or the latest year published before it) and whether we have curated
    # requirements for a full degree plan.
    year_id: int | None = None
    full_plan: bool | None = None


# ---- Request / response envelopes ----


class ProfileResponse(BaseModel):
    profile: Profile


class CoursesResponse(BaseModel):
    courses: list[Course]


class UpdateCoursesRequest(BaseModel):
    courses: list[Course]


class AssistMajorsResponse(BaseModel):
    majors: list[AssistMajor]
    # MAJORS-FALLBACK: set ("2026-10-25", UTC) only when ASSIST failed and the pair's list kept
    # from its last live load was used.
    saved_on: str | None = None


class AssistInstitutionsResponse(BaseModel):
    institutions: list[AssistInstitution]


class MatchRequest(BaseModel):
    major_label: str


class PlanResponse(BaseModel):
    semesters: list[Semester]  # before-transfer terms first, then after-transfer terms
    uncurated_majors: list[str] | None = None  # chosen majors left out: no curated requirements yet
    transfer_term: str | None = None  # when the after-transfer terms start
    earliest_transfer_term: str | None = None  # the first Fall after the before-transfer terms finish
    start_term: str | None = None  # first community-college term
    default_start_term: str | None = None  # next Fall with no courses yet, else the next registrable term
    start_term_choices: list[str] | None = None  # community-college terms the student can start in
    # Community-college courses that don't fit before a requested transfer_term; their
    # university equivalents are planned after transfer instead.
    not_before_transfer: list[str] | None = None
    # False when we don't have the university's degree requirements: no after-transfer terms.
    full_plan: bool | None = None
    # ---- GE progress (feature: GE), only with ?ge=true ----
    # The GE pattern planned before transfer, and the GE areas ("Cal-GETC 3A") that don't fit
    # before a requested transfer term.
    ge_pattern: GePattern | None = None
    ge_not_before_transfer: list[str] | None = None


class OpportunitiesResponse(BaseModel):
    items: list[RankedOpportunity]


class CounselorRequest(BaseModel):
    message: str
    history: list[ChatMessage]


class CounselorResponse(BaseModel):
    reply: str
    citations: list[Citation]


class AgentRunRequest(BaseModel):
    campus: Campus


class AgentRunResponse(BaseModel):
    run_id: str


class AgentEventsResponse(BaseModel):
    events: list[AgentEvent]


class AgentLatestRunResponse(BaseModel):
    run_id: str | None  # null until a run has logged for the campus


class WebhookResponse(BaseModel):
    ok: Literal[True]


class HealthResponse(BaseModel):
    status: Literal["ok"]
    app: str
    storage: bool = True
    claude: bool = True


# ---- University guide (UNIVERSITY) ----
# "What to Expect" at the student's university: short sections written only from official or
# institutional pages, every item citing them (GET /universities/{id}/guide).

GuideSectionId = Literal["transfer_services", "academics", "getting_around", "housing", "student_life",
                         "first_semester"]


class GuideSource(BaseModel):
    id: str
    title: str
    publisher: str  # e.g. "SJSU University Housing Services", "Associated Students, SJSU"
    url: str
    retrieved_on: str  # YYYY-MM-DD the page was read


class GuideItem(BaseModel):
    text: str
    source_ids: list[str]  # ids in UniversityGuide.sources; never empty


class GuideSection(BaseModel):
    id: GuideSectionId
    title: str
    items: list[GuideItem]
    # Opportunities categories (RankedOpportunity.type) worth linking from this section.
    opportunity_types: list[str] | None = None


class UniversityGuide(BaseModel):
    university_id: int  # ASSIST institution id (39 = SJSU)
    university_name: str
    last_updated: str  # YYYY-MM-DD the sources were last read
    sections: list[GuideSection]
    sources: list[GuideSource]  # cited sources, in footnote order


class UniversityGuideResponse(BaseModel):
    university_id: int
    available: bool  # false: no guide for this university yet
    university_name: str | None = None
    guide: UniversityGuide | None = None


# ---- Class schedule (SCHEDULE) ----

ClassMode = Literal["in_person", "online", "hybrid", "asynchronous"]
Weekday = Literal["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


class ScheduledClass(BaseModel):
    """One meeting pattern of a class; a lecture plus a lab is two rows with the same CRN."""

    term: str
    course: str  # as printed, e.g. "MATH 1B" or "MATH D001B"
    title: str
    crn: str | None = None
    section: str | None = None
    professor: str | None = None
    units: float | None = None
    location: str | None = None
    mode: ClassMode
    days: list[Weekday]  # empty for asynchronous or TBA
    start_time: str | None = None  # "HH:MM", 24-hour
    end_time: str | None = None
    start_date: str | None = None  # "YYYY-MM-DD", when the schedule prints class dates
    end_date: str | None = None
    # Upload only, for the confirm table: why a row needs a second look (never stored).
    flags: list[str] | None = None
    confirmed: bool


class ScheduleTerm(BaseModel):
    term: str
    units: float  # each class counted once, however many meeting rows it has
    classes: int


class ScheduleResponse(BaseModel):
    rows: list[ScheduledClass]
    terms: list[ScheduleTerm] | None = None  # saved schedules only


class UpdateScheduleRequest(BaseModel):
    rows: list[ScheduledClass]


class FreeBlock(BaseModel):
    start: str  # "HH:MM"
    end: str
    minutes: int


class FreeDay(BaseModel):
    day: Weekday
    date: str  # "YYYY-MM-DD"
    blocks: list[FreeBlock]


class FreeBlocksResponse(BaseModel):
    week: str  # the Monday, "YYYY-MM-DD"
    day_start: str  # "07:00"
    day_end: str  # "22:00"
    days: list[FreeDay]  # Mon–Sun


class ScheduledPlanCourse(BaseModel):
    code: str  # the plan's course code
    planned_term: str
    scheduled_term: str
    crn: str | None = None


class ScheduledPlanResponse(BaseModel):
    courses: list[ScheduledPlanCourse]  # planned courses that are on the saved schedule


# ---- GE progress (feature: GE): GET /profiles/{id}/ge ----


class GeCourse(BaseModel):
    code: str  # as on the transcript, e.g. "EWRT 1A"
    title: str
    units: float
    grade: str
    term: str
    # pass_no_pass, igetc_course (an IGETC course from before Fall 2025 used for Cal-GETC),
    # calgetc_course (a Cal-GETC course used for IGETC), below_c (on the list but under a C)
    flags: list[str]
    citation: Citation  # the ASSIST list for the year the course was taken


class GeOption(BaseModel):
    code: str
    title: str
    units: float


class GeArea(BaseModel):
    code: str  # "1A", "2", "4", …
    title: str
    status: Literal["done", "in_progress", "missing"]
    courses_required: int
    still_needed: int  # courses still to take (in-progress ones count as taken)
    units: float  # of the courses that count, in the college's units
    units_required: float
    courses: list[GeCourse]  # the student's courses that count here
    options: list[GeOption] | None = None  # approved at the student's college, for areas not done
    not_counted: list[GeCourse] | None = None  # on the list, but the grade doesn't count
    note: str | None = None
    citation: Citation
    # False for an IGETC area the student's university system doesn't require (1C is CSU only,
    # 6 is UC only); left out of the summary.
    required: bool = True


class GeSummary(BaseModel):
    done: int
    in_progress: int
    missing: int


class GeResponse(BaseModel):
    pattern: GePattern
    pattern_name: str  # "Cal-GETC" or "IGETC"
    default_pattern: GePattern  # from when the student started; ?pattern= overrides it
    rule: str  # why this pattern, in a sentence or two
    rule_citation: Citation
    started_term: str | None = None  # first community-college term on the transcript
    institution: str | None = None
    term_system: Literal["quarter", "semester"]
    options_year: str  # ASSIST year the options come from, e.g. "2026-2027"
    areas: list[GeArea]
    summary: GeSummary
    citations: list[Citation]  # ASSIST lists and standards used
