"""Profiles + confirmed courses in Supabase (D-004), and the ranked feed in profile_opportunities."""

import json
import logging
import uuid

import httpx
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.models import Course, CreateProfileRequest, RankedOpportunity
from app.services.db import StoreError, StoreNotConfigured
from app.services.profile_store import confirmed_courses as real_confirmed_courses
from app.services.profile_store import create_profile as real_create_profile
from app.services.profile_store import get_profile as real_get_profile
from app.services.profile_store import replace_courses as real_replace_courses
from app.services.radar.store import record_ranked as real_record_ranked

from .test_contract import PROFILE, make_profile
from .test_radar_rank import ROWS

client = TestClient(app)
PID = "7d6c1c1e-2f7a-4d0e-9a51-0c3c1b8e2f10"
COURSE = Course(prefix="MATH", number="1A", title="Calculus", units=5, grade="A", term="Fall 2025",
                confirmed=True)


@pytest.fixture
def supabase_env(monkeypatch):
    monkeypatch.setenv("SUPABASE_URL", "https://proj.supabase.co")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "sb_secret_test")


def recorder(*responses: httpx.Response):
    seen: list[httpx.Request] = []
    queue = list(responses)

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return queue.pop(0)

    return httpx.MockTransport(handler), seen


def test_create_profile_lets_postgres_assign_id(supabase_env):
    row = {**PROFILE, "id": PID, "created_at": "2026-10-24T09:00:00.123+00:00"}
    transport, seen = recorder(httpx.Response(201, json=[row]))
    profile = real_create_profile(CreateProfileRequest(**PROFILE), transport=transport)
    assert profile.id == PID and profile.majors == PROFILE["majors"]
    (req,) = seen
    assert req.method == "POST" and req.url.path == "/rest/v1/profiles"
    assert req.headers["prefer"] == "return=representation"
    assert json.loads(req.content) == PROFILE


def test_get_profile(supabase_env):
    row = {**PROFILE, "id": PID, "created_at": "2026-10-24T09:00:00+00:00"}
    transport, seen = recorder(httpx.Response(200, json=[row]), httpx.Response(200, json=[]))
    assert real_get_profile(PID, transport=transport).name == PROFILE["name"]
    assert real_get_profile(str(uuid.uuid4()), transport=transport) is None
    assert seen[0].url.params["id"] == f"eq.{PID}"


def test_get_profile_malformed_id_is_not_found_without_a_request(supabase_env):
    transport, seen = recorder()
    assert real_get_profile("nope", transport=transport) is None
    assert seen == []


def test_replace_courses_inserts_then_prunes_the_rest(supabase_env):
    transport, seen = recorder(httpx.Response(201), httpx.Response(204))
    real_replace_courses(PID, [COURSE], transport=transport)
    insert, delete = seen
    (row,) = json.loads(insert.content)
    assert row["profile_id"] == PID and row["prefix"] == "MATH" and row["confirmed"] is True
    assert delete.method == "DELETE"
    assert delete.url.params["profile_id"] == f"eq.{PID}"
    assert delete.url.params["id"] == f"not.in.({row['id']})"


def test_replace_courses_with_none_clears_the_profile(supabase_env):
    transport, seen = recorder(httpx.Response(204))
    real_replace_courses(PID, [], transport=transport)
    (delete,) = seen
    assert delete.method == "DELETE" and dict(delete.url.params) == {"profile_id": f"eq.{PID}"}


def test_confirmed_courses_reads_back_contract_shape(supabase_env):
    stored = {**COURSE.model_dump(), "units": 5, "academic_year_id": None}
    transport, seen = recorder(httpx.Response(200, json=[stored]))
    assert real_confirmed_courses(PID, transport=transport) == [COURSE]
    params = seen[0].url.params
    assert params["profile_id"] == f"eq.{PID}" and params["confirmed"] == "is.true"


def test_store_errors(supabase_env, monkeypatch):
    transport, _ = recorder(httpx.Response(500, text="boom"))
    with pytest.raises(StoreError, match="500"):
        real_get_profile(PID, transport=transport)
    monkeypatch.delenv("SUPABASE_URL")
    with pytest.raises(StoreNotConfigured):
        real_create_profile(CreateProfileRequest(**PROFILE))


def test_record_ranked_upserts_without_touching_notified(supabase_env):
    item = RankedOpportunity(id="o1", title="t", type="event", org="o", url="https://x", score=0.5,
                             reason="r")
    transport, seen = recorder(httpx.Response(201))
    assert real_record_ranked(PID, [item], transport=transport) == 1
    (req,) = seen
    assert req.url.params["on_conflict"] == "profile_id,opportunity_id"
    assert req.headers["prefer"] == "resolution=merge-duplicates,return=minimal"
    assert json.loads(req.content) == [{"profile_id": PID, "opportunity_id": "o1", "score": 0.5, "reason": "r"}]
    assert real_record_ranked(PID, [], transport=transport) == 0  # no request for an empty feed


# ---- routes ----


def test_opportunities_route_records_the_feed(radar_fake, monkeypatch):
    from app.services.radar import rank

    radar_fake.rows = ROWS
    monkeypatch.setattr(rank, "ask_claude", lambda profile, items: {})
    pid = make_profile()
    items = client.get(f"/profiles/{pid}/opportunities").json()["items"]
    assert [i.model_dump(exclude_none=True) for i in radar_fake.ranked[pid]] == items


def test_opportunities_route_survives_record_failure(radar_fake, monkeypatch, caplog):
    from app.services.radar import rank, store

    def down(profile_id, items):
        raise StoreError("Supabase unreachable")

    radar_fake.rows = ROWS
    monkeypatch.setattr(rank, "ask_claude", lambda profile, items: {})
    monkeypatch.setattr(store, "record_ranked", down)
    with caplog.at_level(logging.WARNING):
        res = client.get(f"/profiles/{make_profile()}/opportunities")
    assert res.status_code == 200 and res.json()["items"]
    assert "profile_opportunities write failed" in caplog.text


def test_confirmed_courses_are_stored(profile_fake):
    pid = make_profile()
    course = COURSE.model_copy(update={"confirmed": False}).model_dump(exclude_none=True)
    res = client.put(f"/profiles/{pid}/courses", json={"courses": [course]})
    assert res.json() == {"courses": [{**course, "confirmed": True}]}
    assert profile_fake.courses[pid] == [COURSE]


@pytest.mark.parametrize("error,status,detail", [
    (StoreNotConfigured("Storage is not configured (SUPABASE_URL / ...)"), 503, "Storage is not configured"),
    (StoreError('Supabase GET /profiles failed (400): {"code":"22P02","message":"secret detail"}'), 502,
     "Storage is unavailable"),
])
def test_storage_outage_is_reported_without_upstream_detail(monkeypatch, error, status, detail):
    from app.services import profile_store

    def down(*args, **kwargs):
        raise error

    monkeypatch.setattr(profile_store, "create_profile", down)
    monkeypatch.setattr(profile_store, "get_profile", down)
    assert client.post("/profiles", json=PROFILE).status_code == status
    res = client.get(f"/profiles/{PID}")
    assert res.status_code == status and res.json() == {"detail": detail}


# ---- SKELETON: stage and minor ----

SKELETON_PROFILE = {**PROFILE, "stage": "community_college", "minor": "Business"}


def test_create_profile_saves_stage_and_minor(supabase_env):
    row = {**SKELETON_PROFILE, "id": PID, "created_at": "2026-10-25T09:00:00+00:00"}
    transport, seen = recorder(httpx.Response(201, json=[row]))
    profile = real_create_profile(CreateProfileRequest(**SKELETON_PROFILE), transport=transport)
    assert profile.stage == "community_college" and profile.minor == "Business"
    (req,) = seen
    assert json.loads(req.content) == SKELETON_PROFILE
    assert req.url.params["select"].endswith(",stage,minor")


def test_create_profile_before_the_skeleton_migration_drops_stage_and_minor(supabase_env):
    missing = httpx.Response(400, json={"code": "PGRST204", "message": "Could not find the 'minor' column"})
    row = {**PROFILE, "id": PID, "created_at": "2026-10-25T09:00:00+00:00"}
    transport, seen = recorder(missing, httpx.Response(201, json=[row]))
    profile = real_create_profile(CreateProfileRequest(**SKELETON_PROFILE), transport=transport)
    assert profile.id == PID and profile.stage is None
    first, retry = seen
    assert json.loads(retry.content) == PROFILE
    assert "stage" not in retry.url.params["select"]


def test_get_profile_before_the_skeleton_migration(supabase_env):
    missing = httpx.Response(400, json={"code": "42703", "message": "column profiles.stage does not exist"})
    row = {**PROFILE, "id": PID, "created_at": "2026-10-25T09:00:00+00:00"}
    transport, seen = recorder(missing, httpx.Response(200, json=[row]))
    assert real_get_profile(PID, transport=transport).stage is None
    assert len(seen) == 2


def test_other_store_errors_are_not_retried(supabase_env):
    transport, seen = recorder(httpx.Response(500, text="boom"))
    with pytest.raises(StoreError):
        real_get_profile(PID, transport=transport)
    assert len(seen) == 1


def test_profile_without_stage_still_validates():
    assert CreateProfileRequest(**PROFILE).stage is None
    with pytest.raises(ValueError):
        CreateProfileRequest(**{**PROFILE, "stage": "graduated"})
