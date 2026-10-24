"""Planner v1: remaining major requirements → semesters (PHASES.md Phase 1, step 6).

Reads curated majors from data/requirements/*.json, drops what the student has
already satisfied, then schedules the rest term by term: a course goes in only once
all its prerequisites are done in an earlier term, it's offered that term, and the
term stays under the unit cap. Courses that unlock the longest chains go first.

Deterministic: Claude doesn't take part in planning.
"""

import json
import os
import re
from collections.abc import Iterable
from datetime import date
from pathlib import Path
from typing import Literal

from pydantic import BaseModel

from app.models import Course, MatchResult, Semester, SemesterCourse

REQUIREMENTS_DIR = Path(
    os.getenv("REQUIREMENTS_DIR") or Path(__file__).resolve().parents[4] / "data" / "requirements"
)
DEFAULT_UNIT_CAP = 15.0
PLAN_SEASONS = ("Spring", "Fall")  # SJSU regular terms; summer/winter aren't planned
MAX_TERMS = 16
PLACEHOLDER_PREFIX = "PLACEHOLDER · "

Season = Literal["Fall", "Spring"]


class PlannerError(Exception):
    status = 422


class UnknownMajor(PlannerError):
    status = 404


# ---- Curated requirements file format (data/requirements/README.md) ----


class CatalogCourse(BaseModel):
    title: str
    units: float
    prereqs: list[str] = []
    terms_offered: list[Season] = ["Fall", "Spring"]
    source_url: str


class RequirementGroup(BaseModel):
    id: str
    title: str
    rule: Literal["all", "n_of"]
    n: int | None = None
    courses: list[str]
    source_url: str


class Major(BaseModel):
    placeholder: bool = False
    major_label: str
    campus: str
    catalog_year: str
    source_url: str
    courses: dict[str, CatalogCourse]
    groups: list[RequirementGroup]


def _check(major: Major, path: Path) -> None:
    known = major.courses.keys()
    for group in major.groups:
        missing = [c for c in group.courses if c not in known]
        if missing:
            raise ValueError(f"{path.name}: group {group.id} lists unknown courses {missing}")
        if group.rule == "n_of" and not (group.n and 0 < group.n <= len(group.courses)):
            raise ValueError(f"{path.name}: group {group.id} needs 0 < n <= {len(group.courses)}")
    # Prereqs may point outside this file (shared with another major), but never in a cycle.
    visiting, done = set(), set()

    def visit(code: str, trail: list[str]) -> None:
        if code in done or code not in known:
            return
        if code in visiting:
            raise ValueError(f"{path.name}: prerequisite cycle {' → '.join(trail + [code])}")
        visiting.add(code)
        for p in major.courses[code].prereqs:
            visit(p, trail + [code])
        visiting.discard(code)
        done.add(code)

    for code in known:
        visit(code, [])


def load_majors(directory: Path = REQUIREMENTS_DIR) -> list[Major]:
    """Read every curated major. Re-read per request so curated edits show up without a restart."""
    majors = []
    for path in sorted(directory.glob("*.json")):
        major = Major.model_validate(json.loads(path.read_text()))
        _check(major, path)
        majors.append(major)
    return majors


def resolve_majors(raw: str | None, default: list[str], campus: str, majors: list[Major]) -> list[Major]:
    """Pick majors by label for the profile's campus.

    `raw` is the comma-separated ?majors= value. Labels contain commas themselves
    ("Data Science, B.S."), so pieces are re-joined until they form a known label.
    """
    by_label = {m.major_label.casefold(): m for m in majors if m.campus == campus}
    if raw is None:
        labels = default
    else:
        labels, pending = [], ""
        for piece in raw.split(","):
            pending = f"{pending},{piece}" if pending else piece
            if pending.strip().casefold() in by_label:
                labels.append(pending.strip())
                pending = ""
        if pending.strip():
            labels.append(pending.strip())

    unknown = [label for label in labels if label.casefold() not in by_label]
    if unknown or not labels:
        available = sorted(m.major_label for m in by_label.values())
        raise UnknownMajor(f"No curated requirements for {unknown or 'any major'} at {campus}; available: {available}")
    return list({by_label[label.casefold()].major_label: by_label[label.casefold()] for label in labels}.values())


# ---- What's already done ----

COURSE_CODE = re.compile(r"\b([A-Z]{2,5})\s+(\d+[A-Z]{0,2})\b")


def satisfied_from_match(result: MatchResult) -> set[str]:
    """University course codes the matcher marked satisfied, e.g. 'MATH 30 - Calculus I' → {'MATH 30'}."""
    codes = set()
    for req in result.requirements:
        if req.status == "satisfied":
            title_free = req.receiving_course.split(" - ")[0]
            codes.update(f"{p} {n}" for p, n in COURSE_CODE.findall(title_free))
    return codes


def satisfied_from_courses(courses: Iterable[Course]) -> set[str]:
    """Courses taken directly at the university appear on the transcript under the same code."""
    return {f"{c.prefix} {c.number}" for c in courses if c.confirmed}


# ---- Scheduling ----


def next_term(today: date) -> tuple[Season, int]:
    """First regular term a student can still register for."""
    return ("Fall", today.year) if today.month <= 7 else ("Spring", today.year + 1)


def _terms(start: tuple[Season, int]):
    season, year = start
    while True:
        yield season, year
        season, year = ("Fall", year) if season == "Spring" else ("Spring", year + 1)


def build_plan(
    majors: list[Major],
    satisfied: set[str],
    today: date | None = None,
    unit_cap: float = DEFAULT_UNIT_CAP,
) -> list[Semester]:
    catalog: dict[str, CatalogCourse] = {}
    for major in majors:
        catalog.update(major.courses)
    placeholder = any(m.placeholder for m in majors)
    reasons: dict[str, list[str]] = {}

    def need(code: str, reason: str) -> None:
        reasons.setdefault(code, [])
        if reason not in reasons[code]:
            reasons[code].append(reason)

    def open_prereqs(code: str) -> list[str]:
        return [p for p in catalog[code].prereqs if p in catalog and p not in satisfied]

    def chain_depth(code: str) -> int:
        return 1 + max((chain_depth(p) for p in open_prereqs(code)), default=0)

    # 1. Requirements still open.
    for major in majors:
        for group in major.groups:
            remaining = [c for c in group.courses if c not in satisfied]
            if group.rule == "all":
                for code in remaining:
                    need(code, f"{group.title} ({major.major_label})")
                continue
            still_needed = group.n - (len(group.courses) - len(remaining))
            # Prefer electives that are already planned for another major, then the shortest prereq chain.
            picks = sorted(remaining, key=lambda c: (c not in reasons, chain_depth(c), c))[: max(still_needed, 0)]
            for i, code in enumerate(picks, 1):
                need(code, f"{group.title}: pick {i} of {len(picks)} still needed ({major.major_label}); any listed elective works")

    # 2. Pull in unfinished prerequisites, transitively.
    stack = list(reasons)
    while stack:
        code = stack.pop()
        for p in open_prereqs(code):
            if p not in reasons:
                stack.append(p)
            need(p, f"Prerequisite for {code}")

    # 3. Longest downstream chain first, so bottleneck courses don't slip a term.
    unlocks: dict[str, list[str]] = {c: [] for c in reasons}
    for code in reasons:
        for p in open_prereqs(code):
            unlocks[p].append(code)

    def height(code: str) -> int:
        return 1 + max((height(n) for n in unlocks[code]), default=0)

    remaining = set(reasons)
    done = set(satisfied)
    semesters: list[Semester] = []
    idle_terms = 0
    for season, year in _terms(next_term(today or date.today())):
        if not remaining:
            break
        if len(semesters) >= MAX_TERMS or idle_terms >= len(PLAN_SEASONS):
            raise PlannerError(f"Couldn't schedule {sorted(remaining)}; check prerequisites and terms offered")
        eligible = sorted(
            (c for c in remaining if season in catalog[c].terms_offered and all(p in done for p in open_prereqs(c))),
            key=lambda c: (-height(c), c),
        )
        picked, units = [], 0.0
        for code in eligible:
            if units + catalog[code].units <= unit_cap or not picked:
                picked.append(code)
                units += catalog[code].units
        idle_terms = 0 if picked else idle_terms + 1
        if not picked:
            continue
        semesters.append(Semester(
            term=f"{season} {year}",
            courses=[
                SemesterCourse(
                    code=code,
                    title=catalog[code].title,
                    units=catalog[code].units,
                    reason=(PLACEHOLDER_PREFIX if placeholder else "") + "; ".join(reasons[code]),
                    prereqs=catalog[code].prereqs,
                )
                for code in picked
            ],
        ))
        remaining.difference_update(picked)
        done.update(picked)  # only usable from the next term on: eligibility is computed before picking
    return semesters
