"""Phase 1 item 4: year-of-course agreements + title/units renumbering fallback.

Real case in the fixtures: De Anza renumbered ECON 1 → ECON C2002 and
MATH 10 → STAT C1000. The 2023–24 SJSU agreements still list the old numbers;
the 2026–27 ones only list the new.
"""

import json

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.models import Course, MatchResult, Requirement
from app.services.assist import evaluate, parse_agreement
from app.services.assist.evaluator import academic_year_id_of, similar_course
from app.services.assist.parser import SendingCourse
from tests.assist_fake import (
    DS_2023_KEY,
    DS_KEY,
    ECON_BS_2023_KEY,
    ECON_BS_KEY,
    FakeAssist,
    agreement_result,
)


def course(code: str, title: str = "", units: float = 5, grade: str = "A",
           term: str = "Fall 2025", year_id: int | None = None) -> Course:
    prefix, number = code.split()
    return Course(prefix=prefix, number=number, title=title, units=units, grade=grade,
                  term=term, academic_year_id=year_id, confirmed=True)


def agreement(key: str):
    return parse_agreement(agreement_result(key), key)


def req(result: MatchResult, receiving: str) -> Requirement:
    hits = [r for r in result.requirements if r.receiving_course.startswith(receiving)]
    assert len(hits) == 1, [r.receiving_course for r in result.requirements]
    return hits[0]


ECON_1 = course("ECON 1", "Principles of Macroeconomics", 4, term="Winter 2024")
MATH_10 = course("MATH 10", "Introductory Statistics", 5, term="Fall 2023")


@pytest.mark.parametrize(("term", "year_id"), [
    ("Fall 2023", 74), ("Winter 2024", 74), ("Spring 2024", 74), ("Summer 2024", 74),
    ("Fall 2024", 75), ("Spring 2027", 77), ("", None), ("Transfer credit", None),
])
def test_academic_year_from_term(term, year_id):
    assert academic_year_id_of(course("MATH 1A", term=term)) == year_id


def test_explicit_academic_year_id_wins():
    assert academic_year_id_of(course("MATH 1A", term="Fall 2023", year_id=72)) == 72


def test_renumbered_course_falls_back_to_title_and_units():
    hit = req(evaluate(agreement(ECON_BS_KEY), [ECON_1]), "ECON 1A")
    assert (hit.status, hit.confidence, hit.satisfied_by) == ("satisfied", "low", ["ECON 1"])
    assert "renumbered_match" in hit.flags


def test_year_of_course_agreement_beats_the_fallback():
    hit = req(evaluate(agreement(ECON_BS_KEY), [ECON_1], [agreement(ECON_BS_2023_KEY)]), "ECON 1A")
    assert (hit.status, hit.confidence, hit.satisfied_by) == ("satisfied", "high", ["ECON 1"])
    assert "renumbered_match" not in hit.flags
    # The claim cites the agreement that actually grants the credit.
    assert hit.citation.label.endswith("Economics, B.S. (2023–2024)")
    assert "year=74" in hit.citation.url and "viewByKey=74%2F113" in hit.citation.url
    assert hit.id.startswith("121b4b02")  # still the current requirement row


def test_prefix_change_is_caught_by_similarity():
    # MATH 10 "Introductory Statistics" → STAT C1000 "Introduction to Statistics"
    hit = req(evaluate(agreement(ECON_BS_KEY), [MATH_10]), "STAT 95")
    assert (hit.status, hit.confidence) == ("satisfied", "low")
    assert hit.satisfied_by == ["MATH 10"] and "renumbered_match" in hit.flags
    exact = req(evaluate(agreement(ECON_BS_KEY), [MATH_10], [agreement(ECON_BS_2023_KEY)]), "STAT 95")
    assert (exact.confidence, exact.flags) == ("high", ["min_grade_C"])


def test_year_of_course_agreement_clears_date_mismatch():
    old_calc = course("MATH 1A", "Calculus", term="Fall 2023")
    alone = req(evaluate(agreement(DS_KEY), [old_calc]), "MATH 30")
    assert alone.confidence == "medium" and "course_year_mismatch" in alone.flags
    with_year = req(evaluate(agreement(DS_KEY), [old_calc], [agreement(DS_2023_KEY)]), "MATH 30")
    assert with_year.confidence == "high" and "course_year_mismatch" not in with_year.flags


def test_prior_articulation_counts_even_if_current_year_has_none():
    raw = agreement_result(DS_KEY)
    arts = json.loads(raw["articulations"])
    math30 = next(a for a in arts if a["articulation"]["course"]["courseNumber"] == "30")
    math30["articulation"]["sendingArticulation"]["noArticulationReason"] = "No Current Articulation"
    raw["articulations"] = json.dumps(arts)
    current = parse_agreement(raw, DS_KEY)
    old_calc = course("MATH 1A", "Calculus", term="Fall 2023")

    assert req(evaluate(current, [old_calc]), "MATH 30").status == "at_university"
    hit = req(evaluate(current, [old_calc], [agreement(DS_2023_KEY)]), "MATH 30")
    assert (hit.status, hit.confidence) == ("satisfied", "high")


def test_known_course_codes_never_use_the_fallback():
    # MATH 1B is in the agreement as Calculus II; a mistyped title must not make it Calculus I.
    wrong = course("MATH 1B", "Calculus I", 5)
    assert req(evaluate(agreement(DS_KEY), [wrong]), "MATH 30").status == "missing"


def test_fallback_partial_sequence_is_flagged():
    # Unknown-code course resembling CIS 22A only: partial, and the guess is disclosed.
    guess = course("CS 1", "Beginning Programming Methodologies in C++", 4.5)
    hit = req(evaluate(agreement(DS_KEY), [guess]), "CS 46A")
    assert hit.status == "partial" and {"renumbered_match", "sequence_rule"} <= set(hit.flags)


def sc(title: str, units: float = 5) -> SendingCourse:
    return SendingCourse(prefix="X", number="1", title=title, units=units, begin="", end="", attributes=())


@pytest.mark.parametrize(("taken", "taken_units", "sending", "sending_units", "expected"), [
    ("Principles of Macroeconomics", 4, "Principles of Macroeconomics", 4, True),
    ("Introductory Statistics", 5, "Introduction to Statistics", 5, True),
    ("Calculus", 4.5, "Calculus", 5, True),  # within tolerance
    ("Calculus II", 5, "Calculus I", 5, False),  # ordinal mismatch
    ("Calculus", 5, "Calculus I", 5, False),
    ("Principles of Macroeconomics", 3, "Principles of Macroeconomics", 4, False),  # units
    ("Principles of Macroeconomics", 4, "Principles of Microeconomics", 4, False),
    ("Principles of Macroeconomics", 4, "Principles of Macroeconomics - HONORS", 4, False),
    ("", 4, "Principles of Macroeconomics", 4, False),
    ("Principles of Macroeconomics", 0, "Principles of Macroeconomics", 4, False),
])
def test_similarity(taken, taken_units, sending, sending_units, expected):
    assert similar_course(course("ZZZ 9", taken, taken_units), sc(sending, sending_units)) is expected


# ---- through the API ----

client = TestClient(app)


def _match(courses: list[Course], label: str = "Economics, B.S."):
    pid = client.post("/profiles", json={
        "name": "t", "campus": "sjsu", "sending_institution_id": 113, "receiving_institution_id": 39,
        "majors": [label], "goals": "", "interests": [],
    }).json()["profile"]["id"]
    client.put(f"/profiles/{pid}/courses", json={"courses": [c.model_dump() for c in courses]})
    return client.post(f"/profiles/{pid}/match", json={"major_label": label})


def test_match_fetches_the_agreement_for_each_course_year(assist_fake: FakeAssist):
    res = _match([ECON_1, course("MATH 1A", "Calculus I", term="Fall 2025")])
    assert res.status_code == 200
    result = MatchResult.model_validate(res.json())
    assert result.agreement_key == ECON_BS_KEY  # requirements still come from the current year
    econ = req(result, "ECON 1A")
    assert (econ.status, econ.confidence) == ("satisfied", "high")
    keys = [r.url.params["Key"] for r in assist_fake.requests if r.url.path == "/api/articulation/Agreements"]
    assert sorted(keys) == sorted([ECON_BS_KEY, ECON_BS_2023_KEY])


def test_out_of_range_course_years_never_reach_assist(assist_fake: FakeAssist):
    junk = [course("ECON 1", "Principles of Macroeconomics", 4, year_id=y) for y in (-5, 1, 30)]
    assert _match(junk).status_code == 200
    years = {r.url.params.get("academicYearId") for r in assist_fake.requests if r.url.path == "/api/agreements"}
    assert years == {"77"}


def test_year_without_an_agreement_is_skipped_not_fatal():
    # The fake has no 1999 agreement; that course just falls back.
    res = _match([course("ECON 1", "Principles of Macroeconomics", 4, term="Fall 1999")])
    assert res.status_code == 200
    econ = req(MatchResult.model_validate(res.json()), "ECON 1A")
    assert (econ.status, econ.confidence) == ("satisfied", "low")
    assert "renumbered_match" in econ.flags
