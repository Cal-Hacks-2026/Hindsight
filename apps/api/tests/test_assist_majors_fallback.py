"""MAJORS-FALLBACK: every live majors list is kept (memory, and Supabase's assist_majors_cache when
configured), and a pair that loaded once keeps working while ASSIST is down."""

import datetime
import json

import httpx
from fastapi.testclient import TestClient

from app.main import app
from app.models import AssistMajorsResponse
from app.services.assist import AssistClient, set_service
from app.services.assist.cache import ArticulationCache
from app.services.assist.service import AssistService
from tests.assist_fake import FakeAssist

from .test_assist_routes import profile_with

client = TestClient(app)
PAIR = {"sending": 113, "receiving": 39, "year": 77}


def down(request: httpx.Request) -> httpx.Response:
    raise httpx.ConnectError("boom")


def live_then_down(cache: ArticulationCache) -> None:
    """One live load with `cache`, then a fresh service (as after a restart) whose ASSIST is down."""
    set_service(AssistService(AssistClient(transport=httpx.MockTransport(FakeAssist())), cache))
    res = client.get("/assist/majors", params=PAIR)
    assert res.status_code == 200 and "saved_on" not in res.json()
    set_service(AssistService(AssistClient(transport=httpx.MockTransport(down)), cache))


def test_a_loaded_pair_survives_an_assist_outage():
    cache = ArticulationCache()
    set_service(AssistService(AssistClient(transport=httpx.MockTransport(FakeAssist())), cache))
    live = AssistMajorsResponse.model_validate(client.get("/assist/majors", params=PAIR).json())
    live_then_down(cache)
    res = client.get("/assist/majors", params=PAIR)
    assert res.status_code == 200
    saved = AssistMajorsResponse.model_validate(res.json())
    assert saved.majors == live.majors
    assert saved.saved_on == datetime.datetime.now(datetime.timezone.utc).date().isoformat()


def test_a_pair_never_loaded_keeps_the_error():
    live_then_down(ArticulationCache())
    res = client.get("/assist/majors", params={**PAIR, "receiving": 79})
    assert res.status_code == 502


def test_a_pair_assist_rejects_is_not_answered_from_the_kept_copy():
    live_then_down(ArticulationCache())
    assert client.get("/assist/majors", params={**PAIR, "year": 999}).status_code == 404


def test_matching_uses_the_kept_list_during_an_outage():
    cache = ArticulationCache()
    set_service(AssistService(AssistClient(transport=httpx.MockTransport(FakeAssist())), cache))
    pid = profile_with()
    assert client.post(f"/profiles/{pid}/match", json={"major_label": "Data Science, B.S."}).status_code == 200
    set_service(AssistService(AssistClient(transport=httpx.MockTransport(down)), cache))
    res = client.post(f"/profiles/{pid}/match", json={"major_label": "Data Science, B.S."})
    assert res.status_code == 200


def supabase_cache(*responses: httpx.Response) -> tuple[ArticulationCache, list[httpx.Request]]:
    seen: list[httpx.Request] = []
    queue = list(responses)

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return queue.pop(0)

    return ArticulationCache("https://proj.supabase.co/rest/v1", "sb_secret_test",
                             transport=httpx.MockTransport(handler)), seen


def test_put_majors_upserts_the_pair_into_supabase():
    cache, seen = supabase_cache(httpx.Response(201))
    reports = [{"label": "Data Science, B.S.", "key": "77/113/to/39/Major/x"}]
    cache.put_majors(113, 39, 77, reports)
    (req,) = seen
    assert req.method == "POST" and req.url.path == "/rest/v1/assist_majors_cache"
    assert "resolution=merge-duplicates" in req.headers["prefer"]
    row = json.loads(req.content)
    assert (row["sending_id"], row["receiving_id"], row["year_id"], row["payload"]) == (113, 39, 77, reports)


def test_get_majors_reads_supabase_after_a_restart():
    reports = [{"label": "Economics, B.S.", "key": "77/113/to/39/Major/y"}]
    cache, seen = supabase_cache(httpx.Response(200, json=[
        {"payload": reports, "fetched_at": "2026-10-24T22:10:00+00:00"}]))
    assert cache.get_majors(113, 39, 77) == ("2026-10-24T22:10:00+00:00", reports)
    assert cache.get_majors(113, 39, 77) is not None and len(seen) == 1  # then from memory
    assert seen[0].url.params["receiving_id"] == "eq.39"


def test_a_supabase_failure_never_fails_the_request():
    cache, _ = supabase_cache(httpx.Response(500), httpx.Response(500))
    cache.put_majors(113, 39, 77, [])
    fresh, _ = supabase_cache(httpx.Response(500))
    assert fresh.get_majors(113, 39, 77) is None
