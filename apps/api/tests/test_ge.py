"""GE progress (Cal-GETC / IGETC) against De Anza's real ASSIST lists (tests/fixtures/ge/).

Personas from tests/fixtures/personas/ (make_fixtures.py). The 2026–27 lists are whole; earlier
years keep only the courses on the De Anza persona transcripts (see fixtures/ge/README.md).
"""

import json
from dataclasses import replace

import httpx
import pytest
from fastapi.testclient import TestClient

from app.config import ASSIST_YEAR_ID
from app.main import app
from app.models import GeResponse, Profile
from app.services import ge, planner
from app.services.assist import AssistError, get_service
from app.services.ge import lists, rules
from app.services.ge import plan as ge_plan
from app.services.ge.lists import GeListStore

from .test_contract import PROFILE
from .test_roadmap import DS, ECON, OCT_2026, P1, P3, P7, roadmap, transcript

client = TestClient(app)
DE_ANZA, SJSU, BERKELEY = 113, 39, 79


def run(terms, override=None, receiving=SJSU) -> GeResponse:
    return ge.progress(transcript(terms), DE_ANZA, ge.get_store(), override, receiving)


def area(r: GeResponse, code: str):
    return next(a for a in r.areas if a.code == code)


def codes(a) -> list[str]:
    return [c.code for c in a.courses]


def option_codes(a) -> list[str]:
    return [o.code for o in a.options or []]


# ---- which pattern ----


@pytest.mark.parametrize("first_term, pattern, v23", [
    ("Fall 2019", "igetc", True),
    ("Summer 2023", "igetc", True),
    ("Fall 2023", "igetc", False),
    ("Summer 2025", "igetc", False),
    ("Fall 2025", "calgetc", False),
    ("Winter 2027", "calgetc", False),
])
def test_pattern_follows_first_term(first_term, pattern, v23):
    choice = rules.choose(transcript([(first_term, [("MATH", "1A", 5, "A")])]))
    assert (choice.pattern, choice.default, choice.igetc_v23) == (pattern, pattern, v23)
    assert first_term in choice.rule and choice.citation.url.startswith(rules.CALGETC_PDF)


def test_no_courses_is_calgetc_and_override_wins():
    assert rules.choose([]).pattern == "calgetc"
    choice = rules.choose(transcript(P1), override="calgetc")
    assert (choice.pattern, choice.default) == ("calgetc", "igetc")
    assert "You chose Cal-GETC" in choice.rule


# ---- personas ----


def test_p1_igetc_areas_from_the_year_each_course_was_taken():
    r = run(P1)
    assert (r.pattern, r.pattern_name, r.started_term) == ("igetc", "IGETC", "Fall 2023")
    assert [a.code for a in r.areas] == ["1A", "1B", "1C", "2", "3A", "3B", "3", "4", "5A", "5B", "5C", "6", "7"]
    assert codes(area(r, "1A")) == ["EWRT 1A"] and codes(area(r, "1B")) == ["PHIL 3"]
    assert codes(area(r, "1C")) == ["COMM 1"] and area(r, "2").status == "done"
    assert codes(area(r, "4")) == ["ECON 1", "PSYC 1"] and area(r, "4").status == "done"
    # ENGL C1002 (Fall 2025): De Anza's 3B approval for it starts Fall 2026, so it doesn't count.
    assert all("ENGL C1002" not in codes(a) for a in r.areas)
    assert area(r, "3B").status == "missing" and "PHIL 20A" in option_codes(area(r, "3B"))
    assert area(r, "3A").still_needed == 1 and "ARTS 2A" in option_codes(area(r, "3A"))
    # SJSU is a CSU: IGETC's UC-only language area isn't required; Area 7 is (started Fall 2023).
    assert area(r, "6").required is False and area(r, "7").required is True
    assert r.summary.model_dump() == {"done": 5, "in_progress": 0, "missing": 7}
    assert r.term_system == "quarter" and r.institution == "De Anza College"
    # Each course cites the list for its own year.
    assert area(r, "1A").courses[0].citation.label == "ASSIST · De Anza College · IGETC (2023–2024)"
    assert "year=74&institution=113&type=IGETC&view=transferability" in area(r, "1A").courses[0].citation.url


def test_p1_on_calgetc_uses_igetc_courses_from_before_fall_2025():
    r = run(P1, override="calgetc")
    assert (r.pattern, r.default_pattern) == ("calgetc", "igetc")
    assert [a.code for a in r.areas] == ["1A", "1B", "1C", "2", "3A", "3B", "4", "5A", "5B", "5C", "6"]
    assert area(r, "1A").courses[0].flags == ["igetc_course"]
    assert area(r, "6").title == "Ethnic Studies" and area(r, "6").status == "missing"
    assert rules.CROSSOVER_CITATION in r.citations


def test_p3_calgetc_in_progress_course_outside_ge():
    r = run(P3)
    assert (r.pattern, r.started_term) == ("calgetc", "Summer 2026")
    assert codes(area(r, "1A")) == ["ENGL C1000"] and codes(area(r, "2")) == ["MATH 1A"]
    assert r.summary.done == 2 and r.summary.in_progress == 0
    assert all("CIS 22A" not in codes(a) for a in r.areas)
    assert "ENGL C1000" not in option_codes(area(r, "1B"))
    assert option_codes(area(r, "1B"))[:3] == ["COMM 9", "COMM 9H", "ENGL C1001"]


def test_p7_grades_repeats_and_igetc_2_3():
    r = run(P7)
    assert r.started_term == "Fall 2019"
    assert "7" not in [a.code for a in r.areas]  # Area 7 starts with Fall 2023 students
    a4 = area(r, "4")
    assert (a4.courses_required, a4.units_required) == (3, 12)
    assert a4.courses[0].code == "ECON 1" and a4.courses[0].flags == ["pass_no_pass"]
    a1 = area(r, "1A")  # EWRT 1A with a C-
    assert a1.status == "missing" and [(c.code, c.flags) for c in a1.not_counted] == [("EWRT 1A", ["below_c"])]
    assert codes(area(r, "2")) == ["MATH 1A"] and area(r, "2").courses[0].grade == "A"  # W, F, then A
    assert area(r, "1B").status == "in_progress" and codes(area(r, "1B")) == ["ENGL C1001"]
    assert area(r, "1B").still_needed == 0 and area(r, "1B").options


def test_no_courses_lists_options_for_every_area():
    r = run([])
    assert r.pattern == "calgetc" and r.started_term is None and r.options_year == "2026-2027"
    assert all(a.status == "missing" and a.options for a in r.areas)
    assert option_codes(area(r, "1A")) == ["ENGL C1000", "ENGL C1000H", "ESL 5"]
    assert option_codes(area(r, "5A"))[:2] == ["ASTR 4", "ASTR 10"]  # natural order


# ---- the rules ----


def test_a_course_counts_only_while_its_area_was_approved():
    # IGETC 2A for MATH 10 ends Fall 2025 (STAT C1000 replaced it).
    assert codes(area(run([("Fall 2024", [("MATH", "10", 5, "A")])]), "2")) == ["MATH 10"]
    assert codes(area(run([("Fall 2025", [("MATH", "10", 5, "A")])]), "2")) == []
    # Cal-GETC 4 for ECON 1 ends Fall 2026; ECON C2001 replaces it.
    late = run([("Fall 2026", [("PSYC", "C1000", 4, "A"), ("ECON", "1", 4, "A")])])
    assert codes(area(late, "4")) == ["PSYC C1000"]


def test_one_area_per_course_with_the_lab_exception():
    r = run([("Fall 2026", [("CHEM", "1A", 5, "A"), ("AFAM", "11", 4, "A"), ("PHIL", "20A", 4, "B")]),
             ("Winter 2027", [("PSYC", "C1000", 4, "A"), ("SOC", "1", 4, "B+")])])
    # AFAM 11 is approved for 3B, 4 and 6: it fills 6, leaving 3B to PHIL 20A and 4 to PSYC + SOC.
    assert codes(area(r, "6")) == ["AFAM 11"]
    assert codes(area(r, "3B")) == ["PHIL 20A"]
    assert codes(area(r, "4")) == ["PSYC C1000", "SOC 1"]
    # CHEM 1A is 5A and also meets the lab.
    assert codes(area(r, "5A")) == ["CHEM 1A"] and codes(area(r, "5C")) == ["CHEM 1A"]
    assert area(r, "5C").status == "done"


def test_area_4_needs_two_subjects():
    two_econ = [("Fall 2026", [("ECON", "C2001", 4, "A"), ("ECON", "C2002", 4, "A")])]
    a4 = area(run(two_econ), "4")
    assert a4.status == "missing" and a4.still_needed == 1 and len(a4.courses) == 2
    mixed = area(run(two_econ + [("Winter 2027", [("PSYC", "C1000", 4, "IP")])]), "4")
    assert mixed.status == "in_progress" and "PSYC C1000" in codes(mixed)


def test_in_progress_completes_an_area():
    a = area(run([("Fall 2026", [("PHIL", "20A", 4, "IP")])]), "3B")
    assert (a.status, a.still_needed, codes(a)) == ("in_progress", 0, ["PHIL 20A"])


def test_igetc_third_arts_or_humanities_course():
    r = run([("Fall 2023", [("EWRT", "1A", 5, "A")]),
             ("Fall 2026", [("PHIL", "20A", 4, "A"), ("PHIL", "1", 4, "A"), ("ARTS", "2A", 4, "A")])])
    assert codes(area(r, "3A")) == ["ARTS 2A"]
    assert len(area(r, "3B").courses) == 1 and len(area(r, "3").courses) == 1
    assert area(r, "3").status == "done"


def test_uc_target_drops_csu_only_oral_communication():
    r = run(P1, receiving=BERKELEY)
    assert area(r, "1C").required is False and area(r, "6").required is True
    assert r.summary.missing == 8  # 3A, 3B, 3, 5A, 5B, 5C, 6, 7


# ---- route ----


def make_profile(profile_fake, terms) -> str:
    res = client.post("/profiles", json=PROFILE)
    pid = res.json()["profile"]["id"]
    profile_fake.replace_courses(pid, transcript(terms))
    return pid


def test_route_and_cache(profile_fake, assist_fake):
    pid = make_profile(profile_fake, P1)
    res = client.get(f"/profiles/{pid}/ge")
    assert res.status_code == 200
    body = GeResponse.model_validate(res.json())
    assert body.pattern == "igetc" and body.summary.done == 5
    calls = assist_fake.count("/api/transferability/courses")
    assert calls == 5  # IGETC for 2023–24, 2024–25, 2025–26 and 2026–27; Cal-GETC for 2025–26
    assert client.get(f"/profiles/{pid}/ge?pattern=calgetc").json()["pattern"] == "calgetc"
    again = client.get(f"/profiles/{pid}/ge")
    assert again.json() == res.json()
    assert assist_fake.count("/api/transferability/courses") == calls + 1  # only Cal-GETC 2026–27 was new


def test_route_errors(profile_fake, monkeypatch):
    assert client.get("/profiles/nope/ge").status_code == 404
    pid = make_profile(profile_fake, P3)
    assert client.get(f"/profiles/{pid}/ge?pattern=csuge").status_code == 422

    def down(*a, **kw):
        raise AssistError("timeout")

    monkeypatch.setattr(ge.get_store().client, "transferability_courses", down)
    res = client.get(f"/profiles/{pid}/ge")
    assert res.status_code == 502 and "ASSIST unavailable" in res.json()["detail"]


def test_not_a_community_college(profile_fake):
    res = client.post("/profiles", json={**PROFILE, "sending_institution_id": 39})
    pid = res.json()["profile"]["id"]
    assert client.get(f"/profiles/{pid}/ge").status_code == 404


# ---- lists and cache ----


def test_wrong_list_type_is_an_error():
    with pytest.raises(AssistError):
        lists.parse({"listType": 0, "courseInformationList": []}, "CALGETC", DE_ANZA, 77)


def test_supabase_cache_round_trip(assist_fake):
    rows: dict[str, dict] = {}

    def postgrest(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            row = json.loads(request.content)
            rows[row["key"]] = row
            return httpx.Response(201)
        key = request.url.params["key"].removeprefix("eq.")
        return httpx.Response(200, json=[rows[key]] if key in rows else [])

    db = httpx.MockTransport(postgrest)
    service_client = ge.get_store().client
    first = GeListStore(service_client, "https://db.test/rest/v1", "k", transport=db)
    found = first.get("CALGETC", DE_ANZA, 76)
    assert "CALGETC/113/76" in rows and rows["CALGETC/113/76"]["year_id"] == 76
    before = assist_fake.count("/api/transferability/courses")
    second = GeListStore(service_client, "https://db.test/rest/v1", "k", transport=db)
    assert second.get("CALGETC", DE_ANZA, 76).courses == found.courses
    assert assist_fake.count("/api/transferability/courses") == before  # served from Supabase
    # Empty years aren't stored.
    first.get("CALGETC", DE_ANZA, 74)
    assert "CALGETC/113/74" not in rows


# ---- the plan (/plan?ge=true) ----

def ge_roadmap(terms, transfer_term=None):
    """Planned the way /plan?ge=true does it (test_roadmap.roadmap, plus GE slots)."""
    courses = transcript(terms)
    slots = ge_plan.slots(ge.progress(courses, DE_ANZA, ge.get_store(), None, SJSU))
    profile = Profile(id="p", created_at="", **PROFILE)
    majors, uncurated = planner.resolve_majors(f"{DS},{ECON}", [], "sjsu", planner.load_majors())
    planning = planner.assume_in_progress_passed(courses)
    match = lambda label: get_service().match(DE_ANZA, SJSU, ASSIST_YEAR_ID, label, planning)  # noqa: E731
    return planner.roadmap_for(profile, courses, majors, uncurated, match, today=OCT_2026,
                               transfer_term=transfer_term, ge_slots=slots), slots


def before(r):
    return [s for s in r.semesters if s.phase == "before_transfer"]


def test_ge_slots_follow_missing_areas():
    slots = ge_plan.slots(run([]))
    areas = [s.area for s in slots]
    # 5C rides on 5A; Area 4 needs two courses.
    assert areas == ["Cal-GETC 1A", "Cal-GETC 1B", "Cal-GETC 1C", "Cal-GETC 2", "Cal-GETC 3A", "Cal-GETC 3B",
                     "Cal-GETC 4", "Cal-GETC 4", "Cal-GETC 5A", "Cal-GETC 5B", "Cal-GETC 6"]
    assert "with a lab (5C)" in slots[8].reason and slots[0].units == 5  # De Anza's usual 5 units
    # P1 (IGETC, SJSU): the UC-only language area isn't planned.
    assert "IGETC 6" not in [s.area for s in ge_plan.slots(run(P1))]


def test_area_4_slot_brings_a_second_subject():
    r = run([("Fall 2026", [("ECON", "C2001", 4, "A")])])
    (slot,) = [s for s in ge_plan.slots(r) if s.area == "Cal-GETC 4"]
    assert slot.subjects == ("ECON",) and not any(o.startswith("ECON ") for o in slot.options)


def test_plan_with_ge_no_courses():
    plain = roadmap([])
    r, _ = ge_roadmap([])
    cc = before(r)
    ge_courses = [c for s in cc for c in s.courses if c.ge_area]
    # Planned major courses that are on the lists fill those areas; one area per course.
    reused = {c.code: c.ge_area for c in ge_courses if not c.ge_options}
    assert reused["MATH 1A"] == "Cal-GETC 2"
    area_4 = [code.split()[0] for code, a in reused.items() if a == "Cal-GETC 4"]
    assert len(area_4) == len(set(area_4))  # two subjects, never ECON twice
    open_slots = [c for c in ge_courses if c.ge_options]
    assert {c.code for c in open_slots} >= {"Cal-GETC 1A", "Cal-GETC 1C", "Cal-GETC 3A", "Cal-GETC 3B",
                                             "Cal-GETC 5A", "Cal-GETC 5B", "Cal-GETC 6"}
    assert all(sum(c.units for c in s.courses) <= planner.DEFAULT_CC_UNIT_CAP for s in cc)
    # Every major course from the plain plan is still there.
    assert {c.code for s in before(plain) for c in s.courses} <= {c.code for s in cc for c in s.courses}
    assert planner.term_key(r.earliest_transfer_term) >= planner.term_key(plain.earliest_transfer_term)
    assert r.transfer_term == r.earliest_transfer_term and not r.ge_not_before_transfer


def test_plan_with_ge_and_an_early_transfer_term():
    r, _ = ge_roadmap([], transfer_term="Fall 2028")
    assert all(planner.term_key(s.term) < planner.term_key("Fall 2028") for s in before(r))
    assert r.ge_not_before_transfer and all(a.startswith("Cal-GETC ") for a in r.ge_not_before_transfer)
    assert not any(c.startswith("Cal-GETC") for c in r.not_before_transfer)


def test_fill_ge_respects_the_cap_and_adds_terms():
    slot = planner.GeSlot(area="Cal-GETC 3A", title="Arts", units=5, options=["ARTS 2A"], reason="r")
    cc = [planner.Semester(term="Winter 2027", phase="before_transfer", term_system="quarter", courses=[
        planner.SemesterCourse(code="MATH 1A", title="t", units=12, reason="r", prereqs=[])])]
    terms, left = planner.fill_ge(cc, [slot, slot], ("Winter", 2027), "quarter")
    assert [s.term for s in terms] == ["Winter 2027", "Spring 2027"] and not left
    assert [c.code for c in terms[1].courses] == ["Cal-GETC 3A", "Cal-GETC 3A"]
    terms, left = planner.fill_ge(cc, [slot], ("Winter", 2027), "quarter", limit=planner.term_key("Spring 2027"))
    assert len(terms) == 1 and left == [slot]
    # A planned major course on the list fills the area instead.
    terms, left = planner.fill_ge(cc, [replace(slot, options=["MATH 1A"])], ("Winter", 2027), "quarter")
    assert terms[0].courses[0].ge_area == "Cal-GETC 3A" and len(terms) == 1 and cc[0].courses[0].ge_area is None


def test_plan_route_ge_flag(profile_fake):
    pid = make_profile(profile_fake, P3)
    off = client.get(f"/profiles/{pid}/plan").json()
    assert "ge_pattern" not in off and not any("ge_area" in c for s in off["semesters"] for c in s["courses"])
    on = client.get(f"/profiles/{pid}/plan?ge=true").json()
    assert on["ge_pattern"] == "calgetc"
    assert any(c.get("ge_options") for s in on["semesters"] for c in s["courses"])
    assert client.get(f"/profiles/{pid}/plan?ge=true&ge_pattern=igetc").json()["ge_pattern"] == "igetc"


def test_plan_route_without_ge_lists(profile_fake, monkeypatch):
    pid = make_profile(profile_fake, P3)

    def down(*a, **kw):
        raise AssistError("timeout")

    monkeypatch.setattr(ge.get_store().client, "transferability_courses", down)
    res = client.get(f"/profiles/{pid}/plan?ge=true")
    assert res.status_code == 200 and "ge_pattern" not in res.json()
