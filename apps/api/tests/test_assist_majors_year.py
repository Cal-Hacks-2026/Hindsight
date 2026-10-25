"""MAJORS-YEAR: ASSIST can list a year for a pair before it publishes any majors in it. Foothill →
UC Davis lists 2026–27 (77) with no majors yet, and Foothill → UCLA has none for 77 at all; both
have the full list for 2025–26 (76). An empty year falls back up to three years, the response says
which year it used, and everything downstream reads that year. The fake serves ASSIST's recorded
responses (tests/fixtures/assist/majors-51-*.json, agreements-51.json)."""

from fastapi.testclient import TestClient

from app.config import ASSIST_YEAR_ID
from app.main import app
from app.models import AssistInstitutionsResponse, AssistMajorsResponse, ProfileResponse
from app.services.assist import get_service
from tests.assist_fake import DAVIS_DS_KEY, DS_KEY, FakeAssist

from .test_contract import PROFILE

client = TestClient(app)
FOOTHILL, DAVIS, UCLA = 51, 89, 117


def majors(sending: int, receiving: int, year: int) -> AssistMajorsResponse:
    res = client.get("/assist/majors", params={"sending": sending, "receiving": receiving, "year": year})
    assert res.status_code == 200
    return AssistMajorsResponse.model_validate(res.json())


def test_universities_lists_the_year_assist_says_even_when_it_is_empty():
    res = client.get("/assist/universities", params={"sending": FOOTHILL})
    by_id = {u.id: u for u in AssistInstitutionsResponse.model_validate(res.json()).institutions}
    assert by_id[DAVIS].year_id == 77 and by_id[UCLA].year_id == 76


def test_an_empty_year_falls_back_to_the_year_before():
    got = majors(FOOTHILL, DAVIS, 77)
    assert got.year_id == 76
    assert len(got.majors) == 119
    assert all(m.key.startswith("76/51/to/89/") for m in got.majors)
    assert {"label": "Data Science B.S.", "key": DAVIS_DS_KEY} in [m.model_dump() for m in got.majors]


def test_a_client_asking_for_the_current_year_gets_the_latest_published_one():
    got = majors(FOOTHILL, UCLA, ASSIST_YEAR_ID)
    assert got.year_id == 76 and len(got.majors) == 134


def test_a_published_year_is_used_as_is(assist_fake: FakeAssist):
    got = majors(113, 39, 77)
    assert got.year_id == 77
    assert DS_KEY in [m.key for m in got.majors]
    assert assist_fake.count("/api/agreements") == 1


def test_the_fallback_stops_three_years_back(assist_fake: FakeAssist):
    got = majors(113, UCLA, 77)  # the fake has no UCLA majors for any year
    assert got.majors == [] and got.year_id == 77
    years = [r.url.params["academicYearId"] for r in assist_fake.requests if r.url.path == "/api/agreements"]
    assert years == ["77", "76", "75", "74"]


def test_each_year_is_cached_per_pair(assist_fake: FakeAssist):
    majors(FOOTHILL, DAVIS, 77)
    majors(FOOTHILL, DAVIS, 77)
    assert majors(FOOTHILL, DAVIS, 76).year_id == 76
    assert assist_fake.count("/api/agreements") == 2  # 77 (empty) and 76, once each


def test_downstream_reads_the_year_that_has_the_agreement():
    assert get_service().year_for(FOOTHILL, DAVIS) == 76
    res = client.post("/profiles", json={**PROFILE, "sending_institution_id": FOOTHILL,
                                         "receiving_institution_id": DAVIS, "majors": ["Data Science B.S."]})
    pid = ProfileResponse.model_validate(res.json()).profile.id
    match = client.post(f"/profiles/{pid}/match", json={"major_label": "Data Science B.S."})
    assert match.status_code == 200
    body = match.json()
    assert body["agreement_key"] == DAVIS_DS_KEY
    assert body["requirements"] and all("(2025–2026)" in r["citation"]["label"] for r in body["requirements"])
    assert all("year=76" in r["citation"]["url"] for r in body["requirements"])
