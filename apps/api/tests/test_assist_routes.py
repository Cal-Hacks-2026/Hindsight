import os

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.models import AssistMajorsResponse, MatchResult
from app.services.assist import AssistClient, AssistError, set_service
from app.services.assist.cache import ArticulationCache
from app.services.assist.service import AssistService
from tests.assist_fake import DS_KEY, FakeAssist

client = TestClient(app)

PROFILE = {
    "name": "Test Student",
    "campus": "sjsu",
    "sending_institution_id": 113,
    "receiving_institution_id": 39,
    "majors": ["Data Science, B.S."],
    "goals": "",
    "interests": [],
}


def course(prefix, number, grade="A", term="Fall 2025"):
    return {"prefix": prefix, "number": number, "title": "", "units": 5, "grade": grade,
            "term": term, "confirmed": False}


def profile_with(*courses) -> str:
    pid = client.post("/profiles", json=PROFILE).json()["profile"]["id"]
    if courses:
        client.put(f"/profiles/{pid}/courses", json={"courses": list(courses)})
    return pid


def test_majors_are_real_assist_reports():
    res = client.get("/assist/majors", params={"sending": 113, "receiving": 39, "year": 77})
    majors = AssistMajorsResponse.model_validate(res.json()).majors
    assert {"label": "Data Science, B.S.", "key": DS_KEY} in [m.model_dump() for m in majors]
    assert not any("MOCK" in m.key for m in majors)


def test_majors_for_unknown_pair_is_empty():
    res = client.get("/assist/majors", params={"sending": 113, "receiving": 1, "year": 77})
    assert res.json() == {"majors": []}


def test_match_uses_confirmed_courses_and_real_agreement():
    pid = profile_with(course("MATH", "1A"), course("CIS", "22A"))
    res = client.post(f"/profiles/{pid}/match", json={"major_label": "Data Science, B.S."})
    assert res.status_code == 200
    result = MatchResult.model_validate(res.json())
    assert result.agreement_key == DS_KEY
    by_course = {r.receiving_course: r for r in result.requirements}
    assert by_course["MATH 30 - Calculus I"].status == "satisfied"
    assert by_course["CS 46A - Introduction to Programming"].status == "partial"
    assert "sequence_rule" in by_course["CS 46A - Introduction to Programming"].flags


def test_match_unknown_label_is_404():
    pid = profile_with()
    res = client.post(f"/profiles/{pid}/match", json={"major_label": "Data Science"})
    assert res.status_code == 404


def test_agreement_is_cached_after_first_fetch(assist_fake: FakeAssist):
    pid = profile_with()
    for _ in range(3):
        client.post(f"/profiles/{pid}/match", json={"major_label": "Data Science, B.S."})
    assert assist_fake.count("/api/articulation/Agreements") == 1
    assert assist_fake.count("/api/agreements") == 1


def test_assist_down_is_502():
    import httpx

    def down(request):
        raise httpx.ConnectError("boom")

    set_service(AssistService(AssistClient(transport=httpx.MockTransport(down)), ArticulationCache()))
    res = client.get("/assist/majors", params={"sending": 113, "receiving": 39, "year": 77})
    assert res.status_code == 502
    pid = profile_with()
    assert client.post(f"/profiles/{pid}/match", json={"major_label": "x"}).status_code == 502


@pytest.mark.skipif(not os.getenv("ASSIST_LIVE"), reason="set ASSIST_LIVE=1 to hit assist.org")
def test_live_deanza_to_sjsu_data_science():
    live = AssistClient()
    report = live.major(113, 39, 77, "Data Science, B.S.")
    result = live.agreement(report["key"])
    assert result["name"] == "Data Science, B.S."
    with pytest.raises(AssistError):
        live.major(113, 39, 77, "Data Science")
