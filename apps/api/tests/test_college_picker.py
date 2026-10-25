"""Picking where you transfer from and to (I-08), and the ASSIST year fallback (I-17).

The fake ASSIST (assist_fake.py) has De Anza agreements with SJSU for 2026–27, with UC Berkeley
for 2023–24 and 2025–26 only, and with UCLA through 2025–26.
"""

from datetime import date

from fastapi.testclient import TestClient

from app.config import ASSIST_YEAR_ID
from app.main import app
from app.models import AssistInstitutionsResponse, PlanResponse, Profile, ProfileResponse
from app.services import counselor
from app.services.assist import get_service
from app.services.counselor import Student

from .test_contract import PROFILE

client = TestClient(app)
BERKELEY_ECON = "Economics, B.A."


def profile_at(receiving: int, majors: list[str], **kw) -> Profile:
    res = client.post("/profiles", json={**PROFILE, "receiving_institution_id": receiving, "majors": majors, **kw})
    assert res.status_code == 200
    return ProfileResponse.model_validate(res.json()).profile


# ---- the pickers' lists ----


def test_colleges_are_community_colleges_only_by_name_and_cached(assist_fake):
    res = client.get("/assist/colleges")
    assert res.status_code == 200
    colleges = AssistInstitutionsResponse.model_validate(res.json()).institutions
    assert [c.name for c in colleges] == ["Berkeley City College", "De Anza College", "Foothill College"]
    by_id = {c.id: c for c in colleges}
    assert by_id[113].term_system == "quarter" and by_id[51].term_system == "quarter"
    assert by_id[58].term_system == "semester"
    assert all(c.year_id is None and c.full_plan is None for c in colleges)
    client.get("/assist/colleges")
    assert assist_fake.count("/api/institutions") == 1


def test_universities_for_a_college_with_the_year_each_uses(assist_fake):
    res = client.get("/assist/universities", params={"sending": 113})
    assert res.status_code == 200
    unis = AssistInstitutionsResponse.model_validate(res.json()).institutions
    # Universities only (the CC → CC partner is dropped), by name, with the current name.
    assert [(u.id, u.name, u.year_id, u.full_plan) for u in unis] == [
        (39, "San Jose State University", ASSIST_YEAR_ID, True),
        (79, "University of California, Berkeley", 76, False),
        (117, "University of California, Los Angeles", 76, False),
    ]
    client.get("/assist/universities", params={"sending": 113})
    assert assist_fake.count("/api/institutions/113/agreements") == 1


def test_universities_for_a_non_college_is_404_without_calling_assist(assist_fake):
    for sending in (39, 999):
        assert client.get("/assist/universities", params={"sending": sending}).status_code == 404
    assert not any(r.url.path.endswith("/agreements") for r in assist_fake.requests)


def test_picker_lists_share_the_assist_rate_limit():
    from app.services.assist import limits

    for _ in range(limits.PER_IP_PER_MIN):
        assert client.get("/assist/colleges").status_code == 200
    assert client.get("/assist/universities", params={"sending": 113}).status_code == 429


# ---- I-17: the ASSIST year ----


def test_year_falls_back_to_the_latest_published_year():
    service = get_service()
    assert service.year_for(113, 39) == ASSIST_YEAR_ID
    assert service.year_for(113, 79) == 76  # 2025–26
    assert service.year_for(113, 117) == 76
    assert service.year_for(113, 1) == ASSIST_YEAR_ID  # no agreements at all: nothing to fall back to


def test_match_reads_the_fallback_year():
    p = profile_at(79, [BERKELEY_ECON])
    res = client.post(f"/profiles/{p.id}/match", json={"major_label": BERKELEY_ECON})
    assert res.status_code == 200
    body = res.json()
    assert body["agreement_key"].startswith("76/113/to/79/")
    assert all("(2025–2026)" in r["citation"]["label"] for r in body["requirements"])
    calc = next(r for r in body["requirements"] if r["receiving_course"].startswith("MATH 51"))
    # An honors "or" joined to more courses keeps its parentheses, so the planner reads it right.
    assert "(MATH 1A or MATH 1AH) + (MATH 1B or MATH 1BH)" in calc["options"]


# ---- the profile follows the university picked ----


def test_profile_campus_and_names_follow_the_university(agent_fake, monkeypatch):
    monkeypatch.setenv("AGENT_SECRET", "agent-s3cret")
    ucla = profile_at(117, [BERKELEY_ECON], campus="sjsu")  # whatever the client says
    assert ucla.campus == "other"
    assert ucla.sending_institution_name == "De Anza College"
    assert ucla.receiving_institution_name == "University of California, Los Angeles"
    assert agent_fake.started == []  # no Radar sources, so no Droid run
    assert profile_at(79, [BERKELEY_ECON], campus="sjsu").campus == "berkeley"
    assert [s["campus"] for s in agent_fake.started] == ["berkeley"]
    assert client.get(f"/profiles/{ucla.id}").json()["profile"]["receiving_institution_name"].endswith("Los Angeles")


def test_unwatched_campus_never_gets_another_campus_listings(radar_fake):
    radar_fake.rows = [
        {"id": "s1", "campus": "sjsu", "type": "event", "title": "SJSU AI talk", "org": "SJSU",
         "url": "https://events.sjsu.edu/x", "starts_at": None, "deadline": None, "description": ""},
        {"id": "h1", "campus": "sjsu", "type": "hackathon", "title": "Spartan Hack", "org": "Devpost",
         "url": "https://devpost.com/x", "starts_at": None, "deadline": None, "description": ""},
    ]
    ucla = profile_at(117, [BERKELEY_ECON])
    assert client.get(f"/profiles/{ucla.id}/opportunities").json() == {"items": []}


# ---- a university without curated requirements ----


def test_plan_for_a_university_without_curated_requirements_is_before_transfer_only():
    p = profile_at(79, [BERKELEY_ECON])
    assert client.put(f"/profiles/{p.id}/courses", json={"courses": []}).status_code == 200
    res = client.get(f"/profiles/{p.id}/plan")
    assert res.status_code == 200
    body = PlanResponse.model_validate(res.json())
    assert body.full_plan is False and body.uncurated_majors is None
    assert body.semesters and {s.phase for s in body.semesters} == {"before_transfer"}
    assert {s.institution for s in body.semesters} == {"De Anza College"}
    planned = {c.code for s in body.semesters for c in s.courses}
    assert {"ECON 1", "ECON 2", "MATH 1A", "MATH 1B"} <= planned
    assert body.transfer_term and body.transfer_term.startswith("Fall ")
    # A student with no courses starts in a Fall.
    assert body.semesters[0].term.startswith("Fall ")


def test_a_college_course_sharing_a_university_code_isnt_taken_at_the_university():
    # De Anza ECON 1 is not UC Berkeley's ECON 1; ASSIST says what it counts for (partial here).
    p = profile_at(79, [BERKELEY_ECON])
    econ1 = {"prefix": "ECON", "number": "1", "title": "Macro", "units": 5, "grade": "A", "term": "Fall 2025",
             "confirmed": False}
    assert client.put(f"/profiles/{p.id}/courses", json={"courses": [econ1]}).status_code == 200
    body = PlanResponse.model_validate(client.get(f"/profiles/{p.id}/plan").json())
    planned = {c.code for s in body.semesters for c in s.courses}
    assert "ECON 2" in planned


def test_uc_course_codes_are_read():
    from app.services import planner

    assert planner.COURSE_CODE.findall("DATA C8 - Foundations; COMPSCI 61B - Data Structures") == [
        ("DATA", "C8"), ("COMPSCI", "61B")]


def test_sjsu_plan_is_still_the_full_plan():
    p = profile_at(39, ["Data Science, B.S."])
    body = PlanResponse.model_validate(client.get(f"/profiles/{p.id}/plan").json())
    assert body.full_plan is True
    assert {s.phase for s in body.semesters} == {"before_transfer", "after_transfer"}


def test_uc_style_labels_split_without_commas():
    from app.services import planner

    raw = "Economics/B.A.,Statistics and Data Science/B.S."
    assert planner.plan_majors(raw, [], 117, planner.load_majors()) == (
        [], ["Economics/B.A.", "Statistics and Data Science/B.S."], False)


def test_plan_for_no_majors_is_still_an_error():
    p = profile_at(79, [BERKELEY_ECON])
    assert client.get(f"/profiles/{p.id}/plan", params={"majors": ""}).status_code == 404


def test_counselor_knows_the_university_and_claims_no_sjsu_facts():
    profile = Profile(id="p", created_at="", **{**PROFILE, "campus": "berkeley", "receiving_institution_id": 79,
                                                 "majors": [BERKELEY_ECON]},
                      sending_institution_name="De Anza College",
                      receiving_institution_name="University of California, Berkeley")
    s = Student(profile=profile, courses=[], today=date(2026, 10, 24))
    context = counselor.build_context(s)
    assert context["profile"]["university"] == "University of California, Berkeley"
    assert context["profile"]["community_college"] == "De Anza College"
    assert context["profile"]["full_degree_plan"] is False
    assert context["curated_majors_for_planning"] == []
    assert context["assist_agreement_year"] == "2025-26"
    plan = context["plan"]
    assert "error" not in plan and plan["semesters"] == [] and plan["before_transfer"]["terms"]
    assert plan["university_semesters_not_planned"] == (
        "We don't have University of California, Berkeley's full degree requirements yet, so upper-division "
        "courses aren't planned. Check with University of California, Berkeley's advisors.")
    assert "SJSU" not in str(context) and "sjsu" not in str(context)
    assert "Never assume the university is any particular campus" in counselor.SYSTEM


def test_counselor_says_an_unwatched_campus_has_no_opportunities():
    profile = Profile(id="p", created_at="", **{**PROFILE, "campus": "other", "receiving_institution_id": 117},
                      receiving_institution_name="University of California, Los Angeles")
    out = counselor._opportunities(Student(profile=profile, courses=[], today=date(2026, 10, 24)))
    assert out == {"error": "Hindsight doesn't watch University of California, Los Angeles's campus yet, so "
                            "there are no opportunities to show"}


def test_names_fail_fast_while_assist_is_down(assist_fake, monkeypatch):
    service = get_service()
    calls = []

    def down():
        calls.append(1)
        from app.services.assist import AssistError
        raise AssistError("down")

    monkeypatch.setattr(service.client, "institutions", down)
    assert service.institution_name(39) is None and service.institution_name(113) is None
    assert len(calls) == 1
    p = profile_at(117, ["Economics/B.A."])
    assert p.receiving_institution_name is None and p.campus == "other"
