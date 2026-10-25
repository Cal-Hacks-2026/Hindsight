"""Planner v1 against small in-test catalogs and the curated SJSU files."""

import json
from datetime import date

import pytest
from fastapi.testclient import TestClient

from app.config import ASSIST_YEAR_ID
from app.main import app
from app.models import Citation, Course, MatchResult, MatchSummary, PlanResponse, Profile, Requirement
from app.services import mocks, planner
from app.services.assist import AssistError, get_service
from app.services.planner import Major, PlannerError, UnknownMajor, build_plan, resolve_majors

from .test_contract import PROFILE, make_profile

client = TestClient(app)
OCT_2026 = date(2026, 10, 23)


def major(courses: dict, groups: list, label="Test, B.S.", placeholder=False) -> Major:
    url = "https://example.edu/catalog"
    return Major.model_validate({
        "placeholder": placeholder, "major_label": label, "university_id": 39, "catalog_year": "2026-27",
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
    chosen, uncurated = resolve_majors("Data Science, B.S.,Economics, B.A.", [], 39, [ds, econ, pop])
    assert [m.major_label for m in chosen] == ["Data Science, B.S.", "Economics, B.A."] and uncurated == []
    assert resolve_majors(None, ["Economics, B.A."], 39, [ds, econ]) == ([econ], [])
    with pytest.raises(UnknownMajor):
        resolve_majors("Data Science", [], 39, [ds])
    with pytest.raises(UnknownMajor):
        resolve_majors(None, ["Data Science, B.S."], 79, [ds])


def test_resolve_majors_returns_uncurated_labels_beside_the_curated_ones():
    ds = major(CHAIN, [], label="Data Science, B.S.")
    raw = "Computer Science, B.S.,Data Science, B.S.,Business Administration, Concentration in Finance, B.S."
    chosen, uncurated = resolve_majors(raw, [], 39, [ds])
    assert chosen == [ds]
    assert uncurated == ["Computer Science, B.S.", "Business Administration, Concentration in Finance, B.S."]
    online = "Anthropology, B.A. (SJSU Online),Data Science, B.S."
    assert resolve_majors(online, [], 39, [ds]) == ([ds], ["Anthropology, B.A. (SJSU Online)"])
    assert resolve_majors(None, ["Computer Science, B.S.", "Data Science, B.S."], 39, [ds]) == (
        [ds], ["Computer Science, B.S."])


def test_no_curated_major_is_a_plain_language_404():
    ds = major(CHAIN, [], label="Data Science, B.S.")
    with pytest.raises(UnknownMajor) as e:
        resolve_majors("Computer Science, B.S.,Biology, B.A.", [], 39, [ds])
    message = str(e.value)
    assert message.startswith("We don't have SJSU's Computer Science, B.S. and Biology, B.A. requirements yet")
    assert "lower-division only (from ASSIST)" in message
    assert "[" not in message and "Plans are available for Data Science, B.S." in message


def test_unschedulable_courses_are_named_in_plain_language():
    courses = {"Z 1": {"title": "Z1", "units": 3, "terms_offered": []}, "Z 2": {"title": "Z2", "units": 3,
                                                                           "terms_offered": []}}
    m = major(courses, [{"id": "g", "title": "Core", "rule": "all", "courses": list(courses)}])
    with pytest.raises(PlannerError) as e:
        build_plan([m], set(), today=OCT_2026)
    assert "Z 1, Z 2" in str(e.value) and "[" not in str(e.value)


# ---- What counts as done on the transcript (I-09) ----


def taken(code: str, grade: str, confirmed=True) -> Course:
    prefix, number = code.split()
    return Course(prefix=prefix, number=number, title="t", units=3, grade=grade, term="Fall 2025",
                  confirmed=confirmed)


GRADED = major(
    {"G 1": {"title": "G1", "units": 3}, "G 2": {"title": "G2", "units": 3}},
    [{"id": "a", "title": "Core", "rule": "all", "courses": ["G 1"]},
     {"id": "s", "title": "Statistics", "rule": "all", "courses": ["G 2"], "notes": ['Grade of "C" or better.']}],
)
GRADED.notes = ['A grade of "C-" or better is required for courses being used to meet any requirement.']


@pytest.mark.parametrize(("code", "grade", "done"), [
    ("G 1", "A", True), ("G 1", "C-", True), ("G 1", "P", True), ("G 1", "IP", True),
    ("G 1", "D+", False), ("G 1", "W", False), ("G 1", "F", False), ("G 1", "NP", False), ("G 1", "", False),
    ("G 2", "C", True), ("G 2", "C-", False),  # the Statistics group asks for C
    ("X 9", "D", True),  # not in any planned major: no minimum to apply, but still passed
    ("X 9", "W", False),
])
def test_transcript_courses_count_only_when_passed_or_in_progress(code, grade, done):
    assert (code in planner.satisfied_from_courses([taken(code, grade)], [GRADED])) is done


def test_unconfirmed_and_retaken_courses():
    assert planner.satisfied_from_courses([taken("G 1", "A", confirmed=False)], [GRADED]) == set()
    assert planner.satisfied_from_courses([taken("G 1", "W"), taken("G 1", "B")], [GRADED]) == {"G 1"}


def test_minimum_grades_from_the_curated_sjsu_files():
    majors = {m.major_label: m for m in planner.load_majors()}
    ds, econ = majors[DS], majors[ECON]
    assert planner.minimum_grades([ds])["CS 146"] == "C-"
    mins = planner.minimum_grades([econ])
    assert mins["ECON 1A"] == "C-" and mins["STAT 95"] == "C"
    assert planner.minimum_grades([ds, econ])["STAT 95"] == "C"  # strictest across the planned majors


def test_in_progress_courses_are_assumed_passed_for_planning_only():
    courses = [taken("MATH 1B", "IP"), taken("MATH 1C", "W")]
    planning = planner.assume_in_progress_passed(courses)
    assert [c.grade for c in planning] == ["P", "W"]
    assert [c.grade for c in courses] == ["IP", "W"]  # the caller's list is untouched


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


CATALOG_PDF = "https://catalog.sjsu.edu/mime/media/23/8710/2025-2026+Academic+Catalog.pdf#page="
DS, ECON = "Data Science, B.S.", "Economics, B.S."


def test_one_of_prereq_reuses_a_planned_alternative():
    courses = {"P 1": {"title": "P1", "units": 3}, "P 2": {"title": "P2", "units": 3},
               "Q 1": {"title": "Q1", "units": 3, "prereqs_one_of": [["P 1", "P 2"]]}}
    m = major(courses, [{"id": "g", "title": "Core", "rule": "all", "courses": ["P 2", "Q 1"]}])
    t = terms(build_plan([m], set(), today=OCT_2026))
    assert t == {"P 2": "Spring 2027", "Q 1": "Fall 2027"}  # P 1 isn't pulled in too
    plan = build_plan([major(courses, [{"id": "g", "title": "Core", "rule": "all", "courses": ["Q 1"]}])],
                      set(), today=OCT_2026)
    assert terms(plan) == {"P 1": "Spring 2027", "Q 1": "Fall 2027"}  # first listed when none is planned
    assert plan[1].courses[0].prereqs == ["P 1 or P 2"]


def test_one_of_prereq_met_by_any_alternative_even_outside_the_file():
    courses = {"P 1": {"title": "P1", "units": 3},
               "Q 1": {"title": "Q1", "units": 3, "prereqs_one_of": [["P 1", "ELSEWHERE 9"]]}}
    m = major(courses, [{"id": "g", "title": "Core", "rule": "all", "courses": ["Q 1"]}])
    assert terms(build_plan([m], {"ELSEWHERE 9"}, today=OCT_2026)) == {"Q 1": "Spring 2027"}


def test_units_rule_counts_satisfied_units_and_picks_the_rest():
    courses = {"U 1": {"title": "U1", "units": 4}, "U 2": {"title": "U2", "units": 4},
               "U 3": {"title": "U3", "units": 4}, "U 4": {"title": "U4", "units": 1}}
    group = {"id": "u", "title": "Electives", "rule": "units", "units": 8, "courses": list(courses)}
    assert set(terms(build_plan([major(courses, [group])], set(), today=OCT_2026))) == {"U 1", "U 2"}
    assert set(terms(build_plan([major(courses, [group])], {"U 3"}, today=OCT_2026))) == {"U 1"}
    plan = build_plan([major(courses, [group])], set(), today=OCT_2026)
    assert "toward 8 units" in plan[0].courses[0].reason
    with pytest.raises(PlannerError, match="can't reach"):
        build_plan([major(courses, [{**group, "units": 20}])], set(), today=OCT_2026)


def test_electives_flagged_for_review_are_picked_last():
    courses = {"R 1": {"title": "R1", "units": 3, "needs_review": ["approval needed"]},
               "R 2": {"title": "R2", "units": 3}}
    m = major(courses, [{"id": "e", "title": "Electives", "rule": "n_of", "n": 1, "courses": ["R 1", "R 2"]}])
    assert set(terms(build_plan([m], set(), today=OCT_2026))) == {"R 2"}


def test_a_course_counts_toward_one_group_per_major():
    courses = {"V 1": {"title": "V1", "units": 3}, "V 2": {"title": "V2", "units": 3}}
    m = major(courses, [{"id": "a", "title": "Pick one", "rule": "n_of", "n": 1, "courses": ["V 1"]},
                        {"id": "b", "title": "Electives", "rule": "n_of", "n": 1, "courses": ["V 1", "V 2"]}])
    assert set(terms(build_plan([m], set(), today=OCT_2026))) == {"V 1", "V 2"}
    assert set(terms(build_plan([m], {"V 1"}, today=OCT_2026))) == {"V 2"}


def test_group_without_courses_is_reported_not_scheduled(tmp_path):
    unlisted = {"id": "d", "title": "Domain", "rule": "units", "units": 9, "courses": [],
                "needs_review": ["no course list"]}
    m = major(CHAIN, [{"id": "g", "title": "Core", "rule": "all", "courses": ["B 1"]}, unlisted])
    assert terms(build_plan([m], set(), today=OCT_2026)) == {"B 1": "Spring 2027"}
    assert [g.id for _, g in planner.unscheduled_groups([m])] == ["d"]
    bad = major(CHAIN, [{**unlisted, "needs_review": []}])
    (tmp_path / "m.json").write_text(bad.model_dump_json())
    with pytest.raises(ValueError, match="needs_review"):
        planner.load_majors(tmp_path)


def test_sjsu_files_are_curated_with_sources():
    majors = {m.major_label: m for m in planner.load_majors()}
    for label in (DS, ECON):
        m = majors[label]
        assert not m.placeholder and m.catalog_year == "2025-26"
        assert m.source_url.startswith(CATALOG_PDF)
        assert any("2026-2027" in n for n in m.needs_review)
        items = list(m.courses.values()) + m.groups
        assert items and all(i.source_url.startswith(CATALOG_PDF) for i in items)
    ds, econ = majors[DS], majors[ECON]
    assert ds.courses["CS 163"].prereqs_one_of == [["CS 156", "CS 171"]]
    assert {g.id: g.units for g in ds.groups if g.rule == "units"} == {"ds-electives": 15, "ds-domain": 9}
    assert [g.title for _, g in planner.unscheduled_groups([ds, econ])] == ["Domain Field Electives"]
    assert "ECON 109" not in econ.courses  # "with the exception of ECON 109"
    assert sum(econ.courses[c].units for g in econ.groups if g.id == "econ-core" for c in g.courses) == 30


def demo_plan(labels, today=OCT_2026):
    """The counselor demo student's university semesters, planned the way /plan and the counselor both do it."""
    majors = [m for m in planner.load_majors() if m.major_label in labels]
    courses = [c.model_copy(update={"confirmed": True}) for c in mocks.transcript_courses()]
    matches = [get_service().match(113, 39, ASSIST_YEAR_ID, label, courses) for label in labels]
    return build_plan(majors, planner.satisfied(courses, matches, majors), today=today), majors


def demo_roadmap(labels, uncurated=(), today=None):
    majors = [m for m in planner.load_majors() if m.major_label in labels]
    courses = [c.model_copy(update={"confirmed": True}) for c in mocks.transcript_courses()]
    profile = Profile(id="p", created_at="", **PROFILE)

    def match(label):
        try:
            return get_service().match(113, 39, ASSIST_YEAR_ID, label, courses)
        except AssistError:
            return None  # e.g. no agreement in the fixtures

    return planner.roadmap_for(profile, courses, majors, list(uncurated), match, today=today or date.today())


@pytest.mark.parametrize("labels", [[DS], [DS, ECON]])
def test_sjsu_plan_respects_every_prereq(labels):
    plan, majors = demo_plan(labels)
    t = terms(plan)
    order = [s.term for s in plan]
    catalog = {code: c for m in majors for code, c in m.courses.items()}
    for code, term in t.items():
        for p in catalog[code].prereqs:
            if p in t:
                assert order.index(t[p]) < order.index(term), (p, code)
        for group in catalog[code].prereqs_one_of:
            planned = [order.index(t[p]) for p in group if p in t]
            if planned:
                assert min(planned) < order.index(term), (group, code)
    assert all(sum(c.units for c in s.courses) <= planner.DEFAULT_UNIT_CAP for s in plan)


def test_plan_route_uses_profile_majors():
    pid = make_profile()
    res = client.get(f"/profiles/{pid}/plan")
    assert res.status_code == 200
    semesters = PlanResponse.model_validate(res.json()).semesters
    assert semesters and not any(c.reason.startswith("PLACEHOLDER") for s in semesters for c in s.courses)
    assert client.get(f"/profiles/{pid}/plan", params={"majors": "Basket Weaving, B.A."}).status_code == 404


def confirmed_student() -> str:
    pid = make_profile()
    courses = [c.model_dump() for c in mocks.transcript_courses()]
    assert client.put(f"/profiles/{pid}/courses", json={"courses": courses}).status_code == 200
    return pid


def test_plan_route_counts_assist_satisfied_courses_like_the_counselor():
    pid = confirmed_student()
    res = client.get(f"/profiles/{pid}/plan", params={"majors": f"{DS},{ECON}"})
    assert res.status_code == 200
    semesters = PlanResponse.model_validate(res.json()).semesters
    scheduled = {c.code for s in semesters for c in s.courses}
    # The transcript says MATH 1A/1B and STAT C1000; ASSIST maps them to these, so they're done.
    assert scheduled.isdisjoint({"MATH 30", "MATH 31", "STAT 95"})
    assert semesters == demo_roadmap([DS, ECON]).semesters


def test_plan_route_falls_back_to_the_transcript_when_assist_is_down(monkeypatch):
    pid = confirmed_student()

    def assist_down(*a, **kw):
        raise AssistError("timeout")

    monkeypatch.setattr(get_service(), "match", assist_down)
    res = client.get(f"/profiles/{pid}/plan")
    assert res.status_code == 200
    scheduled = {c.code for s in PlanResponse.model_validate(res.json()).semesters for c in s.courses}
    assert {"MATH 30", "MATH 31"} <= scheduled


def test_plan_route_plans_the_curated_majors_and_lists_the_rest():
    pid = confirmed_student()
    res = client.get(f"/profiles/{pid}/plan", params={"majors": f"Computer Science, B.S.,{DS}"})
    assert res.status_code == 200
    body = PlanResponse.model_validate(res.json())
    assert body.uncurated_majors == ["Computer Science, B.S."]
    # Computer Science still gets its community-college courses; only its university semesters are missing.
    assert body.semesters == demo_roadmap([DS], ["Computer Science, B.S."]).semesters
    # Nothing left out: the field is omitted, like every optional contract field.
    assert "uncurated_majors" not in client.get(f"/profiles/{pid}/plan", params={"majors": DS}).json()


def test_plan_route_with_no_curated_major_says_so_plainly():
    pid = confirmed_student()
    res = client.get(f"/profiles/{pid}/plan", params={"majors": "Computer Science, B.S."})
    assert res.status_code == 404
    detail = res.json()["detail"]
    assert detail.startswith("We don't have SJSU's Computer Science, B.S. requirements yet")
    assert "[" not in detail


def student_with(grades: dict[str, str]) -> str:
    """The demo student with some grades changed, e.g. {"MATH 1B": "IP"}."""
    pid = make_profile()
    courses = [c.model_copy(update={"grade": grades.get(f"{c.prefix} {c.number}", c.grade)}).model_dump()
               for c in mocks.transcript_courses()]
    assert client.put(f"/profiles/{pid}/courses", json={"courses": courses}).status_code == 200
    return pid


def scheduled_codes(pid: str) -> set[str]:
    res = client.get(f"/profiles/{pid}/plan", params={"majors": DS})
    assert res.status_code == 200
    return {c.code for s in PlanResponse.model_validate(res.json()).semesters for c in s.courses}


def test_plan_route_treats_in_progress_as_done_and_withdrawn_as_not():
    assert scheduled_codes(student_with({})).isdisjoint({"MATH 1B", "MATH 31"})
    assert scheduled_codes(student_with({"MATH 1B": "IP"})).isdisjoint({"MATH 1B", "MATH 31"})  # P7: not rescheduled
    # Withdrawn or below the C- minimum: retaken at De Anza before transfer, not at SJSU.
    for grade in ("W", "D"):
        codes = scheduled_codes(student_with({"MATH 1B": grade}))
        assert "MATH 1B" in codes and "MATH 31" not in codes


def test_plan_route_ignores_failed_university_courses():
    """P9: courses taken at SJSU itself count by code, but only when passed (or in progress)."""
    pid = make_profile()
    rows = [taken("MATH 39", "IP"), taken("CS 46A", "F"), taken("CS 46B", "NP")]
    assert client.put(f"/profiles/{pid}/courses", json={"courses": [c.model_dump() for c in rows]}).status_code == 200
    codes = scheduled_codes(pid)
    # MATH 39 (IP) is done; CS 46A and CS 46B (F, NP) aren't, so De Anza courses are planned for them.
    assert codes.isdisjoint({"MATH 39", "MATH 2B", "CS 46A", "CS 46B"}) and {"CIS 35A", "CIS 22C"} <= codes
