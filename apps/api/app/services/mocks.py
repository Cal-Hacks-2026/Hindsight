"""Phase 0 mock data, in exact contract shape.

Every value here is fake and is replaced in Phase 1–3 (see PHASES.md).
Labels are prefixed "MOCK" so nothing here can pass as a real claim.
"""

from datetime import datetime, timezone

from app.models import (
    AgentEvent,
    Course,
    Semester,
    SemesterCourse,
)


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


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


def agent_events(run_id: str) -> list[AgentEvent]:
    t = now_iso()
    return [
        AgentEvent(run_id=run_id, kind="plan", message="MOCK · Scan SJSU sources, rank, write alerts",
                   payload={"sources": 3}, created_at=t),
        AgentEvent(run_id=run_id, kind="step", message="MOCK · Ran campus Actor", created_at=t),
        AgentEvent(run_id=run_id, kind="result", message="MOCK · 2 new opportunities, 1 alert",
                   payload={"new": 2, "alerts": 1}, created_at=t),
    ]
