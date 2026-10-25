"""Planner: remaining major requirements → a two-phase roadmap (PHASES.md Phase 1, step 6; I-03).

Before transfer: every open ASSIST requirement the community college can cover gets one
option (fewest courses still to take), and those courses go in community-college terms
(quarters or semesters) in sequence order, under the unit cap.

After transfer: reads the curated majors each campus's registry entry lists (data/campuses/<id>.json
→ requirements), drops what the student
has already satisfied or will finish before transfer, then schedules the rest term by term
from the transfer term: a course goes in only once all its prerequisites are done in an
earlier term, it's offered that term, and the term stays under the unit cap. Courses that
unlock the longest chains go first.

Deterministic: Claude doesn't take part in planning.
"""

import json
import logging
import re
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field, replace
from datetime import date
from pathlib import Path
from typing import Literal

from pydantic import BaseModel

from app.models import Course, MatchResult, Profile, ProfileStage, Requirement, Semester, SemesterCourse
from app.services import campuses
from app.services.assist import AssistError, get_service
from app.services.assist.evaluator import LETTER_GRADES, grade_verdict, option_receivers, sending_courses

log = logging.getLogger(__name__)

DEFAULT_UNIT_CAP = 15.0
# University terms after transfer: the regular semester terms; summer/winter aren't planned. Every
# university with curated requirements runs on semesters (its registry entry's term_system).
PLAN_SEASONS = ("Spring", "Fall")
MAX_TERMS = 16
PLACEHOLDER_PREFIX = "PLACEHOLDER · "

Season = Literal["Fall", "Spring"]


class PlannerError(Exception):
    status = 422


class UnknownMajor(PlannerError):
    status = 404


# ---- Curated requirements file format (data/campuses/REQUIREMENTS.md) ----


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
    university_id: int = 0  # ASSIST id of the university whose registry entry lists the file
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


def _read_major(path: Path, university_id: int) -> Major:
    major = Major.model_validate({**json.loads(path.read_text()), "university_id": university_id})
    _check(major, path)
    return major


def load_majors(directory: Path | None = None, university_id: int = 0) -> list[Major]:
    """Every curated major: the files each registry entry lists, or every file in `directory` (one
    university's, for tests). Re-read per request so curated edits show up without a restart."""
    if directory is not None:
        return [_read_major(path, university_id) for path in sorted(directory.glob("*.json"))]
    return [_read_major(c.path(rel), c.assist_id) for c in campuses.all_campuses() for rel in c.requirements]


UNIVERSITY_FALLBACK = "your university"
# How an ASSIST label ends: a last comma-separated piece "B.S.", "B.F.A.", "B.A. (<Campus> Online)",
# or UC style with no comma, "Economics/B.A.".
DEGREE_PIECE = re.compile(r"(?:^|/)B\.[A-Z.]*\s*(\(.*\))?$")


def join_labels(labels: list[str]) -> str:
    """Labels for a sentence. They contain commas themselves, so a longer list uses semicolons."""
    if len(labels) <= 2:
        return " and ".join(labels)
    return "; ".join(labels[:-1]) + "; and " + labels[-1]


def uncurated_message(university_id: int, labels: list[str]) -> str:
    university = campuses.short_name(university_id, UNIVERSITY_FALLBACK)
    return (f"We don't have {university}'s {join_labels(labels)} requirements yet, "
            "so lower-division only (from ASSIST).")


def no_full_plan_message(university: str | None) -> str:
    """For a university with no curated requirements: what the plan leaves out, and who to ask."""
    u = university or UNIVERSITY_FALLBACK
    return (f"We don't have {u}'s full degree requirements yet, so upper-division courses aren't planned. "
            f"Check with {u}'s advisors.")


def full_plan(university_id: int, majors: list[Major]) -> bool:
    """Whether we have curated requirements for the university, i.e. can plan after transfer."""
    return any(m.university_id == university_id for m in majors)


def _split_labels(raw: str, known: set[str]) -> list[str]:
    """`raw` is the comma-separated ?majors= value. Labels contain commas themselves
    ("Data Science, B.S."), so pieces are re-joined until they form a known label or end
    in a degree ("…, B.S."), the way every ASSIST label does."""
    labels, pending = [], ""
    for piece in raw.split(","):
        pending = f"{pending},{piece}" if pending else piece
        if pending.strip().casefold() in known or DEGREE_PIECE.search(piece.strip()):
            labels.append(pending.strip())
            pending = ""
    if pending.strip():
        labels.append(pending.strip())
    return labels


def resolve_majors(raw: str | None, default: list[str], university_id: int,
                   majors: list[Major]) -> tuple[list[Major], list[str]]:
    """Pick majors by label for the profile's university: (curated majors, labels with no curated requirements).

    Raises UnknownMajor only when none of the labels is curated.
    """
    by_label = {m.major_label.casefold(): m for m in majors if m.university_id == university_id}
    labels = default if raw is None else _split_labels(raw, set(by_label))
    labels = list(dict.fromkeys(label for label in labels if label.strip()))
    uncurated = [label for label in labels if label.casefold() not in by_label]
    if len(uncurated) == len(labels):
        available = join_labels(sorted(m.major_label for m in by_label.values()))
        if not labels:
            raise UnknownMajor("Choose a major to plan." + (f" Plans are available for {available}." if available else ""))
        raise UnknownMajor(uncurated_message(university_id, uncurated)
                           + (f" Plans are available for {available}." if available else ""))
    curated = {by_label[label.casefold()].major_label: by_label[label.casefold()]
               for label in labels if label.casefold() in by_label}
    return list(curated.values()), uncurated


def plan_majors(raw: str | None, default: list[str], university_id: int,
                majors: list[Major]) -> tuple[list[Major], list[str], bool]:
    """resolve_majors, plus the full_plan flag. For a university with no curated requirements at all
    every label is uncurated, and the roadmap is community-college terms only (no error)."""
    if full_plan(university_id, majors):
        return *resolve_majors(raw, default, university_id, majors), True
    labels = default if raw is None else _split_labels(raw, set())
    labels = list(dict.fromkeys(label.strip() for label in labels if label.strip()))
    if not labels:
        raise UnknownMajor("Choose a major to plan.")
    return [], labels, False


# ---- What's already done ----

# "MATH 30", "CS 46A", and UC style "COMPSCI 61B", "DATA C8".
COURSE_CODE = re.compile(r"\b([A-Z]{2,8})\s+(C?\d+[A-Z]{0,2})\b")


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
    W, F, NP and grades below the requirement's minimum don't count. Without curated majors
    (a university we have no requirements for) nothing counts this way: a community-college
    course can share a code with a university course it isn't (a college's ECON 1 and a university's ECON 1)."""
    majors = list(majors)
    if not majors:
        return set()
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
    start: tuple[Season, int] | None = None,
) -> list[Semester]:
    """University terms from `start` (default: the next term after `today`)."""
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
    for season, year in _terms(start or next_term(today or date.today())):
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


# ---- Before transfer: community-college courses from ASSIST options (I-03) ----

TermSystem = Literal["quarter", "semester"]
CC_SEASONS: dict[TermSystem, tuple[str, ...]] = {"quarter": ("Fall", "Winter", "Spring"), "semester": ("Fall", "Spring")}
SEASON_ORDER = {"Winter": 0, "Spring": 1, "Summer": 2, "Fall": 3}
DEFAULT_CC_UNIT_CAP = 15.0  # quarter or semester units, whichever the college uses
# When the agreement doesn't give a course's units: a typical lecture course.
FALLBACK_CC_UNITS: dict[TermSystem, float] = {"quarter": 5.0, "semester": 4.0}
MAX_TRANSFER_YEARS = 8  # how far ahead a requested transfer term may be
_TERM = re.compile(r"^(Fall|Winter|Spring|Summer) (\d{4})$")
_CC_NUMBER = re.compile(r"^C?(\d+)([A-Z]*)$")


@dataclass(frozen=True)
class SendingCatalog:
    """What the roadmap needs from one major's current ASSIST agreement."""

    college: str  # sending institution, as the agreement names it
    campus: str  # receiving institution, as the agreement names it
    courses: dict[str, tuple[str, float]]  # sending code → (title, units)
    receivers: dict[str, list[str]]  # option text → receiving codes it earns


@dataclass
class CCPick:
    """One open requirement and the community-college option chosen for it."""

    requirement: Requirement
    majors: list[str]
    option: str  # as ASSIST lists it, e.g. "MATH 1B + MATH 1C (or honors)"
    courses: list[str]  # still to take, in sequence order
    covers: list[str]  # receiving course codes it completes


@dataclass
class Roadmap:
    semesters: list[Semester]  # before transfer, then after
    transfer_term: str
    earliest_transfer_term: str
    start_term: str  # first community-college term
    default_start_term: str
    start_term_choices: list[str]
    not_before_transfer: list[str] = field(default_factory=list)
    picks: list[CCPick] = field(default_factory=list)  # the ones scheduled before transfer
    college: str | None = None
    campus: str | None = None
    term_system: TermSystem = "semester"
    ge_not_before_transfer: list[str] = field(default_factory=list)  # GE slots past a requested transfer term


def term_key(term: str) -> int | None:
    """'Winter 2027' → a sortable index; None if not '<Season> <YYYY>'."""
    m = _TERM.match(term.strip())
    return int(m.group(2)) * 4 + SEASON_ORDER[m.group(1)] if m else None


def _split_top(text: str, sep: str) -> list[str]:
    """Split on `sep` outside parentheses."""
    parts, depth, start, i = [], 0, 0, 0
    while i < len(text):
        ch = text[i]
        depth += (ch == "(") - (ch == ")")
        if depth == 0 and text.startswith(sep, i):
            parts.append(text[start:i])
            i += len(sep)
            start = i
            continue
        i += 1
    parts.append(text[start:])
    return [p.strip() for p in parts if p.strip()]


def option_alternatives(option: str) -> list[list[str]]:
    """Every way to complete one ASSIST option, as course lists in the order listed:
    "MATH 1B + MATH 1C (or honors)" → [["MATH 1B", "MATH 1C"]];
    "(MATH 1A or MATH 1AH) + MATH 1B" → [["MATH 1A", "MATH 1B"], ["MATH 1AH", "MATH 1B"]]."""

    def alts(text: str) -> list[list[str]]:
        out: list[list[str]] = []
        for alt in _split_top(text, " or "):
            seqs: list[list[str]] = [[]]
            for piece in _split_top(alt, " + "):
                sub = alts(piece[1:-1]) if piece.startswith("(") and piece.endswith(")") else [[piece]]
                seqs = [a + b for a in seqs for b in sub]
            out += seqs
        return out

    return alts(option.replace(" (or honors)", ""))


def _min_grade(req: Requirement) -> str | None:
    return next((f.removeprefix("min_grade_") for f in req.flags if f.startswith("min_grade_")), None)


def _receiving_codes(req: Requirement) -> list[str]:
    """'MATH 31 - Calculus II' → ['MATH 31']; 'ENGL 1B - … or ENGL 2 - …' → ['ENGL 1B', 'ENGL 2']."""
    codes = []
    for piece in re.split(r"; | or | \+ |: ", req.receiving_course):
        codes += [f"{p} {n}" for p, n in COURSE_CODE.findall(piece.split(" - ")[0])]
    return list(dict.fromkeys(codes))


def pick_cc_courses(matches: Iterable[MatchResult], catalogs: dict[str, SendingCatalog],
                    courses: Iterable[Course]) -> list[CCPick]:
    """One option per open requirement that has community-college options: the fewest courses
    still to take, ties to the first listed. For a requirement every part of which is needed,
    a tie goes first to the option that finishes a sequence the student started (CIS 22A taken,
    so CIS 22B rather than CIS 35A). A course already picked for another requirement isn't picked
    again (one course earns one requirement). A requirement shared by several majors is picked once."""
    taken = [c for c in courses if c.confirmed]

    def done(req: Requirement) -> set[str]:
        return {f"{c.prefix} {c.number}" for c in taken if _passed(c, _min_grade(req))}

    by_course: dict[str, CCPick] = {}
    open_reqs = [(m.major_label, r) for m in matches for r in m.requirements
                 if r.status in ("missing", "partial") and r.options]
    open_reqs.sort(key=lambda mr: mr[1].rule != "all")  # n_of choices can then reuse planned courses
    planned: set[str] = set()
    for label, req in open_reqs:
        if req.receiving_course in by_course:
            if label not in by_course[req.receiving_course].majors:
                by_course[req.receiving_course].majors.append(label)
            continue
        have = done(req)
        best = None
        for i, option in enumerate(req.options or []):
            for alt in option_alternatives(option):
                todo = [c for c in alt if c not in have]
                if not todo or planned & set(todo):
                    continue  # taken already yet still open, or counted for another requirement
                fresh = req.rule == "all" and not any(c in have for c in alt)
                if best is None or (len(todo), fresh, i) < best[0]:
                    best = ((len(todo), fresh, i), option, todo)
        if best is None:
            continue
        _, option, todo = best
        listed = _receiving_codes(req)
        catalog = catalogs.get(label)
        # In a "choose from" list, only the course(s) this option earns.
        earned = catalog.receivers.get(option, []) if catalog and req.rule == "n_of" else []
        covers = [c for c in earned if c in listed] or listed
        by_course[req.receiving_course] = CCPick(req, [label], option, todo, covers)
        planned.update(todo)
    return list(by_course.values())


def next_cc_term(today: date, system: TermSystem) -> tuple[str, int]:
    """First community-college term a student can still register for."""
    if system == "semester":
        return next_term(today)
    if today.month <= 3:
        return "Spring", today.year
    if today.month <= 8:
        return "Fall", today.year
    return "Winter", today.year + 1


def default_start(today: date, system: TermSystem, courses: Iterable[Course],
                  stage: ProfileStage | None = None) -> tuple[str, int]:
    """Where the college terms start by default: the next term they can register for when they're
    already at a community college or have courses, otherwise the next Fall (a high-school senior
    starts in Fall). Terms they're already taking classes in (in progress, e.g. from a saved
    schedule) win: the start moves past the latest one."""
    courses = list(courses)
    if stage == "community_college" or any(c.confirmed for c in courses):
        busy = max((k for c in courses if c.confirmed and c.grade.strip().upper() == IN_PROGRESS
                    and (k := term_key(c.term)) is not None), default=None)
        terms = _cc_terms(next_cc_term(today, system), system)
        term = next(terms)
        while busy is not None and term_key("{} {}".format(*term)) <= busy:
            term = next(terms)
        return term
    return "Fall", today.year if today.month <= 8 else today.year + 1


def start_choices(today: date, system: TermSystem, n: int = 12) -> list[str]:
    """College terms a student can start in: the next registrable term on."""
    terms = _cc_terms(next_cc_term(today, system), system)
    return ["{} {}".format(*next(terms)) for _ in range(n)]


def parse_start_term(raw: str, today: date, system: TermSystem) -> tuple[str, int]:
    """A requested first college term: one of `start_choices`."""
    term = raw.strip().title()
    choices = start_choices(today, system)
    if term not in choices:
        raise PlannerError(f"Pick a starting term from {choices[0]} to {choices[-1]}.")
    season, year = term.split()
    return season, int(year)


def _cc_terms(start: tuple[str, int], system: TermSystem):
    seasons = CC_SEASONS[system]
    season, year = start
    i = seasons.index(season)
    while True:
        yield seasons[i], year
        i = (i + 1) % len(seasons)
        if seasons[i] == "Winter" or (system == "semester" and seasons[i] == "Spring"):
            year += 1


def _course_number(code: str) -> tuple[int, str]:
    """'MATH 1B' → (1, 'B'); 'ECON C2001' → (2001, ''). Unparseable numbers sort last."""
    m = _CC_NUMBER.match(code.rsplit(" ", 1)[-1])
    return (int(m.group(1)), m.group(2)) if m else (10**6, code)


def _sequence_root(code: str) -> tuple[str, str, str] | None:
    """'MATH 1B' → ('MATH', '1', 'B'): same prefix and number, lettered A, B, C… = one sequence.
    A trailing H (honors) is ignored: 'MATH 1AH' → ('MATH', '1', 'A')."""
    prefix, _, number = code.rpartition(" ")
    m = _CC_NUMBER.match(number)
    if not m or not m.group(2):
        return None
    letters = m.group(2)[:-1] if len(m.group(2)) > 1 and m.group(2).endswith("H") else m.group(2)
    return (prefix, number[: len(number) - len(m.group(2))], letters) if len(letters) == 1 else None


def _acyclic(nodes: Iterable[str], deps: dict[str, set[str]]) -> bool:
    indeg = {n: len(deps.get(n, ())) for n in nodes}
    users: dict[str, list[str]] = {}
    for n, ds in deps.items():
        for d in ds:
            users.setdefault(d, []).append(n)
    ready = [n for n, k in indeg.items() if k == 0]
    seen = 0
    while ready:
        n = ready.pop()
        seen += 1
        for u in users.get(n, []):
            indeg[u] -= 1
            if indeg[u] == 0:
                ready.append(u)
    return seen == len(indeg)


def schedule_cc(picks: list[CCPick], units: dict[str, float], titles: dict[str, str], system: TermSystem,
                start: tuple[str, int], majors: Iterable[Major] = (), unit_cap: float = DEFAULT_CC_UNIT_CAP,
                institution: str | None = None) -> list[Semester]:
    """Community-college terms. We don't have the college's prerequisites, so order comes from:
    the order courses are listed in an option (MATH 1B + MATH 1C), lettered sequences
    (MATH 1A → 1B → 1C, CIS 22A → 22B → 22C), and the university's prerequisites between the
    requirements they cover (MATH 31 needs MATH 30, so MATH 1B waits for MATH 1A). Longest chain
    first, then course number."""
    reasons: dict[str, list[str]] = {}
    for p in picks:
        for code in p.courses:
            why = f"For {p.requirement.receiving_course} ({', '.join(p.majors)}); ASSIST option: {p.option}"
            reasons.setdefault(code, [])
            if why not in reasons[code]:
                reasons[code].append(why)
    codes = list(reasons)
    hard: dict[str, set[str]] = {c: set() for c in codes}
    for p in picks:
        for before, after in zip(p.courses, p.courses[1:]):
            hard[after].add(before)
    roots: dict[tuple[str, str], list[tuple[str, str]]] = {}
    for code in codes:
        if root := _sequence_root(code):
            roots.setdefault(root[:2], []).append((root[2], code))
    for seq in roots.values():
        seq.sort()
        for (_, before), (_, after) in zip(seq, seq[1:]):
            hard[after].add(before)
    deps = hard if _acyclic(codes, hard) else {c: set() for c in codes}
    # University prerequisites between the requirements the picks cover; an edge that would
    # close a cycle is left out.
    catalog = {code: c for m in majors for code, c in m.courses.items()}
    covered_by = {code: p for p in picks for code in p.covers}

    def depends(code: str, on: str) -> bool:
        stack, seen = [code], set()
        while stack:
            c = stack.pop()
            if c == on:
                return True
            if c not in seen:
                seen.add(c)
                stack += deps[c]
        return False

    for p in picks:
        for code in p.covers:
            for pre in catalog[code].all_prereqs() if code in catalog else []:
                q = covered_by.get(pre)
                if q is None or q is p:
                    continue
                for after in p.courses:
                    for before in q.courses:
                        if before != after and not depends(before, after):
                            deps[after].add(before)

    users: dict[str, list[str]] = {c: [] for c in codes}
    for c, ds in deps.items():
        for d in ds:
            users[d].append(c)

    def height(code: str) -> int:
        return 1 + max((height(u) for u in users[code]), default=0)

    remaining, done, terms = set(codes), set(), []
    for season, year in _cc_terms(start, system):
        if not remaining:
            break
        eligible = sorted((c for c in remaining if deps[c] <= done),
                          key=lambda c: (-height(c), _course_number(c), c))
        picked, load = [], 0.0
        for code in eligible:
            if load + units[code] <= unit_cap or not picked:
                picked.append(code)
                load += units[code]
        terms.append(Semester(
            term=f"{season} {year}",
            courses=[SemesterCourse(code=c, title=titles[c], units=units[c], reason="; ".join(reasons[c]), prereqs=[])
                     for c in picked],
            phase="before_transfer", institution=institution, term_system=system,
        ))
        remaining.difference_update(picked)
        done.update(picked)
    return terms


# ---- Before transfer: GE areas (feature: GE) ----


@dataclass(frozen=True)
class GeSlot:
    """One GE course still to take: any course on the area's approved list (services/ge)."""

    area: str  # "Cal-GETC 3A"
    title: str  # "Arts"
    units: float
    options: list[str]  # approved course codes at the college
    reason: str
    # Subjects already counted in the area, when it needs two subjects (Area 4): a planned
    # course in the only subject so far doesn't fill another slot.
    subjects: tuple[str, ...] | None = None


def _code_norm(code: str) -> str:
    return re.sub(r"[\s\-.]", "", code).upper()


def fill_ge(cc: list[Semester], slots: Iterable[GeSlot], start: tuple[str, int], system: TermSystem,
            unit_cap: float = DEFAULT_CC_UNIT_CAP, institution: str | None = None,
            limit: int | None = None) -> tuple[list[Semester], list[GeSlot]]:
    """GE after the major courses: a planned major course on an area's list fills that area
    (one area per course); the other areas go in the room left in each college term, then in
    more terms, all before `limit` (a term_key) when given. Returns the terms and the slots
    that didn't fit."""
    terms = [s.model_copy(deep=True) for s in cc]
    open_slots: list[GeSlot] = []
    subjects: dict[str, set[str]] = {}  # area → subjects counted there, for two-subject areas
    for slot in slots:
        options = {_code_norm(o) for o in slot.options}
        seen = subjects.setdefault(slot.area, set(slot.subjects or ()))

        def fits(c: SemesterCourse) -> bool:
            subject = c.code.rpartition(" ")[0]
            return slot.subjects is None or len(seen) >= 2 or subject not in seen

        course = next((c for s in terms for c in s.courses
                       if c.ge_area is None and _code_norm(c.code) in options and fits(c)), None)
        if course is not None:
            course.ge_area = slot.area
            seen.add(course.code.rpartition(" ")[0])
        elif slot.subjects is not None and len(seen) == 1:  # it has to bring the second subject
            other = [o for o in slot.options if o.rpartition(" ")[0] not in seen]
            open_slots.append(replace(slot, options=other or slot.options))
        else:
            open_slots.append(slot)
    by_term = {s.term: s for s in terms}
    out: list[Semester] = []
    for season, year in _cc_terms(start, system):
        name = f"{season} {year}"
        if limit is not None and term_key(name) >= limit:
            break
        if name not in by_term and not open_slots:  # the college terms are consecutive from `start`
            break
        term = by_term.get(name) or Semester(term=name, courses=[], phase="before_transfer",
                                             institution=institution, term_system=system)
        load = sum(c.units for c in term.courses)
        while open_slots and (load + open_slots[0].units <= unit_cap or not term.courses):
            slot = open_slots.pop(0)
            term.courses.append(SemesterCourse(code=slot.area, title=slot.title, units=slot.units,
                                               reason=slot.reason, prereqs=[], ge_area=slot.area,
                                               ge_options=slot.options))
            load += slot.units
        out.append(term)
    return out, open_slots


def parse_transfer_term(raw: str, today: date) -> tuple[Season, int]:
    """A requested transfer term: a Fall or Spring from the next registrable term on."""
    m = _TERM.match(raw.strip().title())
    if not m or m.group(1) not in PLAN_SEASONS:
        raise PlannerError("Give the transfer term as 'Fall <year>' or 'Spring <year>', e.g. 'Fall 2028'.")
    season, year = m.group(1), int(m.group(2))
    first = next_term(today)
    if term_key(f"{season} {year}") < term_key("{} {}".format(*first)):
        raise PlannerError(f"Pick a transfer term from {first[0]} {first[1]} on.")
    if year > today.year + MAX_TRANSFER_YEARS:
        raise PlannerError(f"Pick a transfer term before {today.year + MAX_TRANSFER_YEARS + 1}.")
    return season, year  # type: ignore[return-value]


def earliest_transfer(cc_terms: list[Semester], start: tuple[str, int]) -> tuple[Season, int]:
    """The first Fall after the community-college terms finish (or from their start, with none)."""
    if cc_terms:
        season, year = cc_terms[-1].term.split()
        return "Fall", int(year) + (1 if season == "Fall" else 0)
    return "Fall", start[1]


def build_roadmap(
    majors: list[Major],
    satisfied: set[str],
    matches: list[MatchResult],
    catalogs: dict[str, SendingCatalog],
    courses: list[Course],
    system: TermSystem,
    today: date | None = None,
    transfer_term: str | None = None,
    start_term: str | None = None,
    cc_unit_cap: float = DEFAULT_CC_UNIT_CAP,
    unit_cap: float = DEFAULT_UNIT_CAP,
    ge_slots: Iterable[GeSlot] = (),
    stage: ProfileStage | None = None,
) -> Roadmap:
    """Community-college terms for what the college can cover, then university terms from the
    transfer term for the rest. With a requested transfer term earlier than the college terms
    allow, a requirement whose courses don't all fit before it moves to after transfer.
    College terms start at `start_term`, or `default_start`."""
    today = today or date.today()
    # A requirement already met by its university course code (taken there) needs nothing here.
    picks = [p for p in pick_cc_courses(matches, catalogs, courses) if not p.covers or not set(p.covers) <= satisfied]
    units: dict[str, float] = {}
    titles: dict[str, str] = {}
    for cat in catalogs.values():
        for code, (title, u) in cat.courses.items():
            titles.setdefault(code, title)
            if u > 0:
                units.setdefault(code, u)
    for p in picks:
        for code in p.courses:
            units.setdefault(code, FALLBACK_CC_UNITS[system])
            titles.setdefault(code, code)
    college = next((c.college for c in catalogs.values()), None)
    campus = next((c.campus for c in catalogs.values()), None)
    default = default_start(today, system, courses, stage)
    start = default if start_term is None else parse_start_term(start_term, today, system)

    def schedule(chosen: list[CCPick]) -> list[Semester]:
        return schedule_cc(chosen, units, titles, system, start, majors, cc_unit_cap, college)

    catalog = {code: c for m in majors for code, c in m.courses.items()}

    def ready(p: CCPick, others: list[CCPick]) -> bool:
        """The university prerequisites of what `p` covers are done, or covered before transfer too."""
        ok = satisfied | {code for q in others for code in q.covers}
        known = [catalog[code] for code in p.covers if code in catalog]
        return all(pre in ok or pre not in catalog for c in known for pre in c.prereqs) and all(
            any(pre in ok or pre not in catalog for pre in group) for c in known for group in c.prereqs_one_of)

    kept = picks
    while unready := [p for p in kept if not ready(p, [q for q in kept if q is not p])]:
        kept = [p for p in kept if p not in unready]
    cc = schedule(kept)
    ge_slots = list(ge_slots)
    if ge_slots:  # GE comes after the major courses and can push the earliest transfer later
        with_ge, _ = fill_ge(cc, ge_slots, start, system, cc_unit_cap, college)
        earliest = earliest_transfer(with_ge, start)
        if transfer_term is None:
            cc = with_ge
    else:
        earliest = earliest_transfer(cc, start)
    transfer = earliest if transfer_term is None else parse_transfer_term(transfer_term, today)
    limit = term_key("{} {}".format(*transfer))
    if cc and term_key(cc[-1].term) >= limit:
        # Keep requirements in pick order while all their courses still finish before transfer.
        fitting, cc = [], []
        for p in kept:
            if not ready(p, fitting):
                continue
            trial = schedule(fitting + [p])
            if term_key(trial[-1].term) < limit:
                fitting, cc = fitting + [p], trial
        kept = fitting
    ge_left: list[GeSlot] = []
    if ge_slots and transfer_term is not None:
        cc, ge_left = fill_ge(cc, ge_slots, start, system, cc_unit_cap, college, limit)
    in_cc = {c.code for s in cc for c in s.courses}
    not_before = list(dict.fromkeys(c for p in picks if p not in kept for c in p.courses if c not in in_cc))
    covered = {code for p in kept for code in p.covers}
    after = build_plan(majors, satisfied | covered, today=today, unit_cap=unit_cap, start=transfer)
    for s in after:
        s.phase, s.institution, s.term_system = "after_transfer", campus, "semester"
    return Roadmap(
        semesters=cc + after,
        transfer_term="{} {}".format(*transfer),
        earliest_transfer_term="{} {}".format(*earliest),
        start_term="{} {}".format(*start),
        default_start_term="{} {}".format(*default),
        start_term_choices=start_choices(today, system),
        not_before_transfer=not_before,
        ge_not_before_transfer=list(dict.fromkeys(slot.area for slot in ge_left)),
        picks=kept,
        college=college,
        campus=campus,
        term_system=system,
    )


def sending_catalog(profile: Profile, label: str) -> SendingCatalog | None:
    """The current agreement's sending courses and option map; None when ASSIST can't give it."""
    service = get_service()
    sending, receiving = profile.sending_institution_id, profile.receiving_institution_id
    try:
        ag = service.agreement(sending, receiving, service.year_for(sending, receiving), label)
    except AssistError as e:
        log.info("roadmap: no agreement for %r: %s", label, e)
        return None
    return SendingCatalog(
        college=ag.sending.name,
        campus=ag.receiving.name,
        courses={code: (sc.title, sc.units) for code, sc in sending_courses(ag).items()},
        receivers=option_receivers(ag),
    )


MAX_UNCURATED_FOR_ROADMAP = 3


def _known_labels(profile: Profile, labels: list[str]) -> list[str]:
    """Uncurated labels worth an ASSIST match: only exact labels from the (cached) majors list for
    this college pair, and only a few, so one request can't fan out into many ASSIST calls."""
    if not labels:
        return []
    service = get_service()
    sending, receiving = profile.sending_institution_id, profile.receiving_institution_id
    try:
        known = {m.label for m in service.majors(sending, receiving, service.year_for(sending, receiving))}
    except AssistError as e:
        log.info("roadmap: ASSIST majors unavailable: %s", e)
        return []
    return [label for label in labels if label in known][:MAX_UNCURATED_FOR_ROADMAP]


def roadmap_for(profile: Profile, courses: list[Course], majors: list[Major], uncurated: list[str],
                planning_match: Callable[[str], MatchResult | None], today: date | None = None,
                transfer_term: str | None = None, start_term: str | None = None,
                ge_slots: Iterable[GeSlot] = ()) -> Roadmap:
    """The roadmap /plan and the counselor both show. `planning_match` gives a major's ASSIST
    match with in-progress courses as passed (None when there's no agreement or ASSIST is down).
    Majors without curated requirements still get their community-college courses."""
    labels = [m.major_label for m in majors] + _known_labels(profile, uncurated)
    matches = {label: m for label in labels if (m := planning_match(label)) is not None}
    catalogs = {label: c for label in matches if (c := sending_catalog(profile, label)) is not None}
    done = satisfied(courses, matches.values(), majors)
    system = get_service().term_system(profile.sending_institution_id)
    return build_roadmap(majors, done, list(matches.values()), catalogs, courses, system,
                         today=today, transfer_term=transfer_term, start_term=start_term, ge_slots=ge_slots,
                         stage=profile.stage)
