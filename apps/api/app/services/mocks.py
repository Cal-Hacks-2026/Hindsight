"""Phase 0 mock data, in exact contract shape.

Every value here is fake and is replaced in Phase 1–3 (see PHASES.md).
Citation labels are prefixed "MOCK" so nothing here can pass as a real claim.
"""

from datetime import datetime, timedelta, timezone

from app.models import (
    AgentEvent,
    AssistMajor,
    Citation,
    Course,
    MatchResult,
    MatchSummary,
    RankedOpportunity,
    Requirement,
    Semester,
    SemesterCourse,
)

ASSIST_URL = "https://assist.org/"
MOCK_AGREEMENT_KEY = "MOCK/113/to/39/Major/mock-key"


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _assist_citation(major_label: str, ref: str) -> Citation:
    return Citation(
        source="assist",
        label=f"MOCK · De Anza → SJSU {major_label} (2026–27)",
        url=ASSIST_URL,
        ref=ref,
    )


def transcript_courses() -> list[Course]:
    rows = [
        ("MATH", "1A", "Calculus I", 5, "A", "Fall 2023", 74),
        ("MATH", "1B", "Calculus II", 5, "A-", "Winter 2024", 74),
        ("MATH", "1C", "Calculus III", 5, "B+", "Spring 2024", 74),
        ("CIS", "22A", "Beginning Programming Methodologies in C++", 4.5, "A", "Fall 2023", 74),
        ("STAT", "C1000", "Introduction to Statistics", 5, "B", "Fall 2024", 75),
        ("ECON", "1", "Principles of Macroeconomics", 4, "C-", "Winter 2024", 74),
        ("ENGL", "C1001", "Critical Reading, Writing, and Research", 5, "A", "Fall 2024", 75),
    ]
    return [
        Course(
            prefix=p, number=n, title=t, units=u, grade=g, term=term,
            academic_year_id=y, confirmed=False,
        )
        for p, n, t, u, g, term, y in rows
    ]


def assist_majors() -> list[AssistMajor]:
    return [
        AssistMajor(label="Data Science, B.S.", key=f"{MOCK_AGREEMENT_KEY}/ds"),
        AssistMajor(label="Economics, B.A.", key=f"{MOCK_AGREEMENT_KEY}/econ-ba"),
        AssistMajor(label="Economics, B.S.", key=f"{MOCK_AGREEMENT_KEY}/econ-bs"),
        AssistMajor(label="Computer Science, B.S.", key=f"{MOCK_AGREEMENT_KEY}/cs"),
    ]


def match_result(major_label: str) -> MatchResult:
    reqs = [
        Requirement(
            id="req-1", group_title="Calculus", rule="all",
            receiving_course="MATH 30 - Calculus I",
            status="satisfied", satisfied_by=["MATH 1A"], flags=[],
            citation=_assist_citation(major_label, "Group A, row 1"), confidence="high",
        ),
        Requirement(
            id="req-2", group_title="Calculus", rule="all",
            receiving_course="MATH 31 - Calculus II",
            status="satisfied", satisfied_by=["MATH 1B"], flags=[],
            citation=_assist_citation(major_label, "Group A, row 2"), confidence="high",
        ),
        Requirement(
            id="req-3", group_title="Programming", rule="all",
            receiving_course="CS 46A + CS 46B - Intro to Programming / Data Structures",
            status="partial", satisfied_by=["CIS 22A"], flags=["sequence_rule"],
            citation=_assist_citation(major_label, "Group B, row 1"), confidence="medium",
        ),
        Requirement(
            id="req-4", group_title="Economics", rule="n_of", n=1,
            receiving_course="ECON 1A - Principles of Macroeconomics",
            status="missing", satisfied_by=[], flags=["min_grade_C"],
            citation=_assist_citation(major_label, "Group C, row 1"), confidence="high",
        ),
        Requirement(
            id="req-5", group_title="Linear Algebra", rule="all",
            receiving_course="MATH 39 - Linear Algebra I",
            status="at_university", satisfied_by=[], flags=["no_current_articulation"],
            citation=_assist_citation(major_label, "Group D, row 1"), confidence="high",
        ),
        Requirement(
            id="req-6", group_title="Statistics", rule="all",
            receiving_course="STAT 95 - Elementary Statistics",
            status="satisfied", satisfied_by=["STAT C1000"], flags=["renumbered_course"],
            citation=_assist_citation(major_label, "Group D, row 2"), confidence="low",
        ),
    ]
    return MatchResult(
        major_label=major_label,
        agreement_key=MOCK_AGREEMENT_KEY,
        requirements=reqs,
        summary=MatchSummary(
            satisfied=sum(r.status == "satisfied" for r in reqs),
            partial=sum(r.status == "partial" for r in reqs),
            missing=sum(r.status == "missing" for r in reqs),
            at_university=sum(r.status == "at_university" for r in reqs),
        ),
    )


def plan() -> list[Semester]:
    return [
        Semester(term="Spring 2027", courses=[
            SemesterCourse(code="MATH 39", title="Linear Algebra I", units=3,
                           reason="No De Anza articulation; prereq for DS upper division",
                           prereqs=["MATH 31"]),
            SemesterCourse(code="CS 46B", title="Introduction to Data Structures", units=4,
                           reason="Completes the programming sequence", prereqs=["CS 46A"]),
        ]),
        Semester(term="Fall 2027", courses=[
            SemesterCourse(code="DATA 101", title="Data Science Fundamentals", units=3,
                           reason="Core upper-division requirement", prereqs=["MATH 39", "CS 46B"]),
        ]),
    ]


def opportunities() -> list[RankedOpportunity]:
    soon = datetime.now(timezone.utc) + timedelta(days=9)
    return [
        RankedOpportunity(
            id="opp-1", title="MOCK · AI Student Builders Program", type="program",
            org="Example AI Co.", url="https://example.com/mock-program",
            deadline=soon.isoformat(), score=0.92,
            reason="MOCK · Matches your Data Science major and AI interest; closes in 9 days.",
        ),
        RankedOpportunity(
            id="opp-2", title="MOCK · Hackathon travel funding", type="hackathon",
            org="Example Club", url="https://example.com/mock-hackathon",
            starts_at=(soon + timedelta(days=14)).isoformat(), score=0.78,
            reason="MOCK · Club-funded trip; transfers welcome.",
        ),
    ]


def counselor_reply(message: str) -> tuple[str, list[Citation]]:
    reply = (
        "MOCK counselor reply. In Phase 3 this is answered by Claude, grounded in your "
        f"confirmed courses and match results. You asked: “{message}”"
    )
    return reply, [_assist_citation("Data Science, B.S.", "Group A")]


def agent_events(run_id: str) -> list[AgentEvent]:
    t = now_iso()
    return [
        AgentEvent(run_id=run_id, kind="plan", message="MOCK · Scan SJSU sources, rank, write alerts",
                   payload={"sources": 3}, created_at=t),
        AgentEvent(run_id=run_id, kind="step", message="MOCK · Ran campus Actor", created_at=t),
        AgentEvent(run_id=run_id, kind="result", message="MOCK · 2 new opportunities, 1 alert",
                   payload={"new": 2, "alerts": 1}, created_at=t),
    ]
