"""Smoke-test every §10 endpoint against the contract models."""

from fastapi.testclient import TestClient

from app.main import app
from app.models import (
    AgentEventsResponse,
    AgentRunResponse,
    AssistMajorsResponse,
    CounselorResponse,
    CoursesResponse,
    MatchResult,
    OpportunitiesResponse,
    PlanResponse,
    ProfileResponse,
)

client = TestClient(app)

PROFILE = {
    "name": "Test Student",
    "campus": "sjsu",
    "sending_institution_id": 113,
    "receiving_institution_id": 39,
    "majors": ["Data Science, B.S."],
    "goals": "Graduate by Spring 2028",
    "interests": ["ai"],
}


def make_profile() -> str:
    res = client.post("/profiles", json=PROFILE)
    assert res.status_code == 200
    return ProfileResponse.model_validate(res.json()).profile.id


def test_health():
    assert client.get("/health").json() == {"status": "ok", "app": "Hindsight"}


def test_cors_allows_web_origin():
    res = client.options(
        "/health",
        headers={"Origin": "http://localhost:5173", "Access-Control-Request-Method": "GET"},
    )
    assert res.headers["access-control-allow-origin"] == "http://localhost:5173"


def test_profile_roundtrip():
    pid = make_profile()
    res = client.get(f"/profiles/{pid}")
    assert ProfileResponse.model_validate(res.json()).profile.majors == PROFILE["majors"]
    assert client.get("/profiles/nope").status_code == 404


def test_transcript_then_confirm():
    pid = make_profile()
    res = client.post(
        f"/profiles/{pid}/transcript",
        files={"file": ("t.pdf", b"%PDF-1.4", "application/pdf")},
    )
    courses = CoursesResponse.model_validate(res.json()).courses
    assert courses and not any(c.confirmed for c in courses)

    res = client.put(f"/profiles/{pid}/courses", json=res.json())
    assert all(c.confirmed for c in CoursesResponse.model_validate(res.json()).courses)


def test_transcript_rejects_non_pdf_or_image():
    pid = make_profile()
    res = client.post(
        f"/profiles/{pid}/transcript", files={"file": ("t.txt", b"hi", "text/plain")}
    )
    assert res.status_code == 415


def test_match_omits_unset_optionals():
    pid = make_profile()
    res = client.post(f"/profiles/{pid}/match", json={"major_label": "Data Science, B.S."})
    body = res.json()
    result = MatchResult.model_validate(body)
    assert result.major_label == "Data Science, B.S."
    for status in ("satisfied", "partial", "missing", "at_university"):
        assert getattr(result.summary, status) == sum(r.status == status for r in result.requirements)
    # `n?` is only present on n_of rules — never serialized as null.
    assert all("n" not in r for r in body["requirements"] if r["rule"] == "all")


def test_remaining_endpoints():
    pid = make_profile()
    AssistMajorsResponse.model_validate(
        client.get("/assist/majors", params={"sending": 113, "receiving": 39, "year": 77}).json()
    )
    PlanResponse.model_validate(client.get(f"/profiles/{pid}/plan", params={"majors": "a,b"}).json())
    OpportunitiesResponse.model_validate(client.get(f"/profiles/{pid}/opportunities").json())
    CounselorResponse.model_validate(
        client.post(f"/profiles/{pid}/counselor", json={"message": "hi", "history": []}).json()
    )
    run_id = AgentRunResponse.model_validate(
        client.post("/agent/run", json={"campus": "sjsu"}).json()
    ).run_id
    events = AgentEventsResponse.model_validate(
        client.get("/agent/events", params={"run_id": run_id}).json()
    ).events
    assert all(e.run_id == run_id for e in events)
    assert client.post("/webhooks/apify", json={"eventType": "ACTOR.RUN.SUCCEEDED"}).json() == {
        "ok": True
    }
