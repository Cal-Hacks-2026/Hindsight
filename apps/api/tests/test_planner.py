"""Planner v1 against small in-test catalogs and the placeholder SJSU file."""

import json
from datetime import date

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.models import Citation, MatchResult, MatchSummary, PlanResponse, Requirement
from app.services import planner
from app.services.planner import Major, PlannerError, UnknownMajor, build_plan, resolve_majors

from .test_contract import make_profile

client = TestClient(app)
OCT_2026 = date(2026, 10, 23)


def major(courses: dict, groups: list, label="Test, B.S.", placeholder=False) -> Major:
    url = "https://example.edu/catalog"
    return Major.model_validate({
        "placeholder": placeholder, "major_label": label, "campus": "sjsu", "catalog_year": "2026-27",
        "source_url": url,
        "courses": {c: {"source_url": url, **v} for c, v in courses.items()},
        "groups": [{"source_url": url, **g} for g in groups],
    })


def terms(plan) -> dict[str, str]:
    return {c.code: s.term for s in plan for c in s.courses}


CHAIN = {
    "A 1": {"title": "A1", "units": 4},
    "A 2": {"title": "A2", "units": 4, "prereqs": ["A 1"]},
    "A 3": {"title": "A3", "units": 4, "prereqs": ["A 2"]},
    "B 1": {"title": "B1", "units": 4},
}


def test_respects_prereq_order_and_starts_next_term():
    m = major(CHAIN, [{"id": "g", "title": "Core", "rule": "all", "courses": list(CHAIN)}])
    t = terms(build_plan([m], set(), today=OCT_2026))
    assert t == {"A 1": "Spring 2027", "B 1": "Spring 2027", "A 2": "Fall 2027", "A 3": "Spring 2028"}


def test_satisfied_courses_and_prereqs_are_skipped():
    m = major(CHAIN, [{"id": "g", "title": "Core", "rule": "all", "courses": ["A 3"]}])
    plan = build_plan([m], {"A 1"}, today=OCT_2026)
    assert terms(plan) == {"A 2": "Spring 2027", "A 3": "Fall 2027"}
    assert plan[0].courses[0].reason == "Prerequisite for A 3"


def test_unit_cap_spills_over_with_critical_path_first():
    courses = {f"C {i}": {"title": f"C{i}", "units": 4} for i in range(5)}
    courses["D 1"] = {"title": "D1", "units": 4, "prereqs": ["C 4"]}
    m = major(courses, [{"id": "g", "title": "Core", "rule": "all", "courses": list(courses)}])
    plan = build_plan([m], set(), today=OCT_2026, unit_cap=12)
    assert all(sum(c.units for c in s.courses) <= 12 for s in plan)
    assert "C 4" in [c.code for c in plan[0].courses]  # unlocks D 1, so it can't wait


def test_terms_offered():
    courses = {"F 1": {"title": "F1", "units": 3, "terms_offered": ["Fall"]}}
    m = major(courses, [{"id": "g", "title": "Core", "rule": "all", "courses": ["F 1"]}])
    assert terms(build_plan([m], set(), today=OCT_2026)) == {"F 1": "Fall 2027"}


def test_n_of_counts_satisfied_and_picks_rest():
    courses = {f"E {i}": {"title": f"E{i}", "units": 3} for i in range(4)}
    m = major(courses, [{"id": "e", "title": "Electives", "rule": "n_of", "n": 2, "courses": list(courses)}])
    assert len(terms(build_plan([m], {"E 3"}, today=OCT_2026))) == 1
    assert build_plan([m], {"E 0", "E 3"}, today=OCT_2026) == []


def test_shared_course_planned_once_with_both_reasons():
    a = major(CHAIN, [{"id": "g", "title": "Core", "rule": "all", "courses": ["B 1"]}], label="A, B.S.")
    b = major(CHAIN, [{"id": "g", "title": "Core", "rule": "all", "courses": ["B 1"]}], label="B, B.A.")
    plan = build_plan([a, b], set(), today=OCT_2026)
    assert [c.reason for s in plan for c in s.courses] == ["Core (A, B.S.); Core (B, B.A.)"]


def test_placeholder_reasons_are_marked():
    m = major(CHAIN, [{"id": "g", "title": "Core", "rule": "all", "courses": ["B 1"]}], placeholder=True)
    assert build_plan([m], set(), today=OCT_2026)[0].courses[0].reason.startswith("PLACEHOLDER · ")


def test_unschedulable_raises():
    courses = {"S 1": {"title": "S1", "units": 3, "prereqs": ["S 2"], "terms_offered": ["Spring"]},
               "S 2": {"title": "S2", "units": 3, "terms_offered": ["Spring"]}}
    m = major(courses, [{"id": "g", "title": "Core", "rule": "all", "courses": ["S 1"]}])
    assert terms(build_plan([m], set(), today=OCT_2026)) == {"S 2": "Spring 2027", "S 1": "Spring 2028"}
    courses["S 2"]["terms_offered"] = []
    with pytest.raises(PlannerError):
        build_plan([major(courses, [{"id": "g", "title": "Core", "rule": "all", "courses": ["S 1"]}])], set(), today=OCT_2026)


def test_cycle_rejected(tmp_path):
    m = major({"X 1": {"title": "X", "units": 3, "prereqs": ["X 2"]},
               "X 2": {"title": "Y", "units": 3, "prereqs": ["X 1"]}},
              [{"id": "g", "title": "Core", "rule": "all", "courses": ["X 1"]}])
    (tmp_path / "m.json").write_text(m.model_dump_json())
    with pytest.raises(ValueError, match="cycle"):
        planner.load_majors(tmp_path)


def test_resolve_majors_handles_commas_in_labels():
    ds = major(CHAIN, [], label="Data Science, B.S.")
    econ = major(CHAIN, [], label="Economics, B.A.")
    pop = major(CHAIN, [], label="Population Data Science, B.S.")
    chosen = resolve_majors("Data Science, B.S.,Economics, B.A.", [], "sjsu", [ds, econ, pop])
    assert [m.major_label for m in chosen] == ["Data Science, B.S.", "Economics, B.A."]
    assert resolve_majors(None, ["Economics, B.A."], "sjsu", [ds, econ]) == [econ]
    with pytest.raises(UnknownMajor):
        resolve_majors("Data Science", [], "sjsu", [ds])
    with pytest.raises(UnknownMajor):
        resolve_majors(None, ["Data Science, B.S."], "berkeley", [ds])


def test_satisfied_from_match():
    cite = Citation(source="assist", label="x", url="https://assist.org/")
    reqs = [Requirement(id=str(i), group_title="g", rule="all", receiving_course=rc, status=st,
                        satisfied_by=[], flags=[], citation=cite, confidence="high")
            for i, (rc, st) in enumerate([("MATH 30 - Calculus I", "satisfied"),
                                          ("CS 46A + CS 46B - Programming", "satisfied"),
                                          ("MATH 39 - Linear Algebra I", "at_university")])]
    result = MatchResult(major_label="m", agreement_key="k", requirements=reqs,
                         summary=MatchSummary(satisfied=2, partial=0, missing=0, at_university=1))
    assert planner.satisfied_from_match(result) == {"MATH 30", "CS 46A", "CS 46B"}


def test_placeholder_sjsu_file_loads_and_plans():
    [ds] = [m for m in planner.load_majors() if m.major_label == "Data Science, B.S."]
    assert ds.placeholder
    plan = build_plan([ds], set(), today=OCT_2026)
    t = terms(plan)
    order = [s.term for s in plan]
    for code, course in ds.courses.items():
        for p in course.prereqs:
            if code in t:
                assert order.index(t[p]) < order.index(t[code]), (p, code)


def test_plan_route_uses_profile_majors():
    pid = make_profile()
    res = client.get(f"/profiles/{pid}/plan")
    assert res.status_code == 200
    semesters = PlanResponse.model_validate(res.json()).semesters
    assert semesters and all(c.reason.startswith("PLACEHOLDER") for s in semesters for c in s.courses)
    assert client.get(f"/profiles/{pid}/plan", params={"majors": "Basket Weaving, B.A."}).status_code == 404
