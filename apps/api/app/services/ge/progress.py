"""Confirmed transcript × a college's GE lists → progress per Cal-GETC or IGETC area.

Deterministic, like the major evaluator. The rules, from the standards cited in rules.py:
- A course counts in an area only if it was on the college's list for that area in the term it
  was taken (each course is checked against the list for its own academic year).
- A course listed in several areas counts in one of them; labs (5C) and IGETC languages (6) are
  the exceptions and count alongside another area.
- A "C" or better counts; "C-" doesn't. Pass counts (flagged: only if the college treats it as a C).
- Cal-GETC students may use IGETC courses taken before Fall 2025 in the same area, and IGETC
  students may use Cal-GETC courses (flagged, since the college decides these exceptions).

Courses are assigned to areas with a maximum matching, completed courses first, so a course
that fits two areas lands where it fills the most. In-progress courses (`IP`) make an area
"in_progress" when they'd complete it.
"""

import logging
import re
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Literal

from app.config import ASSIST_YEAR_ID
from app.models import Citation, Course, GeArea, GeCourse, GeOption, GeResponse, GeSummary
from app.services.assist import AssistNotFound, get_service
from app.services.assist.evaluator import academic_year_id_of, grade_verdict
from app.services.assist.service import MAX_YEAR_ID, MIN_YEAR_ID

from . import rules
from .lists import GeList, GeListStore, norm_code
from .rules import Area, Pattern, PatternChoice

log = logging.getLogger(__name__)

# Bound the ASSIST calls a long transcript can trigger (most recent years win).
MAX_YEARS = 8
CALGETC_FIRST_YEAR = 76  # 2025–26

Standing = Literal["done", "in_progress", "below_c", "no"]


@dataclass
class Attempt:
    course: Course
    ord: int | None
    year_id: int | None
    standing: Standing
    pass_grade: bool
    # area code → (list it came from, crossover flag or "")
    rows: dict[str, tuple[GeList, str]] = field(default_factory=dict)

    @property
    def counts(self) -> bool:
        return self.standing in ("done", "in_progress")

    @property
    def prefix(self) -> str:
        return norm_code(self.course.prefix)


def _standing(course: Course) -> tuple[Standing, bool]:
    if course.grade.strip().upper() == "IP":
        return "in_progress", False
    verdict = grade_verdict(course.grade, rules.MIN_GRADE, False)
    if verdict in ("ok", "pass_no_pass"):
        return "done", verdict == "pass_no_pass"
    return ("below_c" if verdict == "below_min" else "no"), False


_RANK = {"done": 3, "in_progress": 2, "below_c": 1, "no": 0}


def best_attempts(courses: list[Course]) -> list[Attempt]:
    """One attempt per course code: the best standing, then the latest term (repeats)."""
    best: dict[str, Attempt] = {}
    for c in courses:
        standing, pass_grade = _standing(c)
        a = Attempt(c, rules.course_ord(c), academic_year_id_of(c), standing, pass_grade)
        key = norm_code(c.prefix, c.number)
        prev = best.get(key)
        if prev is None or (_RANK[a.standing], a.ord or 0) > (_RANK[prev.standing], prev.ord or 0):
            best[key] = a
    return sorted(best.values(), key=lambda a: (a.ord is None, a.ord or 0, a.course.prefix, a.course.number))


# ---- which lists ----


def _sources(pattern: Pattern, year_id: int) -> list[tuple[str, dict[str, str] | None, str]]:
    """(ASSIST list type, area-code mapping into the pattern's codes or None, flag) to check a
    course from `year_id` against, in order."""
    if pattern == "calgetc":
        if year_id >= CALGETC_FIRST_YEAR:
            return [("CALGETC", None, "")]
        return [("IGETC", rules.IGETC_TO_CALGETC, "igetc_course")]
    out = [("IGETC", None, "")]
    if year_id >= CALGETC_FIRST_YEAR:
        out.append(("CALGETC", rules.CALGETC_TO_IGETC, "calgetc_course"))
    return out


def _course_years(attempts: list[Attempt]) -> list[int]:
    years = sorted({a.year_id for a in attempts if a.year_id and MIN_YEAR_ID <= a.year_id <= MAX_YEAR_ID})
    return years[-MAX_YEARS:]


def _load(store: GeListStore, sending: int, wanted: set[tuple[str, int]]) -> dict[tuple[str, int], GeList]:
    keys = sorted(wanted)
    with ThreadPoolExecutor(max_workers=4) as pool:
        found = list(pool.map(lambda k: store.get(k[0], sending, k[1]), keys))
    return dict(zip(keys, found))


def _place(attempts: list[Attempt], areas: tuple[Area, ...], pattern: Pattern,
           lists: dict[tuple[str, int], GeList], today: GeList | None = None) -> None:
    """Fill each attempt's `rows`: the areas its year's list approved it for in the term it was
    taken. With `today`, check against that list instead, counting only approvals still open."""
    for a in attempts:
        if today is not None:
            sources = [(None, "", today)]
        else:
            sources = [(m, f, lists.get((lt, a.year_id))) for lt, m, f in _sources(pattern, a.year_id)]
        for mapping, flag, found in sources:
            listed = found.courses.get(norm_code(a.course.prefix, a.course.number)) if found else None
            if listed is None:
                continue
            for la in listed.areas:
                if not la.covers(None if today is not None else a.ord):
                    continue
                code = mapping.get(la.code) if mapping is not None else la.code
                for area in areas:
                    if code in area.list_codes and area.code not in a.rows:
                        a.rows[area.code] = (found, flag)


# ---- assigning courses to areas ----


def _match(order: list[int], slots_for: dict[int, list[tuple[str, int]]]) -> dict[tuple[str, int], int]:
    """Kuhn's maximum bipartite matching; earlier courses in `order` keep their slot."""
    owner: dict[tuple[str, int], int] = {}

    def augment(i: int, seen: set[tuple[str, int]]) -> bool:
        for s in slots_for.get(i, []):
            if s in seen:
                continue
            seen.add(s)
            if s not in owner or augment(owner[s], seen):
                owner[s] = i
                return True
        return False

    for i in order:
        augment(i, set())
    return owner


def _order(attempts: list[Attempt], idx: list[int]) -> list[int]:
    return sorted(idx, key=lambda i: (attempts[i].standing != "done", attempts[i].ord or 0,
                                      _code_key(f"{attempts[i].course.prefix} {attempts[i].course.number}")))


def assign(attempts: list[Attempt], areas: tuple[Area, ...]) -> dict[str, list[int]]:
    """Area code → indexes of the attempts that count there."""
    counting = [i for i, a in enumerate(attempts) if a.counts]
    out: dict[str, list[int]] = {area.code: [] for area in areas}

    def slots(group: list[Area]) -> dict[int, list[tuple[str, int]]]:
        return {i: [(area.code, n) for area in group if area.code in attempts[i].rows for n in range(area.courses)]
                for i in counting}

    regular = [area for area in areas if area.consumes and not area.overflow]
    owner = _match(_order(attempts, counting), slots(regular))
    for (code, _), i in owner.items():
        out[code].append(i)
    used = set(owner.values())
    for area in regular:
        if area.disciplines > 1:
            _mix_disciplines(attempts, area, out, used, counting)

    rest = [i for i in counting if i not in used]
    for (code, _), i in _match(_order(attempts, rest), slots([a for a in areas if a.overflow])).items():
        out[code].append(i)

    for area in areas:
        if not area.consumes:  # counts alongside another area: every eligible course, best first
            out[area.code] = _order(attempts, [i for i in counting if area.code in attempts[i].rows])[:area.courses]
    for code in out:
        out[code] = _order(attempts, out[code])
    return out


def _mix_disciplines(attempts: list[Attempt], area: Area, out: dict[str, list[int]], used: set[int],
                     counting: list[int]) -> None:
    """All of an area's courses in one subject: swap in an unused course from another subject."""
    held = out[area.code]
    if not held or len({attempts[i].prefix for i in held}) >= area.disciplines:
        return
    subject = attempts[held[0]].prefix
    swap = next((i for i in _order(attempts, counting)
                 if i not in used and area.code in attempts[i].rows and attempts[i].prefix != subject), None)
    if swap is None:
        return
    if len(held) < area.courses:
        held.append(swap)
    else:
        drop = _order(attempts, held)[-1]
        held.remove(drop)
        used.discard(drop)
        held.append(swap)
    used.add(swap)


# ---- the response ----


def _year_label(code: str) -> str:
    return code.replace("-", "–")


def list_citation(found: GeList, pattern_name: str) -> Citation:
    name = found.institution_name or "Community college"
    return Citation(source="assist", label=f"ASSIST · {name} · {pattern_name} ({_year_label(found.year_code)})",
                    url=found.url())


def _ge_course(a: Attempt, flags: list[str], found: GeList) -> GeCourse:
    c = a.course
    return GeCourse(code=f"{c.prefix} {c.number}".strip(), title=c.title, units=c.units, grade=c.grade,
                    term=c.term, flags=flags, citation=list_citation(found, rules.PATTERN_NAME[_pattern_of(found)]))


def _pattern_of(found: GeList) -> Pattern:
    return "calgetc" if found.list_type == "CALGETC" else "igetc"


def _effective(n: int, subjects: int, area: Area) -> int:
    """How many of n courses count toward the area, given how many subjects they span."""
    return min(n, area.courses if subjects >= area.disciplines else area.courses - 1)


def _code_key(code: str) -> tuple:
    """"ASTR 4" before "ASTR 10"."""
    return tuple(int(p) if p.isdigit() else p for p in re.split(r"(\d+)", code))


def _options(area: Area, options: GeList, taken: set[str]) -> list[GeOption]:
    ord_ = (options.year_id + 1949) * 4 + 3
    found = [c for key, c in options.courses.items()
             if key not in taken and any(la.code in area.list_codes and la.covers(ord_) for la in c.areas)]
    return [GeOption(code=c.code, title=c.title, units=c.units) for c in sorted(found, key=lambda c: _code_key(c.code))]


def _area(area: Area, held: list[int], attempts: list[Attempt], unit_index: int, options: GeList,
          taken: set[str], system: str | None) -> GeArea:
    counted = [attempts[i] for i in held]
    done = [a for a in counted if a.standing == "done"]
    need_units = area.units[unit_index]
    all_n = _effective(len(counted), len({a.prefix for a in counted}), area)
    done_n = _effective(len(done), len({a.prefix for a in done}), area)
    units_all = sum(a.course.units for a in counted)
    units_done = sum(a.course.units for a in done)
    if done_n >= area.courses and units_done >= need_units:
        status = "done"
    elif all_n >= area.courses and units_all >= need_units:
        status = "in_progress"
    else:
        status = "missing"
    still = max(0, area.courses - all_n) or (1 if status == "missing" else 0)

    courses = []
    for a in counted:
        found, crossover = a.rows[area.code]
        flags = [f for f in (crossover, "pass_no_pass" if a.pass_grade else "") if f]
        courses.append(_ge_course(a, flags, found))
    below = [_ge_course(a, ["below_c"], a.rows[area.code][0]) for a in attempts
             if a.standing == "below_c" and area.code in a.rows]
    return GeArea(
        code=area.code, title=area.title, status=status, courses_required=area.courses, still_needed=still,
        units=units_all, units_required=need_units, courses=courses,
        options=_options(area, options, taken) if status != "done" else None,
        not_counted=below or None, note=area.note, citation=area.citation,
        required=area.only_for is None or system in (None, area.only_for),
    )


def progress(courses: list[Course], sending: int, store: GeListStore, override: Pattern | None = None,
             receiving: int | None = None) -> GeResponse:
    """`receiving` decides UC-only and CSU-only IGETC areas; without it every area is required."""
    service = get_service()
    if sending not in {c.id for c in service.colleges()}:
        raise AssistNotFound(f"{sending} is not an ASSIST community college")
    choice: PatternChoice = rules.choose(courses, override)
    pattern, areas = choice.pattern, rules.areas_for(choice)
    list_type = rules.LIST_TYPE[pattern]
    term_system = service.term_system(sending)

    options = store.get(list_type, sending, ASSIST_YEAR_ID)
    if not options.courses:  # not published yet for this year
        options = store.get(list_type, sending, ASSIST_YEAR_ID - 1)
    attempts = best_attempts(courses)
    years = _course_years(attempts)
    wanted = {(lt, y) for y in years for lt, _, _ in _sources(pattern, y)}
    lists = _load(store, sending, wanted)
    lists[(list_type, options.year_id)] = options
    # Courses from years we don't read (unknown, or beyond MAX_YEARS) are checked against today's list.
    _place([a for a in attempts if a.year_id in years], areas, pattern, lists)
    _place([a for a in attempts if a.year_id not in years], areas, pattern, lists, today=options)

    held = assign(attempts, areas)
    taken = {norm_code(a.course.prefix, a.course.number) for a in attempts if a.counts}
    unit_index = 0 if term_system == "semester" else 1
    system = rules.university_system(service.institution_name(receiving)) if receiving else None
    rows = [_area(area, held[area.code], attempts, unit_index, options, taken, system) for area in areas]

    citations = [choice.citation, rules.LIST_RULE_CITATION[pattern], rules.GRADE_CITATION[pattern],
                 list_citation(options, rules.PATTERN_NAME[pattern])]
    citations += [c.citation for r in rows for c in r.courses + (r.not_counted or [])]
    if any(f in ("igetc_course", "calgetc_course") for r in rows for c in r.courses for f in c.flags):
        citations.append(rules.CROSSOVER_CITATION)
    citations += [r.citation for r in rows]
    return GeResponse(
        pattern=pattern, pattern_name=rules.PATTERN_NAME[pattern], default_pattern=choice.default,
        rule=choice.rule, rule_citation=choice.citation,
        started_term=rules.term_label(choice.started) if choice.started is not None else None,
        institution=options.institution_name or service.institution_name(sending),
        term_system=term_system, options_year=options.year_code, areas=rows,
        summary=GeSummary(done=sum(r.required and r.status == "done" for r in rows),
                          in_progress=sum(r.required and r.status == "in_progress" for r in rows),
                          missing=sum(r.required and r.status == "missing" for r in rows)),
        citations=list({(c.label, c.url): c for c in citations}.values()),
    )

