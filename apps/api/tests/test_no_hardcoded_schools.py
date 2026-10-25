"""Application code knows no school: every name, ASSIST id, campus key and school-specific rule lives
in data (data/campuses/<id>.json and the files it points to). Tests, fixtures and data/ may name
schools; apps/api/app, apps/web/src, apps/agent/src and packages/contracts/src may not.

What counts as naming a school:
- a school's name or short name, anywhere in the file, comments included: the registry's own
  entries, plus well-known ones the app has had reason to special-case (KNOWN_NAMES);
- an ASSIST id of a registry school as a number in code (strings and comments aren't searched, so
  "MATH 39" is fine; `university_id === 39` isn't);
- a registry feed key as a quoted string ("sjsu").

University *systems* (University of California, California State University, its Polytechnic
campuses) are naming conventions every campus shares, not schools, so the system rules may use them.
"""

import io
import json
import re
import tokenize
from pathlib import Path

import pytest

from app.services import campuses, planner
from app.services.radar import programs, sources
from app.services.university import sources as guide_sources

ROOT = Path(__file__).resolve().parents[3]
APP_DIRS = ["apps/api/app", "apps/web/src", "apps/agent/src", "packages/contracts/src"]
SUFFIXES = {".py", ".ts", ".tsx", ".js", ".css", ".html", ".json"}

KNOWN_NAMES = [
    "De Anza", "Foothill", "Mission College", "San Jose State", "San José State", "SJSU", "Spartan",
    "Berkeley", "UCLA", "UCSD", "UCSB", "UCSC", "Stanford", "UC Davis", "UC Irvine", "UC Merced",
    "UC Riverside", "UC Santa Barbara", "UC Santa Cruz", "UC San Diego", "Cal State East Bay", "CSU East Bay",
]

# (file, name or id) → why it's allowed. None are needed today.
ALLOWLIST: dict[tuple[str, str], str] = {}


def app_files() -> list[Path]:
    out = []
    for d in APP_DIRS:
        out += [p for p in (ROOT / d).rglob("*") if p.is_file() and p.suffix in SUFFIXES
                and "node_modules" not in p.parts and "__pycache__" not in p.parts]
    assert len(out) > 100, "the scan found too few files; did a directory move?"
    return sorted(out)


def banned_names() -> list[str]:
    names = set(KNOWN_NAMES)
    for c in campuses.all_campuses():
        names |= {c.name, c.short_name}
    return sorted(names, key=len, reverse=True)


def registry_ids() -> set[int]:
    return set(campuses.load().campuses)


def name_pattern() -> re.Pattern:
    alternatives = "|".join(re.escape(n).replace(r"\ ", r"\s+") for n in banned_names())
    return re.compile(rf"(?<![\w-])(?:{alternatives})(?![\w-])", re.IGNORECASE)


def _python_numbers(text: str) -> list[tuple[int, str]]:
    out = []
    for tok in tokenize.generate_tokens(io.StringIO(text).readline):
        if tok.type == tokenize.NUMBER:
            out.append((tok.start[0], tok.string))
    return out


def _ts_code(text: str) -> str:
    """The text with comments and string/template text blanked (newlines kept), so numbers left are
    code. Template ${...} expressions stay code. Regex literals are blanked too."""
    out, i, n = [], 0, len(text)
    stack: list[str] = []  # "`": in a template's text; "{": in one of its ${...} (or a brace within)
    prev = ""  # last significant code character, to tell a regex literal from division

    def blank(s: str) -> str:
        return "".join(ch if ch == "\n" else " " for ch in s)

    while i < n:
        c = text[i]
        if stack and stack[-1] == "`":
            j = i
            while j < n and text[j] != "`" and not text.startswith("${", j):
                j += 2 if text[j] == "\\" else 1
            out.append(blank(text[i:j]))
            if j < n and text[j] == "`":
                stack.pop()
                out.append(" ")
                i = j + 1
            else:
                stack.append("{")
                out.append("  ")
                i = j + 2
            prev = "x"
            continue
        if text.startswith("//", i):
            j = text.find("\n", i)
            j = n if j < 0 else j
            out.append(blank(text[i:j]))
            i = j
            continue
        if text.startswith("/*", i):
            j = text.find("*/", i + 2)
            j = n if j < 0 else j + 2
            out.append(blank(text[i:j]))
            i = j
            continue
        if c in "'\"":
            j = i + 1
            while j < n and text[j] != c and text[j] != "\n":
                j += 2 if text[j] == "\\" else 1
            out.append(blank(text[i:j + 1]))
            i = j + 1
            prev = "x"
            continue
        if c == "`":
            stack.append("`")
            out.append(" ")
            i += 1
            continue
        if c == "/" and (prev == "" or prev in "(,=:[!&|?{};+-*%<>~^"):
            j, in_class = i + 1, False
            while j < n and text[j] != "\n" and (in_class or text[j] != "/"):
                if text[j] == "\\":
                    j += 1
                elif text[j] == "[":
                    in_class = True
                elif text[j] == "]":
                    in_class = False
                j += 1
            out.append(blank(text[i:j + 1]))
            i = j + 1
            prev = "x"
            continue
        if stack and c in "{}":  # braces inside a template's ${...}; the last "}" returns to its text
            if c == "{":
                stack.append("{")
            else:
                stack.pop()
            out.append(c)
            i += 1
            prev = c
            continue
        out.append(c)
        if not c.isspace():
            prev = c
        i += 1
    return "".join(out)


def _ts_numbers(text: str) -> list[tuple[int, str]]:
    code = _ts_code(text)
    out = []
    for m in re.finditer(r"(?<![\w.$])\d+(?![\w.])", code):
        out.append((code.count("\n", 0, m.start()) + 1, m.group()))
    return out


def violations() -> list[str]:
    names, ids = name_pattern(), registry_ids()
    feeds = campuses.feeds()
    feed_literal = re.compile(r"""(['"`])(?:%s)\1""" % "|".join(map(re.escape, feeds))) if feeds else None
    found = []
    for path in app_files():
        rel = str(path.relative_to(ROOT))
        text = path.read_text(errors="replace")
        for m in names.finditer(text):
            if (rel, m.group().casefold()) not in ALLOWLIST:
                found.append(f"{rel}:{text.count(chr(10), 0, m.start()) + 1}: school name {m.group()!r}")
        if feed_literal:
            for m in feed_literal.finditer(text):
                found.append(f"{rel}:{text.count(chr(10), 0, m.start()) + 1}: campus key {m.group()}")
        numbers = (_python_numbers(text) if path.suffix == ".py"
                   else _ts_numbers(text) if path.suffix in (".ts", ".tsx", ".js") else [])
        for line, number in numbers:
            if number.isdigit() and int(number) in ids and (rel, number) not in ALLOWLIST:
                found.append(f"{rel}:{line}: ASSIST id {number}")
    return found


def test_application_code_names_no_school():
    found = violations()
    assert not found, ("School-specific values in application code; move them to the campus registry "
                       "(data/campuses/):\n" + "\n".join(found))


# ---- the scanner itself ----


@pytest.mark.parametrize("src, numbers", [
    ("const a = 39;", ["39"]),
    ('const a = "MATH 39"; // 39', []),
    ("const a = `x ${39} y 79`;", ["39"]),
    ("const r = /\\d{39}/; f(79)", ["79"]),
    ("const a = b / 39;", ["39"]),
    ("x.id === 113 ? 'a' : 117", ["113", "117"]),
    ("/* 51 */ 1.39 + 39px", []),
])
def test_ts_number_scan(src, numbers):
    assert [n for _, n in _ts_numbers(src)] == numbers


def test_python_number_scan():
    src = 'X = 39  # 79\nY = "MATH 113"\nZ = {51: "a"}\n'
    assert [n for _, n in _python_numbers(src)] == ["39", "51"]


def test_names_are_matched_across_spacing_and_case():
    pattern = name_pattern()
    assert pattern.search("a de  anza student") and pattern.search("sjsu") and pattern.search("SAN JOSÉ STATE")
    assert not pattern.search("America/Los_Angeles") and not pattern.search("berkeleyish-word")


# ---- the registry is complete and the data it points to exists ----


def test_registry_entries_point_at_real_files():
    for c in campuses.all_campuses():
        for rel in c.requirements:
            assert c.path(rel).is_file(), (c.assist_id, rel)
        if c.opportunities:
            assert c.path(c.opportunities.sources).is_file(), c.assist_id
            if c.opportunities.programs:
                assert c.path(c.opportunities.programs).is_file(), c.assist_id
        if c.university_guide:
            assert c.path(c.university_guide.sources).is_file(), c.assist_id


def test_every_requirements_file_is_listed_by_its_campus():
    # The web bundles data/campuses/<id>/requirements/*.json by folder; the API reads the registry list.
    on_disk = {p.relative_to(campuses.CAMPUSES_DIR).as_posix()
               for p in campuses.CAMPUSES_DIR.glob("*/requirements/*.json")}
    listed = {rel for c in campuses.all_campuses() for rel in c.requirements}
    assert on_disk == listed
    for rel in listed:
        assert rel.split("/")[0] == str(next(c.assist_id for c in campuses.all_campuses() if rel in c.requirements))


def test_everything_school_specific_loads_through_the_registry():
    assert {m.university_id for m in planner.load_majors()} == {
        c.assist_id for c in campuses.all_campuses() if c.requirements}
    assert set(sources.load().campuses) == set(campuses.feeds())
    for feed in campuses.feeds():
        assert programs.load(feed) or campuses.by_feed(feed).opportunities.programs is None
    assert {u.id for u in guide_sources.load().universities} == {
        c.assist_id for c in campuses.all_campuses() if c.university_guide}


def test_old_school_data_paths_are_gone():
    for old in ("data/requirements", "data/programs", "data/sources.json", "data/university/sources.json",
                "data/university/guides", "apps/web/src/data"):
        path = ROOT / old
        assert not path.is_file() and not (path.is_dir() and any(path.rglob("*.json"))), old


def test_milestones_name_universities_by_id():
    data = json.loads((ROOT / "data" / "milestones.json").read_text())
    for m in data["milestones"]:
        assert all(isinstance(u, int) for u in m.get("universities", [])), m["id"]
