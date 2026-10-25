"""Cal-GETC and IGETC: their areas, which one a student follows, and the sources for both.

Every rule here comes from the ICAS standards documents (cited by PDF page, as the catalog
files are). Which courses are approved for an area at a college comes from ASSIST (lists.py).
"""

import re
from dataclasses import dataclass, field
from typing import Literal

from app.models import Citation, Course

Pattern = Literal["calgetc", "igetc"]

CALGETC_PDF = "https://icas-ca.org/wp-content/uploads/2026/07/Cal-GETC_Standards_1v4_Final_r.pdf"
IGETC_PDF = "https://icas-ca.org/wp-content/uploads/2023/10/IGETC_Standards_2023_v2_4-rev1.pdf"
IGETC_23_PDF = "https://icas-ca.org/wp-content/uploads/2022/06/IGETC_STANDARDS-2.3_02June2022-Final.pdf"


def calgetc_cite(page: int, what: str) -> Citation:
    return Citation(source="web", label=f"Cal-GETC Standards 1.4 · {what}", url=f"{CALGETC_PDF}#page={page}",
                    ref=f"p. {page}")


def igetc_cite(page: int, what: str, v23: bool = False) -> Citation:
    url, version = (IGETC_23_PDF, "2.3") if v23 else (IGETC_PDF, "2.4")
    return Citation(source="web", label=f"IGETC Standards {version} · {what}", url=f"{url}#page={page}",
                    ref=f"p. {page}")


# ---- terms ----

_SEASON = {"winter": 0, "spring": 1, "summer": 2, "fall": 3, "autumn": 3}
_CODE_SEASON = {"W": 0, "S": 1, "U": 2, "SU": 2, "F": 3}


def term_ord(term: str) -> int | None:
    """"Fall 2025" → a sortable number (winter < spring < summer < fall within a year)."""
    m = re.search(r"(winter|spring|summer|fall|autumn)\D*(\d{4})", term or "", re.I)
    return int(m.group(2)) * 4 + _SEASON[m.group(1).lower()] if m else None


def code_ord(code: str) -> int | None:
    """ASSIST's "F2025" → the same scale as term_ord; "" (open-ended) → None."""
    m = re.fullmatch(r"\s*([A-Z]{1,2})(\d{4})\s*", (code or "").upper())
    if not m or m.group(1) not in _CODE_SEASON:
        return None
    return int(m.group(2)) * 4 + _CODE_SEASON[m.group(1)]


def course_ord(course: Course) -> int | None:
    """The term a course was taken; the fall that starts its academic year when only that is known."""
    found = term_ord(course.term)
    if found is None and course.academic_year_id:
        return (course.academic_year_id + 1949) * 4 + 3
    return found


def term_label(ord_: int) -> str:
    year, season = divmod(ord_, 4)
    return f"{('Winter', 'Spring', 'Summer', 'Fall')[season]} {year}"


FALL_2023 = 2023 * 4 + 3
FALL_2025 = 2025 * 4 + 3  # Cal-GETC's first term


# ---- areas ----


@dataclass(frozen=True)
class Area:
    code: str
    title: str
    list_codes: frozenset[str]  # ASSIST area codes that count here
    courses: int = 1
    units: tuple[float, float] = (3, 4)  # (semester, quarter) for the whole area row
    disciplines: int = 1  # courses must come from at least this many subjects
    consumes: bool = True  # False: a course here can also count in another area (labs, languages)
    overflow: bool = False  # filled only with courses left after every other area
    only_for: Literal["UC", "CSU"] | None = None  # required for transfer to this system only
    note: str | None = None
    citation: Citation = field(default_factory=lambda: calgetc_cite(6, "Areas"))


def _codes(*codes: str) -> frozenset[str]:
    return frozenset(codes)


_CALGETC_AREAS = calgetc_cite(6, "Areas of Distribution")
_CALGETC_LAB = calgetc_cite(6, "Area 5C Laboratory")

CALGETC: tuple[Area, ...] = (
    Area("1A", "English Composition", _codes("1A"), citation=_CALGETC_AREAS),
    Area("1B", "Critical Thinking and Composition", _codes("1B"), citation=_CALGETC_AREAS),
    Area("1C", "Oral Communication", _codes("1C"), citation=_CALGETC_AREAS),
    Area("2", "Mathematical Concepts and Quantitative Reasoning", _codes("2"), citation=_CALGETC_AREAS),
    Area("3A", "Arts", _codes("3A"), citation=_CALGETC_AREAS),
    Area("3B", "Humanities", _codes("3B"), citation=_CALGETC_AREAS),
    Area("4", "Social and Behavioral Sciences", _codes("4"), courses=2, units=(6, 8), disciplines=2,
         note="Two courses from two different subjects.", citation=calgetc_cite(7, "Area 4")),
    Area("5A", "Physical Science", _codes("5A"), citation=_CALGETC_AREAS),
    Area("5B", "Biological Science", _codes("5B"), citation=_CALGETC_AREAS),
    Area("5C", "Laboratory", _codes("5C"), units=(1, 1), consumes=False,
         note="A lab with your 5A or 5B course, or a separate lab course.", citation=_CALGETC_LAB),
    Area("6", "Ethnic Studies", _codes("6"), citation=_CALGETC_AREAS),
)

_IGETC_4 = _codes("4", "4A", "4B", "4C", "4D", "4E", "4F", "4G", "4H", "4I", "4J")


def igetc_areas(v23: bool) -> tuple[Area, ...]:
    """IGETC 2.4's areas, or 2.3's for students who started before Fall 2023: three Area 4
    courses instead of two, and no Area 7."""
    areas = igetc_cite(6 if v23 else 5, "Areas of Distribution", v23)
    out = [
        Area("1A", "English Composition", _codes("1A"), citation=areas),
        Area("1B", "Critical Thinking and English Composition", _codes("1B"), citation=areas),
        Area("1C", "Oral Communication", _codes("1C"), only_for="CSU", note="Required for CSU only.",
             citation=areas),
        Area("2", "Mathematical Concepts and Quantitative Reasoning", _codes("2A"), citation=areas),
        Area("3A", "Arts", _codes("3A"), citation=areas),
        Area("3B", "Humanities", _codes("3B"), citation=areas),
        Area("3", "Arts or Humanities", _codes("3A", "3B"), overflow=True,
             note="A third Arts or Humanities course.", citation=areas),
        Area("4", "Social and Behavioral Sciences", _IGETC_4, courses=3 if v23 else 2,
             units=(9, 12) if v23 else (6, 8), disciplines=2,
             note=f"{'Three' if v23 else 'Two'} courses from at least two different subjects.", citation=areas),
        Area("5A", "Physical Science", _codes("5A"), citation=areas),
        Area("5B", "Biological Science", _codes("5B"), citation=areas),
        Area("5C", "Laboratory", _codes("5C"), units=(1, 1), consumes=False,
             note="A lab with your 5A or 5B course, or a separate lab course.", citation=areas),
        Area("6", "Language Other Than English", _codes("6A"), units=(0, 0), consumes=False, only_for="UC",
             note="Required for UC only. Two years of high school study in one language also meets it.",
             citation=areas),
    ]
    if not v23:
        out.append(Area("7", "Ethnic Studies", _codes("7"), citation=areas))
    return tuple(out)


# Cal-GETC 1.4 §10.2: IGETC courses taken before Fall 2025 count in the same Cal-GETC area, and
# IGETC students may use Cal-GETC courses in the same area.
IGETC_TO_CALGETC = {"1A": "1A", "1B": "1B", "1C": "1C", "2A": "2", "3A": "3A", "3B": "3B",
                    **{c: "4" for c in _IGETC_4}, "5A": "5A", "5B": "5B", "5C": "5C", "7": "6"}
CALGETC_TO_IGETC = {"1A": "1A", "1B": "1B", "1C": "1C", "2": "2A", "3A": "3A", "3B": "3B", "4": "4",
                    "5A": "5A", "5B": "5B", "5C": "5C", "6": "7"}
CROSSOVER_CITATION = calgetc_cite(32, "§10.2 Exceptions to the Certification Process")

LIST_RULE_CITATION = {
    "calgetc": calgetc_cite(9, "§4 Course Application Rights"),
    "igetc": igetc_cite(8, "§5.1.1 Course Application Rights"),
}
GRADE_CITATION = {
    "calgetc": calgetc_cite(20, "§8 Grades"),
    "igetc": igetc_cite(15, "§9 Grades"),
}
MIN_GRADE = "C"  # both patterns: "C" (2.0) or better, "C-" not accepted; Pass counts if it means C or better


# ---- which pattern ----


@dataclass(frozen=True)
class PatternChoice:
    pattern: Pattern
    default: Pattern
    started: int | None  # first community-college term, as term_ord
    rule: str
    citation: Citation
    igetc_v23: bool  # IGETC 2.3's areas (started before Fall 2023)


def started_ord(courses: list[Course]) -> int | None:
    found = [o for c in courses if (o := course_ord(c)) is not None]
    return min(found) if found else None


def choose(courses: list[Course], override: Pattern | None = None) -> PatternChoice:
    """Cal-GETC for anyone who starts community college in Fall 2025 or later (and anyone with no
    courses yet); IGETC for earlier starters, who keep it through catalog rights."""
    started = started_ord(courses)
    default: Pattern = "calgetc" if started is None or started >= FALL_2025 else "igetc"
    pattern = override or default
    v23 = started is not None and started < FALL_2023
    since = f"you started in {term_label(started)}" if started is not None else "you haven't started yet"
    if default == "calgetc":
        rule = (f"Cal-GETC applies because {since}: it is the general education pattern for students "
                "who start community college in Fall 2025 or later.")
        citation = calgetc_cite(5, "§1 Cal-GETC begins Fall 2025")
    else:
        rule = (f"IGETC applies because {since}, before Cal-GETC began in Fall 2025. Students with "
                "catalog rights from before Fall 2025 can keep IGETC, which usually means staying "
                "continuously enrolled. You can switch to Cal-GETC.")
        citation = calgetc_cite(5, "§1 Catalog rights before Fall 2025")
    if pattern != default:
        rule += (" You chose Cal-GETC instead." if pattern == "calgetc" else
                 " You chose IGETC instead; it is meant for students who started before Fall 2025, so "
                 "check with a counselor that you can use it.")
    return PatternChoice(pattern, default, started, rule, citation, v23)


def areas_for(choice: PatternChoice) -> tuple[Area, ...]:
    return CALGETC if choice.pattern == "calgetc" else igetc_areas(choice.igetc_v23)


def university_system(name: str | None) -> Literal["UC", "CSU"] | None:
    """From ASSIST's name for the university; None when it can't be told."""
    n = (name or "").casefold()
    if n.startswith("university of california"):
        return "UC"
    if "state university" in n or "california polytechnic" in n or "cal poly" in n:
        return "CSU"
    return None


PATTERN_NAME = {"calgetc": "Cal-GETC", "igetc": "IGETC"}
LIST_TYPE = {"calgetc": "CALGETC", "igetc": "IGETC"}  # ASSIST's listType parameter
