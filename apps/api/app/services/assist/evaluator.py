"""Deterministic And/Or evaluator: confirmed transcript × parsed agreement → MatchResult.

This is the only place that decides whether a course counts (PROJECT.md §6).

Semantics, per PROJECT.md §8.1:
- Receiving side (what the university wants), per RequirementGroup:
  `Following` → every row; `NFromArea` / `NFromFollowing` → N rows (or N
  units); `Conjunction` → sections joined by And/Or; a section's
  `NFollowing` advisement → N of that section's rows. No instruction →
  "choose from" with an unspecified count (reported low-confidence).
- Sending side (what satisfies one receiving course): CourseGroups are
  joined by `courseGroupConjunctions` (Or unless marked And); inside a group
  courses are joined by `courseConjunction` (And).
- `noArticulationReason`, or no articulation record → must be taken at the
  university.
- "Complete entire sequence at same institution prior to transfer" → a
  partly-done sequence earns nothing; reported as partial + `sequence_rule`.
- "Minimum grade required: X or better" → courses below X don't count.

Course renumbering (PROJECT.md §8.1): requirements come from the current
agreement, but each receiving course is also checked against the agreements
for the academic years the student took courses (`prior` agreements, joined
by receiving course code), because a course counts under the articulation in
effect when it was taken. A transcript course no loaded agreement knows by
code may still match a sending course by title + units — low confidence,
flagged `renumbered_match`.

Options (I-02): every unsatisfied requirement lists what to take at the
sending college, from the current agreement — one string per alternative,
"A + B" for courses taken together, "A or B" for interchangeable ones.

In progress (I-09): an `IP` grade never counts, but a requirement that the
student's IP courses alone would complete is reported `in_progress` instead
of missing/partial.

Flags emitted (UI copy for unknown ones falls through as-is):
  min_grade_<X>, below_min_grade, sequence_rule, no_current_articulation,
  pass_no_pass, denied_course, course_year_mismatch, renumbered_match,
  unspecified_rule, sequence_grouping_inferred, n_units
"""

import re
from dataclasses import dataclass, field, replace
from typing import Iterable, Literal, Sequence
from urllib.parse import quote

from app.models import Citation, Course, MatchResult, MatchSummary, Requirement

from .parser import Agreement, Articulation, Cell, CourseGroup, RequirementGroup, Row, Section, SendingCourse

Status = Literal["satisfied", "partial", "missing", "at_university", "in_progress"]
Confidence = Literal["high", "medium", "low"]

_CONFIDENCE_RANK = {"high": 2, "medium": 1, "low": 0}

# ---- grades ----

LETTER_GRADES = ["F", "D-", "D", "D+", "C-", "C", "C+", "B-", "B", "B+", "A-", "A", "A+"]
PASS_GRADES = {"P", "CR", "S", "PASS"}
_MIN_GRADE_RE = re.compile(r"grade\b.*?\b([A-D][+-]?)\s*(?:or better|or higher)", re.I)
_LETTER_REQUIRED_RE = re.compile(r"\bletter\s+grade", re.I)
_SEQUENCE_RE = re.compile(r"entire sequence", re.I)
_HONORS_MIX_RE = re.compile(r"honors.*combined", re.I)
_AT_UNIVERSITY_RE = re.compile(r"must be taken at (the )?university", re.I)

GradeVerdict = Literal["ok", "pass_no_pass", "below_min", "not_completed"]


def min_grade_of(attributes: Iterable[str]) -> str | None:
    """Strictest "X or better" grade among the attribute strings."""
    found = [m.group(1).upper() for a in attributes if (m := _MIN_GRADE_RE.search(a))]
    return max(found, key=LETTER_GRADES.index) if found else None


def _stricter(*grades: str | None) -> str | None:
    found = [g for g in grades if g]
    return max(found, key=LETTER_GRADES.index) if found else None


def grade_verdict(grade: str, min_grade: str | None, letter_required: bool) -> GradeVerdict:
    g = grade.strip().upper()
    if g in LETTER_GRADES:
        if g == "F":
            return "not_completed"
        if min_grade and LETTER_GRADES.index(g) < LETTER_GRADES.index(min_grade):
            return "below_min"
        return "ok"
    if g in PASS_GRADES:
        # A P may or may not meet a letter-grade / minimum-grade rule; say so.
        return "pass_no_pass" if (min_grade or letter_required) else "ok"
    return "not_completed"  # NP, NC, W, I, IP, blank


# ---- terms ----

_SEASON = {"W": 0, "WI": 0, "S": 1, "SP": 1, "SU": 2, "U": 2, "F": 3, "FA": 3}
_SEASON_WORDS = {"winter": 0, "spring": 1, "summer": 2, "fall": 3, "autumn": 3}


def _assist_term_ord(code: str) -> int | None:
    """ "F2024" → ordinal; "" → None."""
    m = re.fullmatch(r"\s*([A-Za-z]{1,2})(\d{4})\s*", code or "")
    if not m or m.group(1).upper() not in _SEASON:
        return None
    return int(m.group(2)) * 4 + _SEASON[m.group(1).upper()]


def academic_year_id_of(course: Course) -> int | None:
    """ASSIST academic year id the course was taken in (id = fall year − 1949)."""
    if course.academic_year_id:
        return course.academic_year_id
    m = re.search(r"(winter|spring|summer|fall|autumn)\D*(\d{4})", course.term or "", re.I)
    if not m:
        return None
    year = int(m.group(2))
    fall_year = year if m.group(1).lower() in ("fall", "autumn") else year - 1
    return fall_year - 1949


def _course_term_ord(course: Course) -> int | None:
    m = re.search(r"(winter|spring|summer|fall|autumn)\D*(\d{4})", course.term or "", re.I)
    if m:
        return int(m.group(2)) * 4 + _SEASON_WORDS[m.group(1).lower()]
    if course.academic_year_id:
        return (course.academic_year_id + 1949) * 4 + 3  # start of that academic year (fall)
    return None


# ---- transcript ----


def _norm(s: str) -> str:
    return re.sub(r"[\s\-.]", "", s or "").upper()


@dataclass(frozen=True)
class Taken:
    course: Course
    key: tuple[str, str]
    term_ord: int | None

    @property
    def code(self) -> str:
        return f"{self.course.prefix} {self.course.number}".strip()


_STOPWORDS = {"of", "to", "the", "and", "in", "for", "a", "an", "with", "on"}
# Sequence markers must agree exactly: "Calculus I" is not "Calculus II".
_ORDINALS = {"i", "ii", "iii", "iv", "v", "vi", "b", "c", "d"} | {str(n) for n in range(10)}
TITLE_SIMILARITY_MIN = 0.75
UNITS_TOLERANCE = 0.5


def _title_tokens(title: str) -> tuple[set[str], set[str]]:
    """(word stems, ordinal markers). Stems are 6-char prefixes so
    "Introductory Statistics" ~ "Introduction to Statistics"."""
    words = [w for w in re.findall(r"[a-z0-9]+", (title or "").lower()) if w not in _STOPWORDS]
    ordinals = {w for w in words if w in _ORDINALS}
    return {w[:6] for w in words if w not in _ORDINALS}, ordinals


def similar_course(taken: Course, sc: SendingCourse) -> bool:
    """Title + units fallback for a renumbered course (e.g. MATH 10 → STAT C1000)."""
    if taken.units <= 0 or sc.units <= 0 or abs(taken.units - sc.units) > UNITS_TOLERANCE:
        return False
    (a, a_ord), (b, b_ord) = _title_tokens(taken.title), _title_tokens(sc.title)
    if not a or not b or a_ord != b_ord:
        return False
    return len(a & b) / len(a | b) >= TITLE_SIMILARITY_MIN


def _index(courses: Iterable[Course]) -> dict[tuple[str, str], list[Taken]]:
    idx: dict[tuple[str, str], list[Taken]] = {}
    for c in courses:
        key = (_norm(c.prefix), _norm(c.number))
        idx.setdefault(key, []).append(Taken(course=c, key=key, term_ord=_course_term_ord(c)))
    return idx


# ---- evaluation results ----


@dataclass
class Eval:
    status: Status
    satisfied_by: list[str] = field(default_factory=list)
    flags: list[str] = field(default_factory=list)
    confidence: Confidence = "high"
    units: float = 0.0  # receiving units, for N-units rules
    source: Agreement | None = None  # prior-year agreement that satisfied it; None = current
    options: list[str] = field(default_factory=list)  # what to take at the sending college


def _add(flags: list[str], *new: str) -> None:
    for f in new:
        if f and f not in flags:
            flags.append(f)


def _min_conf(*cs: Confidence) -> Confidence:
    return min(cs, key=_CONFIDENCE_RANK.__getitem__) if cs else "high"


def _union(lists: Iterable[list[str]]) -> list[str]:
    out: list[str] = []
    for items in lists:
        _add(out, *items)
    return out


def _source(evals: Iterable[Eval]) -> Agreement | None:
    return next((e.source for e in evals if e.source), None)


@dataclass
class Ctx:
    index: dict[tuple[str, str], list[Taken]]
    min_grade: str | None
    letter_required: bool
    # Transcript courses unknown (by code) to every loaded agreement: renumbering candidates.
    fallback: tuple[Taken, ...] = ()


# ---- sending side: one receiving cell ----


@dataclass
class _CourseHit:
    taken: Taken
    verdict: GradeVerdict
    outside_dates: bool
    renumbered: bool = False


def _candidate_keys(sc: SendingCourse, honors_mix: bool) -> list[tuple[str, str]]:
    keys = [(_norm(sc.prefix), _norm(sc.number))]
    keys += [(_norm(p), _norm(n)) for p, n in sc.cross_listed]
    if honors_mix:
        for p, n in list(keys):
            keys.append((p, n[:-1]) if n.endswith("H") else (p, n + "H"))
    return keys


_VERDICT_RANK = {"ok": 3, "pass_no_pass": 2, "below_min": 1, "not_completed": 0}


def _find(sc: SendingCourse, ctx: Ctx, honors_mix: bool, fallback: bool = True) -> _CourseHit | None:
    """Best transcript attempt at this sending course (retakes: best grade wins).
    With no attempt by code, a renumbering candidate with a matching title + units."""
    begin, end = _assist_term_ord(sc.begin), _assist_term_ord(sc.end)
    hits = []
    for key in _candidate_keys(sc, honors_mix):
        for t in ctx.index.get(key, []):
            outside = t.term_ord is not None and (
                (begin is not None and t.term_ord < begin) or (end is not None and t.term_ord > end)
            )
            hits.append(_CourseHit(t, grade_verdict(t.course.grade, ctx.min_grade, ctx.letter_required), outside))
    if not hits and fallback:
        hits = [
            _CourseHit(t, grade_verdict(t.course.grade, ctx.min_grade, ctx.letter_required), False, True)
            for t in ctx.fallback
            if similar_course(t.course, sc)
        ]
    if not hits:
        return None
    return max(hits, key=lambda h: (_VERDICT_RANK[h.verdict], not h.outside_dates))


@dataclass
class _BlockEval:
    complete: bool
    done: list[_CourseHit]
    total: int
    sequence_rule: bool
    below_min: bool

    @property
    def confidence(self) -> Confidence:
        c: Confidence = "high"
        if any(h.outside_dates for h in self.done):
            c = "medium"
        if any(h.verdict == "pass_no_pass" or h.renumbered for h in self.done):
            c = "low"
        return c


def _blocks(art: Articulation) -> list[list[CourseGroup]]:
    """Split course groups into Or-alternatives; adjacent groups joined by And merge."""
    groups = list(art.groups)
    pos = [g.position for g in groups]
    and_pairs: set[int] = set()
    for conj, b, e in art.group_conjunctions:
        if conj.lower() == "and":
            and_pairs.update(i for i in range(len(groups) - 1) if b <= pos[i] and pos[i + 1] <= e)
    blocks: list[list[CourseGroup]] = []
    for i, g in enumerate(groups):
        if i and (i - 1) in and_pairs:
            blocks[-1].append(g)
        else:
            blocks.append([g])
    return blocks


def _eval_block(block: list[CourseGroup], ctx: Ctx) -> _BlockEval:
    done: list[_CourseHit] = []
    total = 0
    complete = True
    sequence_rule = below = False
    for g in block:
        attrs = g.attributes + tuple(a for c in g.courses for a in c.attributes)
        sequence_rule |= any(_SEQUENCE_RE.search(a) for a in attrs)
        honors_mix = any(_HONORS_MIX_RE.search(a) for a in attrs)
        hits = [_find(c, ctx, honors_mix) for c in g.courses]
        below |= any(h and h.verdict == "below_min" for h in hits)
        good = [h for h in hits if h and h.verdict in ("ok", "pass_no_pass")]
        if g.conjunction.lower() == "or":
            total += 1
            if good:
                done.append(good[0])
            else:
                complete = False
        else:
            total += len(g.courses)
            done += good
            complete &= len(good) == len(g.courses)
    return _BlockEval(complete, done, total, sequence_rule, below)


def _hit_flags(hits: list[_CourseHit]) -> list[str]:
    flags: list[str] = []
    if any(h.outside_dates for h in hits):
        _add(flags, "course_year_mismatch")
    if any(h.verdict == "pass_no_pass" for h in hits):
        _add(flags, "pass_no_pass")
    if any(h.renumbered for h in hits):
        _add(flags, "renumbered_match")
    return flags


def _group_text(g: CourseGroup, nested: bool) -> str:
    joiner = " or " if g.conjunction.lower() == "or" else " + "
    text = joiner.join(c.code for c in g.courses)
    return f"({text})" if nested and joiner == " or " and len(g.courses) > 1 else text


_HONORS_RE = re.compile(r"\b(C?\d+[A-Z]*?)H\b")


def _merge_honors(options: list[str]) -> list[str]:
    """Fold honors twins into their regular option: "MATH 1A or MATH 1AH",
    "MATH 1B + MATH 1C (or honors)". Only when the regular option is listed too."""
    groups: dict[str, list[str]] = {}
    for o in options:
        groups.setdefault(_HONORS_RE.sub(r"\1", o), []).append(o)
    out: list[str] = []
    for base, group in groups.items():
        if len(group) == 1 or base not in group:
            out += group
        elif " + " in base:
            out.append(f"{base} (or honors)")
        else:
            out.append(" or ".join([base] + [o for o in group if o != base]))
    return out


def articulation_options(art: Articulation | None) -> list[str]:
    """Sending-side alternatives, e.g. ["CIS 35A", "CIS 22A + CIS 22B"]."""
    if art is None or art.no_articulation_reason:
        return []
    alts: list[str] = []
    for b in _blocks(art):
        if len(b) == 1 and b[0].conjunction.lower() == "or":
            _add(alts, *(c.code for c in b[0].courses))
        else:
            _add(alts, " + ".join(_group_text(g, len(b) > 1) for g in b))
    return _merge_honors(alts)


def _either(options: list[str], nested: bool) -> str:
    """Several alternatives as one string: "A or B", parenthesized when joined to more. One option
    can be an "or" already (honors: "MATH 1A or MATH 1AH"), so it's parenthesized too."""
    text = " or ".join(options)
    return f"({text})" if nested and (len(options) > 1 or " or " in text) else text


def _eval_sending(art: Articulation | None, ctx: Ctx) -> Eval | None:
    """One receiving course against one year's articulation; None = nothing articulates."""
    if art is None or art.no_articulation_reason or not art.groups:
        return None
    flags: list[str] = []
    if any(_find(d, ctx, False, fallback=False) for d in art.denied):
        _add(flags, "denied_course")

    evals = [_eval_block(b, ctx) for b in _blocks(art)]
    complete = [e for e in evals if e.complete]
    if complete:
        best = max(complete, key=lambda e: _CONFIDENCE_RANK[e.confidence])  # first wins ties
        _add(flags, *_hit_flags(best.done))
        return Eval("satisfied", _union([[h.taken.code] for h in best.done]), flags, best.confidence)

    if any(e.below_min for e in evals):
        _add(flags, "below_min_grade")
    started = [e for e in evals if e.done]
    if started:
        best = max(started, key=lambda e: len(e.done) / e.total)
        if best.sequence_rule:
            _add(flags, "sequence_rule")
        if any(h.renumbered for h in best.done):
            _add(flags, "renumbered_match")
        return Eval("partial", _union([[h.taken.code] for h in best.done]), flags, "high")

    return Eval("missing", [], flags, "high")


def _eval_cell(cell: Cell, ctx: Ctx, priors: Sequence[tuple[Agreement, Cell]] = ()) -> Eval:
    """`priors`: the same receiving course in agreements for years the student took courses."""
    units = sum(c.units for c in cell.courses)
    art = cell.articulation
    cell_attrs = cell.attributes + (art.attributes if art else ())
    ctx = replace(
        ctx,
        min_grade=_stricter(ctx.min_grade, min_grade_of(cell_attrs)),
        letter_required=ctx.letter_required or any(_LETTER_REQUIRED_RE.search(a) for a in cell_attrs),
    )
    flags: list[str] = []
    if ctx.min_grade:
        _add(flags, f"min_grade_{ctx.min_grade}")

    at_university = any(_AT_UNIVERSITY_RE.search(a) for a in cell_attrs)
    current = None if at_university else _eval_sending(art, ctx)
    options = [(None, current)] + [(ag, _eval_sending(pc.articulation, ctx)) for ag, pc in priors]
    options = [(src, e) for src, e in options if e is not None]

    satisfied = [(src, e) for src, e in options if e.status == "satisfied"]
    if satisfied:
        # Best confidence wins; ties go to the current agreement (listed first).
        src, best = max(satisfied, key=lambda o: _CONFIDENCE_RANK[o[1].confidence])
    elif current is None:
        _add(flags, "no_current_articulation")
        return Eval("at_university", [], flags, "high", units)
    else:
        partial = [(src, e) for src, e in options if e.status == "partial"]
        src, best = partial[0] if partial else (None, current)
    best.flags = _union([flags, best.flags])
    best.units = units
    best.source = src
    best.options = articulation_options(art)
    return best


# ---- receiving side ----


def _all_of(evals: list[Eval]) -> Eval:
    """Every part required (cells in a row, rows in a section, rows in a sequence)."""
    if len(evals) == 1:
        return evals[0]
    todo = [e.options for e in evals if e.status in ("partial", "missing") and e.options]
    options = todo[0] if len(todo) == 1 else [" + ".join(_either(o, True) for o in todo)] if todo else []
    statuses = {e.status for e in evals}
    if statuses == {"satisfied"}:
        status: Status = "satisfied"
    elif statuses == {"at_university"}:
        status = "at_university"
    elif statuses == {"missing"}:
        status = "missing"
    elif statuses <= {"missing", "at_university"}:
        status = "missing"
    else:
        status = "partial"
    return Eval(
        status,
        _union(e.satisfied_by for e in evals),
        _union(e.flags for e in evals),
        _min_conf(*(e.confidence for e in evals)),
        sum(e.units for e in evals),
        _source(evals),
        options,
    )


def _n_of(options: list[Eval], n: float, by_units: bool = False) -> Eval:
    """At least `n` of the options (or `n` receiving units' worth) satisfied."""
    satisfied = [o for o in options if o.status == "satisfied"]
    used: list[Eval] = []
    got = 0.0
    for o in satisfied:
        if got >= n:
            break
        used.append(o)
        got += o.units if by_units else 1
    min_grade_flags = [f for o in options for f in o.flags if f.startswith("min_grade_")]

    if got >= n:
        return Eval(
            "satisfied",
            _union(o.satisfied_by for o in used),
            _union([min_grade_flags] + [o.flags for o in used]),
            _min_conf(*(o.confidence for o in used)),
            sum(o.units for o in used),
            _source(used),
        )
    if options and all(o.status == "at_university" for o in options):
        return Eval("at_university", [], _union([min_grade_flags, ["no_current_articulation"]]))
    progress = [o for o in options if o.status in ("satisfied", "partial")]
    todo = _union(o.options for o in options if o.status in ("partial", "missing"))
    # Options that can't be taken here are expected noise in an "N of" list.
    flags = _union([min_grade_flags] + [[f for f in o.flags if f != "no_current_articulation"] for o in options])
    return Eval(
        "partial" if progress else "missing",
        _union(o.satisfied_by for o in progress),
        flags,
        "high",
        source=_source(progress),
        options=todo,
    )


def _pairs(rows: tuple[Row, ...]) -> list[tuple[Row, ...]]:
    """ASSIST doesn't encode how a "Sequence" section's rows pair up; it lists each
    sequence's courses adjacently, so pair neighbours (flagged as inferred)."""
    if len(rows) % 2:
        return [(r,) for r in rows]
    return [rows[i : i + 2] for i in range(0, len(rows), 2)]


@dataclass
class _Unit:
    """One contract Requirement: a single row (rule "all") or a collapsed N-of set."""

    id: str
    rule: Literal["all", "n_of"]
    n: int | None
    label: str
    eval: Eval


def _cell_key(cell: Cell) -> tuple[tuple[str, str], ...]:
    return tuple((_norm(c.prefix), _norm(c.number)) for c in cell.courses)


def _cells(agreement: Agreement) -> Iterable[Cell]:
    for g in agreement.groups:
        for s in g.sections:
            for r in s.rows:
                yield from r.cells


def _sending_keys(agreement: Agreement) -> set[tuple[str, str]]:
    keys: set[tuple[str, str]] = set()
    for cell in _cells(agreement):
        if cell.articulation:
            courses = [c for g in cell.articulation.groups for c in g.courses]
            for sc in courses + list(cell.articulation.denied):
                keys.update(_candidate_keys(sc, honors_mix=False))
    return keys


def sending_courses(agreement: Agreement) -> dict[str, SendingCourse]:
    """Every sending course the agreement names, by code: titles and units for planning."""
    out: dict[str, SendingCourse] = {}
    for cell in _cells(agreement):
        if cell.articulation:
            for g in cell.articulation.groups:
                for sc in g.courses:
                    out.setdefault(sc.code, sc)
    return out


def option_receivers(agreement: Agreement) -> dict[str, list[str]]:
    """Each option, as `articulation_options` writes it → the receiving course codes it earns.
    Lets a planner tell which course of a "choose from" list one option covers."""
    out: dict[str, list[str]] = {}
    for cell in _cells(agreement):
        for option in articulation_options(cell.articulation):
            codes = out.setdefault(option, [])
            codes += [f"{c.prefix} {c.number}" for c in cell.courses if f"{c.prefix} {c.number}" not in codes]
    return out


class _Evaluator:
    def __init__(self, agreement: Agreement, courses: list[Course], prior: Sequence[Agreement] = ()):
        self.agreement = agreement
        self.index = _index(courses)
        known = set().union(*(_sending_keys(a) for a in (agreement, *prior)))
        self.fallback = tuple(t for ts in self.index.values() for t in ts if t.key not in known)
        self.priors: dict[tuple[tuple[str, str], ...], list[tuple[Agreement, Cell]]] = {}
        for ag in prior:
            for cell in _cells(ag):
                self.priors.setdefault(_cell_key(cell), []).append((ag, cell))

    def _ctx(self, *attr_lists: tuple[str, ...]) -> Ctx:
        attrs = [a for lst in attr_lists for a in lst]
        return Ctx(
            index=self.index,
            min_grade=min_grade_of(attrs),
            letter_required=any(_LETTER_REQUIRED_RE.search(a) for a in attrs),
            fallback=self.fallback,
        )

    def _row(self, row: Row, ctx: Ctx) -> Eval:
        row_ctx = replace(
            ctx,
            min_grade=_stricter(ctx.min_grade, min_grade_of(row.attributes)),
            letter_required=ctx.letter_required
            or any(_LETTER_REQUIRED_RE.search(a) for a in row.attributes),
        )
        return _all_of([_eval_cell(c, row_ctx, self.priors.get(_cell_key(c), ())) for c in row.cells])

    def _section_options(self, section: Section, ctx: Ctx) -> tuple[list[Eval], list[str], list[str]]:
        """(evals, labels, extra flags) of a section's choosable options."""
        if section.n_unit == "Sequence":
            chunks = _pairs(section.rows)
            flags = ["sequence_grouping_inferred"] if any(len(c) > 1 for c in chunks) else []
        else:
            chunks, flags = [(r,) for r in section.rows], []
        evals = [_all_of([self._row(r, ctx) for r in chunk]) for chunk in chunks]
        labels = [" + ".join(r.label for r in chunk) for chunk in chunks]
        return evals, labels, flags

    def _n_unit(self, uid: str, group: RequirementGroup, evals: list[Eval], labels: list[str],
                n: float, by_units: bool, extra_flags: list[str]) -> _Unit:
        e = _n_of(evals, n, by_units)
        _add(e.flags, *extra_flags)
        if by_units:
            _add(e.flags, "n_units")
            label = f"{n:g} units from: " + "; ".join(labels)
        elif n == 1:
            label = " or ".join(labels)
        else:
            label = f"{n:g} from: " + "; ".join(labels)
        if "sequence_grouping_inferred" in extra_flags and e.status == "satisfied":
            e.confidence = _min_conf(e.confidence, "medium")
        return _Unit(uid, "n_of", int(n), label, e)

    def group_units(self, group: RequirementGroup) -> list[_Unit]:
        ins = group.instruction
        units: list[_Unit] = []
        sections = [s for s in group.sections if s.rows]

        def section_ctx(s: Section) -> Ctx:
            return self._ctx(group.attributes, s.attributes)

        if ins.type in ("NFromArea", "NFromFollowing"):
            evals, labels = [], []
            for s in sections:
                ev, lb, _ = self._section_options(s, section_ctx(s))
                evals += ev
                labels += lb
            if evals:
                by_units = (ins.unit or "").lower() == "unit"
                units.append(self._n_unit(group.id, group, evals, labels, ins.amount or 1, by_units, []))
            return units

        if ins.type == "Conjunction" and (ins.conjunction or "").lower() == "or":
            evals, labels = [], []
            for s in sections:
                sev, slb, _ = self._section_options(s, section_ctx(s))
                evals.append(_n_of(sev, s.n_amount) if s.n_amount else _all_of(sev))
                labels.append(" + ".join(slb) if not s.n_amount else f"{s.n_amount:g} of ({', '.join(slb)})")
            if evals:
                units.append(self._n_unit(group.id, group, evals, labels, 1, False, []))
            return units

        if ins.type in ("Following", "Conjunction"):
            for s in sections:
                ctx = section_ctx(s)
                if s.n_amount:
                    ev, lb, extra = self._section_options(s, ctx)
                    by_units = (s.n_unit or "").lower() == "unit"
                    units.append(self._n_unit(f"{group.id}/{s.position}", group, ev, lb, s.n_amount, by_units, extra))
                else:
                    for r in s.rows:
                        units.append(_Unit(r.cells[0].id, "all", None, r.label, self._row(r, ctx)))
            return units

        # No (or unknown) instruction: the agreement lists options without saying
        # how many are needed — report "choose from" and ask for a human check.
        evals, labels = [], []
        for s in sections:
            ev, lb, _ = self._section_options(s, section_ctx(s))
            evals += ev
            labels += lb
        if evals:
            e = _n_of(evals, 1)
            _add(e.flags, "unspecified_rule")
            e.confidence = "low"
            units.append(_Unit(group.id, "n_of", None, "Choose from: " + "; ".join(labels), e))
        return units


def assist_url(agreement: Agreement) -> str:
    """Public ASSIST page for the agreement (what a counselor would open)."""
    return (
        "https://assist.org/transfer/results"
        f"?year={agreement.year_id}&institution={agreement.sending.id}"
        f"&agreement={agreement.receiving.id}&agreementType=to&view=agreement"
        f"&viewBy=major&viewSendingAgreements=false&viewByKey={quote(agreement.key, safe='')}"
    )


def _citation_label(agreement: Agreement) -> str:
    year = agreement.year_code.replace("-", "–")
    return f"{agreement.sending.name} → {agreement.receiving.name} · {agreement.name} ({year})"


def _ip_as_passed(courses: list[Course]) -> list[Course]:
    """The transcript as it will read once every in-progress course passes."""
    return [c.model_copy(update={"grade": "P" if c.grade.strip().upper() == "IP" else c.grade}) for c in courses]


def evaluate(agreement: Agreement, courses: list[Course],
             prior: Sequence[Agreement] = ()) -> MatchResult:
    """`prior`: the same major's agreements for the academic years courses were taken.
    A requirement met under one of them cites that year's agreement."""
    ev = _Evaluator(agreement, courses, prior)
    has_ip = any(c.grade.strip().upper() == "IP" for c in courses)
    ev_ip = _Evaluator(agreement, _ip_as_passed(courses), prior) if has_ip else None

    requirements: list[Requirement] = []
    for group in agreement.groups:
        units = ev.group_units(group)
        ip_units = ev_ip.group_units(group) if ev_ip else [None] * len(units)
        for unit, ip_unit in zip(units, ip_units, strict=True):
            e = unit.eval
            if ip_unit and e.status in ("partial", "missing") and ip_unit.eval.status == "satisfied":
                # The only gap is an in-progress course: report it as it will count, minus
                # the pass/no-pass doubt that standing in "P" for "IP" adds.
                ip = ip_unit.eval
                flags = [f for f in ip.flags if f != "pass_no_pass" or f in e.flags]
                e = replace(ip, status="in_progress", flags=flags, confidence=e.confidence, options=[])
            requirements.append(
                Requirement(
                    id=unit.id,
                    group_title=group.title,
                    rule=unit.rule,
                    n=unit.n,
                    receiving_course=unit.label,
                    status=e.status,
                    satisfied_by=e.satisfied_by,
                    flags=e.flags,
                    options=e.options if e.status in ("partial", "missing") and e.options else None,
                    citation=Citation(
                        source="assist",
                        label=_citation_label(e.source or agreement),
                        url=assist_url(e.source or agreement),
                        ref=f"{group.title} › {unit.label}",
                    ),
                    confidence=e.confidence,
                )
            )
    return MatchResult(
        major_label=agreement.name,
        agreement_key=agreement.key,
        requirements=requirements,
        summary=MatchSummary(
            satisfied=sum(r.status == "satisfied" for r in requirements),
            partial=sum(r.status == "partial" for r in requirements),
            missing=sum(r.status == "missing" for r in requirements),
            at_university=sum(r.status == "at_university" for r in requirements),
            in_progress=sum(r.status == "in_progress" for r in requirements),
        ),
    )
