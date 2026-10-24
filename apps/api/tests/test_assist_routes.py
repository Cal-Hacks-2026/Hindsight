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


def test_majors_for_pair_without_agreements_is_empty():
    res = client.get("/assist/majors", params={"sending": 113, "receiving": 79, "year": 77})
    assert res.json() == {"majors": []}


@pytest.mark.parametrize(("sending", "receiving", "year"), [
    (113, 39, 0), (113, 39, -5), (113, 39, 30), (113, 39, 79), (113, 39, 10**9),  # year range
    (999, 39, 77), (113, 999, 77),  # unknown institutions
    (39, 113, 77), (113, 58, 77),  # wrong direction / CC → CC
])
def test_invalid_majors_queries_are_404_without_calling_assist(assist_fake: FakeAssist, sending, receiving, year):
    res = client.get("/assist/majors", params={"sending": sending, "receiving": receiving, "year": year})
    assert res.status_code == 404
    assert assist_fake.count("/api/agreements") == 0


def test_assist_routes_are_rate_limited_per_ip(assist_fake: FakeAssist):
    from app.services.assist import limits

    params = {"sending": 113, "receiving": 39, "year": 77}
    for _ in range(limits.PER_IP_PER_MIN):
        assert client.get("/assist/majors", params=params).status_code == 200
    res = client.get("/assist/majors", params=params)
    assert res.status_code == 429 and int(res.headers["Retry-After"]) >= 1
    pid = profile_with()
    assert client.post(f"/profiles/{pid}/match", json={"major_label": "Data Science, B.S."}).status_code == 429


def test_majors_cache_is_size_capped(monkeypatch):
    from app.services.assist import service as service_mod

    monkeypatch.setattr(service_mod, "MAX_CACHED_MAJOR_LISTS", 2)
    svc = service_mod.get_service()
    for year in (75, 76, 77):
        svc.majors(113, 39, year)
    assert list(svc._majors) == [(113, 39, 76), (113, 39, 77)]


def test_agreement_memory_cache_is_size_capped(monkeypatch):
    from app.services.assist import cache as cache_mod

    monkeypatch.setattr(cache_mod, "MAX_IN_MEMORY", 2)
    cache = cache_mod.ArticulationCache()
    for k in "abc":
        cache.put(k, {"k": k}, sending_id=1, receiving_id=2, year_id=77, major_label="x")
    assert cache.get("a") is None and cache.get("c") == {"k": "c"}


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
