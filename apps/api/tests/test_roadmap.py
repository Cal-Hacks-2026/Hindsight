"""Two-phase roadmap (I-03): community-college terms before transfer, SJSU semesters after.

Personas from tests/fixtures/personas/ (make_fixtures.py), matched against the saved
De Anza → SJSU agreements.
"""

from datetime import date

import pytest
from fastapi.testclient import TestClient

from app.config import ASSIST_YEAR_ID
from app.main import app
from app.models import Course, PlanResponse, Profile
from app.services import planner
from app.services.assist import AssistError, get_service
from app.services.transcript import academic_year_id

from .test_contract import PROFILE, make_profile

client = TestClient(app)
OCT_2026 = date(2026, 10, 24)
DS, ECON = "Data Science, B.S.", "Economics, B.S."

P1 = [
    ("Fall 2023", [("MATH", "1A", 5, "A"), ("EWRT", "1A", 5, "A-"), ("MATH", "10", 5, "B+")]),
    ("Winter 2024", [("MATH", "1B", 5, "B+"), ("ECON", "1", 5, "A"), ("CIS", "22A", 4.5, "A")]),
    ("Spring 2024", [("MATH", "1C", 5, "B"), ("CIS", "36A", 4.5, "A"), ("PSYC", "1", 5, "A")]),
    ("Fall 2024", [("MATH", "2B", 5, "B+"), ("MATH", "22", 5, "B"), ("COMM", "1", 5, "A")]),
    ("Winter 2025", [("CIS", "36B", 4.5, "A-"), ("PHIL", "3", 5, "A"), ("KINS", "1A", 1, "P")]),
    ("Fall 2025", [("STAT", "C1000", 5, "A"), ("ENGL", "C1002", 5, "A-")]),
]
P3 = [
    ("Summer 2026", [("MATH", "1A", 5, "A"), ("ENGL", "C1000", 5, "A-")]),
    ("Fall 2026", [("CIS", "22A", 4.5, "IP")]),
]
P7 = [
    ("Fall 2019", [("CIS", "22A", 4.5, "A"), ("EWRT", "1A", 5, "C-")]),
    ("Fall 2022", [("MATH", "1A", 5, "W")]),
    ("Winter 2023", [("MATH", "1A", 5, "F")]),
    ("Spring 2023", [("MATH", "1A", 5, "A"), ("ECON", "1", 5, "P")]),
    ("Fall 2023", [("MATH", "1B", 5, "B"), ("CIS", "22B", 4.5, "NP")]),
    ("Fall 2026", [("MATH", "1C", 5, "IP"), ("ENGL", "C1001", 5, "IP")]),
]


def transcript(terms) -> list[Course]:
    return [Course(prefix=p, number=n, title="t", units=u, grade=g, term=term,
                   academic_year_id=academic_year_id(term), confirmed=True)
            for term, rows in terms for p, n, u, g in rows]


def roadmap(courses: list[Course], labels=(DS, ECON), transfer_term=None, today=OCT_2026, start_term=None,
            stage=None):
    """Planned the way /plan and the counselor do it."""
    profile = Profile(id="p", created_at="", **PROFILE, stage=stage)
    majors, uncurated = planner.resolve_majors(",".join(labels), [], 39, planner.load_majors())
    planning = planner.assume_in_progress_passed(courses)

    def match(label):
        try:
            return get_service().match(113, 39, ASSIST_YEAR_ID, label, planning)
        except AssistError:
            return None

    return planner.roadmap_for(profile, courses, majors, uncurated, match, today=today, transfer_term=transfer_term,
                               start_term=start_term)


def phase(r, name) -> list:
    return [s for s in r.semesters if s.phase == name]


def codes(semesters) -> list[str]:
    return [c.code for s in semesters for c in s.courses]


def term_of(semesters) -> dict[str, str]:
    return {c.code: s.term for s in semesters for c in s.courses}


LOWER_DIVISION = {"MATH 30", "MATH 31", "MATH 39", "MATH 42", "CS 46A", "CS 46B", "ECON 1A", "ECON 1B"}


def test_p2_zero_courses_plans_de_anza_quarters_then_sjsu():
    r = roadmap([])
    before, after = phase(r, "before_transfer"), phase(r, "after_transfer")
    assert r.semesters == before + after  # college terms first
    assert {s.institution for s in before} == {"De Anza College"} and {s.term_system for s in before} == {"quarter"}
    assert {s.institution for s in after} == {"San Jose State University"}
    assert before[0].term == "Fall 2027"  # no courses yet: a high-school senior starts in Fall
    assert [s.term.split()[0] for s in before[:4]] == ["Fall", "Winter", "Spring", "Fall"]
    assert all(sum(c.units for c in s.courses) <= planner.DEFAULT_CC_UNIT_CAP for s in before)
    # One option per requirement, fewest courses: MATH 1A (not 1AH), CIS 35A for CS 46A.
    t = term_of(before)
    assert {"MATH 1A", "MATH 1B", "MATH 1C", "MATH 2B", "MATH 22", "CIS 35A", "CIS 22C",
            "ECON C2001", "ECON C2002"} <= set(t)
    assert "MATH 1AH" not in t and "CIS 22A" not in t
    keys = {code: planner.term_key(term) for code, term in t.items()}
    assert keys["MATH 1A"] < keys["MATH 1B"] < keys["MATH 1C"] < keys["MATH 2B"]  # sequence, then MATH 39 ← 31
    assert keys["CIS 35A"] < keys["CIS 22C"]  # CS 46B needs CS 46A
    # Units come from the agreement: CIS courses are 4.5 quarter units.
    assert {c.code: c.units for s in before for c in s.courses}["CIS 22C"] == 4.5
    # Transfer: the first Fall after De Anza; SJSU semesters start then, with no lower division left.
    assert r.transfer_term == r.earliest_transfer_term == "Fall 2029" == after[0].term
    assert LOWER_DIVISION.isdisjoint(codes(after)) and {"CS 146", "ECON 101"} <= set(codes(after))
    assert not r.not_before_transfer


def test_p1_leaves_only_a_few_de_anza_gaps():
    r = roadmap(transcript(P1))
    before = phase(r, "before_transfer")
    assert set(codes(before)) == {"CIS 22C", "ECON C2001", "CIS 40"}  # CS 46B, ECON 1B, the DS "choose from"
    assert len(before) == 1 and before[0].term == "Winter 2027"
    assert r.transfer_term == "Fall 2027" == phase(r, "after_transfer")[0].term
    assert LOWER_DIVISION.isdisjoint(codes(phase(r, "after_transfer")))
    assert "CS 22A" not in codes(phase(r, "after_transfer"))  # CIS 40 earns it at De Anza


def test_p3_in_progress_course_counts_and_its_sequence_is_finished():
    r = roadmap(transcript(P3), labels=(DS,))
    t = term_of(phase(r, "before_transfer"))
    assert "CIS 22A" not in t and "MATH 1A" not in t  # in progress counts as done; A counts
    assert "CIS 22B" in t and "CIS 35A" not in t  # finishes CIS 22A + 22B rather than starting over
    assert planner.term_key(t["CIS 22B"]) < planner.term_key(t["CIS 22C"])


def test_p7_withdrawn_failed_and_repeated_courses():
    r = roadmap(transcript(P7), labels=(DS,))
    t = term_of(phase(r, "before_transfer"))
    # MATH 1A: W, F, then A: the repeat counts. MATH 1C is in progress: MATH 31 is done.
    assert t.keys().isdisjoint({"MATH 1A", "MATH 1B", "MATH 1C"})
    assert "CIS 22B" in t  # NP doesn't count: retake it to finish the CIS 22A + 22B sequence
    assert "MATH 31" not in codes(phase(r, "after_transfer"))


def test_requested_transfer_term_too_early_moves_requirements_after_transfer():
    r = roadmap([], transfer_term="Fall 2027", start_term="Winter 2027")
    before, after = phase(r, "before_transfer"), phase(r, "after_transfer")
    assert r.transfer_term == after[0].term == "Fall 2027" and r.earliest_transfer_term == "Fall 2028"
    assert all(planner.term_key(s.term) < planner.term_key("Fall 2027") for s in before)
    assert {"MATH 1B", "MATH 1C", "MATH 2B"} <= set(r.not_before_transfer)
    assert set(r.not_before_transfer).isdisjoint(codes(before))
    # Their SJSU courses are planned after transfer instead, in prerequisite order.
    t = term_of(after)
    assert {"MATH 31", "MATH 39"} <= set(t) and planner.term_key(t["MATH 31"]) < planner.term_key(t["MATH 39"])
    # What still fits stays at De Anza.
    assert {"MATH 1A", "CIS 35A", "CIS 22C"} <= set(codes(before))


def test_requested_later_transfer_term_starts_sjsu_then():
    r = roadmap(transcript(P1), transfer_term="Spring 2029")
    assert phase(r, "after_transfer")[0].term == "Spring 2029" and not r.not_before_transfer


@pytest.mark.parametrize("bad", ["Winter 2028", "Fall 2025", "Fall 2099", "soon"])
def test_transfer_term_must_be_a_coming_fall_or_spring(bad):
    with pytest.raises(planner.PlannerError):
        roadmap([], transfer_term=bad)


def test_plan_route_returns_both_phases_and_the_transfer_term():
    pid = make_profile()
    assert client.put(f"/profiles/{pid}/courses", json={"courses": []}).status_code == 200
    body = PlanResponse.model_validate(client.get(f"/profiles/{pid}/plan").json())
    assert body.semesters[0].phase == "before_transfer" and body.semesters[-1].phase == "after_transfer"
    assert body.transfer_term == body.earliest_transfer_term
    assert body.transfer_term.startswith("Fall ")
    # Transferring the Fall the college terms start (no courses yet: a Fall) leaves no room for them.
    early = client.get(f"/profiles/{pid}/plan", params={"transfer_term": body.semesters[0].term}).json()
    assert early["not_before_transfer"]
    res = client.get(f"/profiles/{pid}/plan", params={"transfer_term": "Winter 2030"})
    assert res.status_code == 422 and "Fall" in res.json()["detail"]


def test_semester_college_plans_fall_and_spring_only():
    r = planner.build_roadmap([], set(), [], {}, [], "semester", today=OCT_2026)
    assert r.semesters == [] and r.transfer_term == "Fall 2027"
    terms = planner._cc_terms(planner.next_cc_term(OCT_2026, "semester"), "semester")
    assert [next(terms) for _ in range(3)] == [("Spring", 2027), ("Fall", 2027), ("Spring", 2028)]
    quarters = planner._cc_terms(("Spring", 2027), "quarter")
    assert [next(quarters) for _ in range(3)] == [("Spring", 2027), ("Fall", 2027), ("Winter", 2028)]


def test_term_system_from_assist_with_a_fallback():
    service = get_service()
    assert service.term_system(113) == "quarter"  # fixtures lack termType: De Anza is a known quarter college
    service._institutions = (float("inf"), {7: {"id": 7, "termType": 0}, 51: {"id": 51, "termType": 1}})
    assert service.term_system(7) == "semester" and service.term_system(51) == "quarter"


@pytest.mark.parametrize(("option", "alternatives"), [
    ("MATH 1A or MATH 1AH", [["MATH 1A"], ["MATH 1AH"]]),
    ("MATH 1B + MATH 1C (or honors)", [["MATH 1B", "MATH 1C"]]),
    ("CIS 22A + CIS 22B (or honors)", [["CIS 22A", "CIS 22B"]]),
    ("(MATH 1A or MATH 1AH) + MATH 1B", [["MATH 1A", "MATH 1B"], ["MATH 1AH", "MATH 1B"]]),
    ("C S 1A", [["C S 1A"]]),
])
def test_option_alternatives(option, alternatives):
    assert planner.option_alternatives(option) == alternatives


def test_unknown_uncurated_labels_never_reach_assist(assist_fake):
    """A label ASSIST doesn't list for this pair would otherwise trigger a live lookup per label."""
    profile = Profile(id="p", created_at="", **PROFILE)
    majors, _ = planner.resolve_majors(DS, [], 39, planner.load_majors())
    asked = []

    def match(label):
        asked.append(label)
        return get_service().match(113, 39, ASSIST_YEAR_ID, label, [])

    fake = [f"Basket Weaving {i}, B.A." for i in range(20)]
    planner.roadmap_for(profile, [], majors, fake, match, today=OCT_2026)
    assert asked == [DS]


def test_default_start_is_next_fall_with_no_courses_else_the_next_term():
    fresh = roadmap([])
    assert fresh.default_start_term == fresh.start_term == "Fall 2027"
    assert phase(fresh, "before_transfer")[0].term == "Fall 2027"
    returning = roadmap(transcript(P3), labels=(DS,))
    assert returning.default_start_term == returning.start_term == "Winter 2027"  # next De Anza quarter
    assert phase(returning, "before_transfer")[0].term == "Winter 2027"
    # Before September, the next Fall is this year's.
    assert planner.default_start(date(2026, 5, 1), "quarter", []) == ("Fall", 2026)
    assert planner.default_start(date(2026, 5, 1), "semester", transcript(P3)) == ("Fall", 2026)


def test_a_student_already_at_college_starts_next_term_not_next_fall():
    # No courses yet, but already enrolled: the next term that hasn't started (De Anza is on quarters).
    fresh = roadmap([], stage="community_college")
    assert fresh.default_start_term == fresh.start_term == "Winter 2027"
    assert phase(fresh, "before_transfer")[0].term == "Winter 2027"
    assert planner.default_start(OCT_2026, "semester", [], "community_college") == ("Spring", 2027)
    # A high-school senior still starts in Fall.
    assert roadmap([], stage="high_school").default_start_term == "Fall 2027"
    assert planner.default_start(OCT_2026, "semester", [], "high_school") == ("Fall", 2027)


def test_requested_start_term():
    r = roadmap([], start_term="Winter 2027")
    assert r.start_term == phase(r, "before_transfer")[0].term == "Winter 2027"
    assert r.default_start_term == "Fall 2027" and r.start_term_choices[0] == "Winter 2027"
    with pytest.raises(planner.PlannerError):
        roadmap([], start_term="Fall 2026")  # already started
    with pytest.raises(planner.PlannerError):
        roadmap([], start_term="Summer 2027")


def test_plan_route_takes_a_start_term():
    pid = make_profile()
    assert client.put(f"/profiles/{pid}/courses", json={"courses": []}).status_code == 200
    body = client.get(f"/profiles/{pid}/plan").json()
    assert body["start_term"] == body["default_start_term"] == body["semesters"][0]["term"]
    later = body["start_term_choices"][-1]
    assert client.get(f"/profiles/{pid}/plan", params={"start_term": later}).json()["semesters"][0]["term"] == later
    assert client.get(f"/profiles/{pid}/plan", params={"start_term": "Fall 1999"}).status_code == 422
