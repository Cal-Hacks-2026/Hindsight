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
from app.services.assist.evaluator import LETTER_GRADES, grade_verdict

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
    units: float  # the minimum when the catalog gives a range ("1-3 unit(s)")
    units_max: float | None = None
    prereqs: list[str] = []  # all required
    prereqs_one_of: list[list[str]] = []  # each inner list: any one of them
    prereq_text: str | None = None  # the catalog's wording, verbatim
    terms_offered: list[Season] = ["Fall", "Spring"]
    notes: list[str] = []  # catalog wording that matters for planning, verbatim
    needs_review: list[str] = []  # where the catalog is ambiguous; planners and advisors should check
    source_url: str

    def all_prereqs(self) -> list[str]:
        return self.prereqs + [p for group in self.prereqs_one_of for p in group]


class RequirementGroup(BaseModel):
    id: str
    title: str
    rule: Literal["all", "n_of", "units"]
    n: int | None = None  # n_of: how many courses
    units: float | None = None  # units: how many units
    courses: list[str]  # may be empty for a units rule the catalog doesn't list courses for
    notes: list[str] = []
    needs_review: list[str] = []
    source_url: str


class Major(BaseModel):
    placeholder: bool = False
    major_label: str
    campus: str
    catalog_year: str
    source_url: str
    notes: list[str] = []
    needs_review: list[str] = []
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
        if group.rule == "units" and not (group.units and group.units > 0):
            raise ValueError(f"{path.name}: group {group.id} needs units > 0")
        if group.rule != "units" and not group.courses:
            raise ValueError(f"{path.name}: group {group.id} lists no courses")
        if not group.courses and not group.needs_review:
            raise ValueError(f"{path.name}: group {group.id} lists no courses; say why in needs_review")
    # Prereqs may point outside this file (shared with another major), but never in a cycle.
    visiting, done = set(), set()

    def visit(code: str, trail: list[str]) -> None:
        if code in done or code not in known:
            return
        if code in visiting:
            raise ValueError(f"{path.name}: prerequisite cycle {' → '.join(trail + [code])}")
        visiting.add(code)
        for p in major.courses[code].all_prereqs():
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


CAMPUS_NAMES = {"sjsu": "SJSU", "berkeley": "UC Berkeley"}
# The last comma-separated piece of an ASSIST label: "B.S.", "B.F.A.", "B.A. (SJSU Online)".
DEGREE_PIECE = re.compile(r"^B\.[A-Z.]*\s*(\(.*\))?$")


def join_labels(labels: list[str]) -> str:
    """Labels for a sentence. They contain commas themselves, so a longer list uses semicolons."""
    if len(labels) <= 2:
        return " and ".join(labels)
    return "; ".join(labels[:-1]) + "; and " + labels[-1]


def uncurated_message(campus: str, labels: list[str]) -> str:
    return (f"We don't have {CAMPUS_NAMES.get(campus, campus.upper())}'s {join_labels(labels)} requirements yet, "
            "so lower-division only (from ASSIST).")


def _split_labels(raw: str, known: set[str]) -> list[str]:
    """`raw` is the comma-separated ?majors= value. Labels contain commas themselves
    ("Data Science, B.S."), so pieces are re-joined until they form a known label or end
    in a degree ("…, B.S."), the way every ASSIST label does."""
    labels, pending = [], ""
    for piece in raw.split(","):
        pending = f"{pending},{piece}" if pending else piece
        if pending.strip().casefold() in known or DEGREE_PIECE.match(piece.strip()):
            labels.append(pending.strip())
            pending = ""
    if pending.strip():
        labels.append(pending.strip())
    return labels


def resolve_majors(raw: str | None, default: list[str], campus: str,
                   majors: list[Major]) -> tuple[list[Major], list[str]]:
    """Pick majors by label for the profile's campus: (curated majors, labels with no curated requirements).

    Raises UnknownMajor only when none of the labels is curated.
    """
    by_label = {m.major_label.casefold(): m for m in majors if m.campus == campus}
    labels = default if raw is None else _split_labels(raw, set(by_label))
    labels = list(dict.fromkeys(label for label in labels if label.strip()))
    uncurated = [label for label in labels if label.casefold() not in by_label]
    if len(uncurated) == len(labels):
        available = join_labels(sorted(m.major_label for m in by_label.values()))
        if not labels:
            raise UnknownMajor("Choose a major to plan." + (f" Plans are available for {available}." if available else ""))
        raise UnknownMajor(uncurated_message(campus, uncurated)
                           + (f" Plans are available for {available}." if available else ""))
    curated = {by_label[label.casefold()].major_label: by_label[label.casefold()]
               for label in labels if label.casefold() in by_label}
    return list(curated.values()), uncurated


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


IN_PROGRESS = "IP"
# 'minimum grade of "C-"', 'A grade of "C-" or better', 'Grade of "C" or better.'
_CATALOG_MIN_GRADE = re.compile(r'\bgrade of\s*"?([A-D][+-]?)"?', re.I)


def _min_grade_in(notes: list[str]) -> str | None:
    found = [m.upper() for note in notes for m in _CATALOG_MIN_GRADE.findall(note)]
    return max(found, key=LETTER_GRADES.index) if found else None


def minimum_grades(majors: Iterable[Major]) -> dict[str, str]:
    """Lowest passing grade per course code, from the catalog notes of the major and of the
    groups listing the course. Strictest wins when planned majors disagree."""
    out: dict[str, str] = {}

    def require(code: str, grade: str | None) -> None:
        if grade and (code not in out or LETTER_GRADES.index(grade) > LETTER_GRADES.index(out[code])):
            out[code] = grade

    for major in majors:
        for code in major.courses:
            require(code, _min_grade_in(major.notes))
        for group in major.groups:
            for code in group.courses:
                require(code, _min_grade_in(group.notes))
    return out


def _passed(course: Course, min_grade: str | None) -> bool:
    """IP counts: the plan assumes the student passes what they're taking now."""
    if course.grade.strip().upper() == IN_PROGRESS:
        return True
    return grade_verdict(course.grade, min_grade, letter_required=False) in ("ok", "pass_no_pass")


def satisfied_from_courses(courses: Iterable[Course], majors: Iterable[Major] = ()) -> set[str]:
    """Courses taken directly at the university appear on the transcript under the same code.
    W, F, NP and grades below the requirement's minimum don't count."""
    mins = minimum_grades(majors)
    codes = set()
    for c in courses:
        code = f"{c.prefix} {c.number}"
        if c.confirmed and _passed(c, mins.get(code)):
            codes.add(code)
    return codes


def assume_in_progress_passed(courses: Iterable[Course]) -> list[Course]:
    """Courses to match against ASSIST for planning: an IP course is treated as passed (P), so
    the plan doesn't reschedule what the student is taking now. Not for reporting a match."""
    return [c.model_copy(update={"grade": "P"}) if c.grade.strip().upper() == IN_PROGRESS else c for c in courses]


def satisfied(courses: Iterable[Course], matches: Iterable[MatchResult], majors: Iterable[Major] = ()) -> set[str]:
    """Done = passed on the transcript, or marked satisfied by the ASSIST match for one of the planned majors."""
    codes = satisfied_from_courses(courses, majors)
    for result in matches:
        codes |= satisfied_from_match(result)
    return codes


# ---- Scheduling ----


def next_term(today: date) -> tuple[Season, int]:
    """First regular term a student can still register for."""
    return ("Fall", today.year) if today.month <= 7 else ("Spring", today.year + 1)


def _terms(start: tuple[Season, int]):
    season, year = start
    while True:
        yield season, year
        season, year = ("Fall", year) if season == "Spring" else ("Spring", year + 1)


def unscheduled_groups(majors: list[Major]) -> list[tuple[Major, RequirementGroup]]:
    """Requirements the catalog states without a course list (e.g. "9 units from one other
    major"). The planner can't schedule them, so whoever shows a plan must say so."""
    return [(m, g) for m in majors for g in m.groups if not g.courses]


def prereq_labels(course: CatalogCourse) -> list[str]:
    """Prerequisites as shown to students: 'CS 46A or CS 46AX' for a one-of group."""
    return course.prereqs + [" or ".join(group) for group in course.prereqs_one_of]


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
    fixed: dict[str, list[str]] = {}  # open prereqs per course, once its one-of choices are made

    def need(code: str, reason: str) -> None:
        reasons.setdefault(code, [])
        if reason not in reasons[code]:
            reasons[code].append(reason)

    def open_prereqs(code: str) -> list[str]:
        if code in fixed:
            return fixed[code]
        course = catalog[code]
        out = [p for p in course.prereqs if p in catalog and p not in satisfied]
        for group in course.prereqs_one_of:
            options = [p for p in group if p in catalog]
            if options and not any(p in satisfied for p in group):
                # Reuse an alternative that's already planned; otherwise the first listed one not flagged for review.
                pick = min(options, key=lambda p: (p not in reasons, bool(catalog[p].needs_review)))
                if pick not in out:
                    out.append(pick)
        return out

    def chain_depth(code: str) -> int:
        return 1 + max((chain_depth(p) for p in open_prereqs(code)), default=0)

    # 1. Requirements still open. Within a major a course counts toward one group only.
    for major in majors:
        used: set[str] = set()
        for group in major.groups:
            listed = [c for c in group.courses if c not in used]
            if group.rule == "all":
                for code in listed:
                    if code not in satisfied:
                        need(code, f"{group.title} ({major.major_label})")
                used.update(listed)
                continue
            if not listed:
                continue  # no course list (see unscheduled_groups), or all used by earlier groups
            order = {c: i for i, c in enumerate(listed)}
            done = [c for c in listed if c in satisfied]
            # Prefer electives already planned for another major, then ones not flagged for review,
            # then the shortest prereq chain, then catalog order.
            options = sorted((c for c in listed if c not in satisfied),
                             key=lambda c: (c not in reasons, bool(catalog[c].needs_review), chain_depth(c), order[c]))
            if group.rule == "n_of":
                credited = done[: group.n]
                picks = options[: max(group.n - len(credited), 0)]
                goal = f"{group.n} course{'s' if group.n > 1 else ''}"
            else:
                credited, have = [], 0.0
                for code in done:
                    if have < group.units:
                        credited.append(code)
                        have += catalog[code].units
                picks = []
                for code in options:
                    if have >= group.units:
                        break
                    picks.append(code)
                    have += catalog[code].units
                if have < group.units:
                    raise PlannerError(f"{group.title} ({major.major_label}) needs {group.units:g} units; "
                                       "its listed courses can't reach that")
                goal = f"{group.units:g} units"
            for i, code in enumerate(picks, 1):
                need(code, f"{group.title}: pick {i} of {len(picks)} still needed toward {goal} "
                           f"({major.major_label}); any listed elective works")
            used.update(credited + picks)

    # 2. Pull in unfinished prerequisites, transitively; one-of choices are settled here.
    stack = list(reasons)
    while stack:
        code = stack.pop()
        fixed[code] = open_prereqs(code)
        for p in fixed[code]:
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
            raise PlannerError(f"Couldn't schedule {', '.join(sorted(remaining))}; "
                               "check prerequisites and terms offered")
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
                    prereqs=prereq_labels(catalog[code]),
                )
                for code in picked
            ],
        ))
        remaining.difference_update(picked)
        done.update(picked)  # only usable from the next term on: eligibility is computed before picking
    return semesters
