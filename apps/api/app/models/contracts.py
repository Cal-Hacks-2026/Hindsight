"""Pydantic mirror of packages/contracts/src/index.ts (PROJECT.md §10).

Keep the two files in lockstep. Optional fields default to None and routes
serialize with response_model_exclude_none so they're omitted, matching the
TS `field?: T` shape.
"""

from typing import Any, Literal

from pydantic import BaseModel

Campus = Literal["sjsu", "berkeley"]


class CreateProfileRequest(BaseModel):
    name: str
    campus: Campus
    sending_institution_id: int
    receiving_institution_id: int
    majors: list[str]
    goals: str
    interests: list[str]


class Profile(CreateProfileRequest):
    id: str
    created_at: str


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


# ---- Request / response envelopes ----


class ProfileResponse(BaseModel):
    profile: Profile


class CoursesResponse(BaseModel):
    courses: list[Course]


class UpdateCoursesRequest(BaseModel):
    courses: list[Course]


class AssistMajorsResponse(BaseModel):
    majors: list[AssistMajor]


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
