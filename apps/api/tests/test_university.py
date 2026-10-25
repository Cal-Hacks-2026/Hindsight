"""Your University guide: sources, Apify pages, Claude's sections, storage, and the route.
No test reaches Apify, Claude, or Supabase."""

import json
import re
from datetime import date, datetime, timezone
from types import SimpleNamespace

import httpx
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.models import UniversityGuide, UniversityGuideResponse
from app.services import campuses
from app.services.university import build, fetch, sources, store, write

client = TestClient(app)

ALLOWED_HOSTS = {"sjsu.edu"}  # the university's own site, which also hosts Associated Students


def page(source_id: str, text: str) -> fetch.Page:
    src = sources.university(39).source(source_id)
    return fetch.Page(source_id=source_id, url=str(src.url), title=src.title, text=text, retrieved_on="2026-10-25")


ORIENTATION = page("sjsu-transfer-orientation", (
    "Spartan Experience for Transfers (Transfer Orientation)\n"
    "All admitted transfer students must attend one orientation session, and participate for the entire "
    "duration of the program.\nOrientation is mandatory and attendance will be recorded."))
STEPS = page("sjsu-transfer-steps", (
    "Step 7 - Register for Classes\nRegistration is a multi-step process.\n"
    "Your nonrefundable Enrollment Deposit of $250 includes your orientation payment."))


@pytest.fixture(autouse=True)
def isolated(monkeypatch, tmp_path):
    """Guides are read from and written to a temp dir; no Supabase; Claude is a script."""
    monkeypatch.setattr(store, "GUIDES_DIR", tmp_path)
    monkeypatch.delenv("SUPABASE_URL", raising=False)
    monkeypatch.delenv("SUPABASE_SERVICE_ROLE_KEY", raising=False)
    store.clear_memory()
    yield
    store.clear_memory()


class FakeClaude:
    def __init__(self, *outputs):
        self.outputs = list(outputs)
        self.requests: list[dict] = []
        self.beta = self
        self.messages = self

    def parse(self, **kwargs):
        self.requests.append(kwargs)
        if not self.outputs:
            raise AssertionError("called Claude more often than the test scripted")
        return SimpleNamespace(stop_reason="end_turn", parsed_output=self.outputs.pop(0))


def claude(monkeypatch, *outputs) -> FakeClaude:
    fake = FakeClaude(*outputs)
    monkeypatch.setattr(write, "_client", lambda: fake)
    return fake


def answer(*items, not_covered=()) -> write._Section:
    return write._Section(items=[write._Item(text=t, source_ids=ids, quote=q) for t, ids, q in items],
                          not_covered=list(not_covered))


# ---- sources ----


def test_every_source_is_an_official_page_and_every_section_has_one():
    data = sources.load()
    section_ids = {s.id for s in data.sections}
    assert section_ids == {"transfer_services", "academics", "getting_around", "housing", "student_life",
                           "first_semester"}
    sjsu = sources.university(39)
    assert sjsu.name == "San José State University"
    ids = [s.id for s in sjsu.sources]
    assert len(ids) == len(set(ids))
    for s in sjsu.sources:
        assert s.url.scheme == "https" and sources.host(str(s.url)) in ALLOWED_HOSTS, s.url
        assert s.sections and set(s.sections) <= section_ids
    for section in data.sections:
        assert sjsu.for_section(section.id), f"{section.id} has no source"


def test_section_titles_are_title_case_with_no_ai_wording():
    for s in sources.load().sections:
        assert all(w[0].isupper() or w in {"and", "of", "to"} for w in s.title.replace("-", " ").split()), s.title
        assert "AI" not in s.title.split()


# ---- fetch ----


def test_apify_input_fetches_exactly_the_listed_pages():
    sjsu = sources.university(39)
    run_input = fetch.build_input(sjsu)
    assert [u["url"] for u in run_input["startUrls"]] == [str(s.url) for s in sjsu.sources]
    assert run_input["startUrls"][0]["userData"] == {"sourceId": sjsu.sources[0].id}
    assert run_input["maxCrawlingDepth"] == 0
    assert "async function pageFunction" in run_input["pageFunction"]


def test_pages_keep_only_usable_on_site_results():
    sjsu = sources.university(39)
    good = "x" * 300
    items = [
        {"sourceId": "sjsu-housing", "loadedUrl": "https://www.sjsu.edu/housing/", "status": 200, "text": good},
        {"sourceId": "sjsu-housing", "loadedUrl": "https://www.sjsu.edu/housing/", "status": 200, "text": "dup" * 100},
        {"sourceId": "sjsu-facts", "loadedUrl": "https://example.com/facts", "status": 200, "text": good},
        {"sourceId": "sjsu-as-baypass", "loadedUrl": "https://www.sjsu.edu/as/", "status": 404, "text": good},
        {"sourceId": "sjsu-parking-maps", "loadedUrl": "https://www.sjsu.edu/parking/maps/", "status": 200,
         "text": "Loading..."},
        {"sourceId": "not-listed", "loadedUrl": "https://www.sjsu.edu/x", "status": 200, "text": good},
    ]
    pages = fetch.pages_from_dataset(items, sjsu, today=date(2026, 10, 25))
    assert [(p.source_id, p.text, p.retrieved_on) for p in pages] == [("sjsu-housing", good, "2026-10-25")]
    assert pages[0].url == "https://www.sjsu.edu/housing/"  # the listed url, not wherever it loaded


# ---- writing and verifying ----


def test_only_items_quoting_a_cited_page_are_kept():
    raw = answer(
        ("Orientation is required for every admitted transfer student.", ["sjsu-transfer-orientation"],
         "Orientation is mandatory and attendance will be recorded."),
        # Typography and spacing differ from the page; the words don't.
        ("The $250 deposit includes orientation.", ["sjsu-transfer-steps"],
         "Your nonrefundable  Enrollment Deposit of $250 includes your orientation payment"),
        ("Orientation lasts two days.", ["sjsu-transfer-orientation"], "Orientation lasts two days."),
        ("Parking is free.", ["sjsu-parking-commuter"], "Parking is free for all students."),
        ("You register at orientation.", [], "Registration is a multi-step process."),
        ("Registration has steps.", ["sjsu-transfer-orientation"], "Registration is a multi-step process."),
    )
    kept, dropped = write.verify(raw, [ORIENTATION, STEPS])
    assert [k.text for k in kept] == ["Orientation is required for every admitted transfer student.",
                                      "The $250 deposit includes orientation."]
    assert [d["why"] for d in dropped] == ["quote not found on a cited page", "unknown source ['sjsu-parking-commuter']",
                                           "no source", "quote not found on a cited page"]


def test_curly_quotes_and_dashes_match_plain_ones():
    p = page("sjsu-transfer-steps", "Check your MySJSU “To Do List” — often.")
    raw = answer(("Check your To Do List.", ["sjsu-transfer-steps"], 'Check your MySJSU "To Do List" - often'))
    kept, _ = write.verify(raw, [p])
    assert len(kept) == 1


def test_write_section_sends_only_that_sections_pages(monkeypatch):
    fake = claude(monkeypatch, answer(
        ("Orientation is required.", ["sjsu-transfer-orientation"], "Orientation is mandatory"),
        not_covered=["transfer student center"]))
    section = next(s for s in sources.load().sections if s.id == "transfer_services")
    written = write.write_section("San José State University", section, [ORIENTATION])
    assert [i.text for i in written.items] == ["Orientation is required."]
    assert written.not_covered == ["transfer student center"]
    sent = fake.requests[0]["messages"][0]["content"]
    assert '<page id="sjsu-transfer-orientation"' in sent and "sjsu-transfer-steps" not in sent
    assert "San José State University" in fake.requests[0]["system"]


def test_a_section_without_pages_makes_no_call(monkeypatch):
    claude(monkeypatch)  # no scripted answers: any call fails the test
    section = sources.load().sections[0]
    assert write.write_section("San José State University", section, []).items == []


def test_input_hash_changes_with_page_text():
    section = sources.load().sections[0]
    a = write.input_hash("SJSU", section, [ORIENTATION])
    assert a == write.input_hash("SJSU", section, [ORIENTATION])
    assert a != write.input_hash("SJSU", section, [page(ORIENTATION.source_id, ORIENTATION.text + " New.")])


# ---- build ----

NOW = datetime(2026, 10, 25, 8, 0, tzinfo=timezone.utc)


def one_item_per_section(n: int) -> list[write._Section]:
    return [answer(("Orientation is required.", ["sjsu-transfer-orientation"], "Orientation is mandatory"))
            if i == 0 else answer(not_covered=["everything"]) for i in range(n)]


def test_build_writes_each_section_once_then_reuses_unchanged_ones(monkeypatch):
    n = len(sources.load().sections)
    fake = claude(monkeypatch, *one_item_per_section(n))
    guide = build.build(39, [ORIENTATION, STEPS], now=NOW)
    # Only sections with pages are sent to Claude; transfer_services and first_semester share these two.
    assert len(fake.requests) == 3  # transfer_services, first_semester, housing (steps page)
    assert guide["last_updated"] == "2026-10-25"
    assert [s["id"] for s in guide["sources"]] == ["sjsu-transfer-orientation"]  # cited ones only
    first = guide["sections"][0]
    assert first["id"] == "transfer_services" and first["items"][0]["quote"] == "Orientation is mandatory"

    fake.outputs, fake.requests = [], []
    again = build.build(39, [ORIENTATION, STEPS], previous=guide, now=NOW)
    assert fake.requests == []
    assert again["sections"] == guide["sections"]


def test_a_failed_section_keeps_the_previous_one(monkeypatch):
    claude(monkeypatch, *one_item_per_section(6))
    guide = build.build(39, [ORIENTATION, STEPS], now=NOW)

    def boom(*a, **kw):
        raise RuntimeError("overloaded")

    monkeypatch.setattr(write, "write_section", boom)
    changed = page(ORIENTATION.source_id, ORIENTATION.text + "\nNew line.")
    again = build.build(39, [changed, STEPS], previous=guide, now=NOW)
    assert again["sections"][0] == guide["sections"][0]


# ---- store and route ----

STORED = {
    "university_id": 39, "university_name": "San José State University", "last_updated": "2026-10-25",
    "generated_at": "2026-10-25T08:00:00+00:00",
    "sections": [
        {"id": "transfer_services", "title": "Transfer Services and Orientation", "opportunity_types": ["program"],
         "input_hash": "h", "not_covered": [],
         "items": [{"text": "Orientation is required.", "source_ids": ["b", "a"], "quote": "q"}]},
        {"id": "housing", "title": "Housing", "opportunity_types": [], "input_hash": "h", "not_covered": [],
         "items": []},
        {"id": "academics", "title": "Academic Culture", "opportunity_types": [], "input_hash": "h",
         "not_covered": [], "items": [{"text": "Semesters.", "source_ids": ["a", "gone"], "quote": "q"}]},
    ],
    "sources": [
        {"id": "a", "title": "A", "publisher": "SJSU", "url": "https://www.sjsu.edu/a", "retrieved_on": "2026-10-25"},
        {"id": "b", "title": "B", "publisher": "SJSU", "url": "https://www.sjsu.edu/b", "retrieved_on": "2026-10-25"},
        {"id": "c", "title": "C", "publisher": "SJSU", "url": "https://www.sjsu.edu/c", "retrieved_on": "2026-10-25"},
    ],
}


def test_contract_drops_build_details_empty_sections_and_uncited_sources():
    guide = store.to_contract(STORED)
    assert [s.id for s in guide.sections] == ["transfer_services", "academics"]
    assert [s.id for s in guide.sources] == ["b", "a"]  # footnote order: first cited first
    assert guide.sections[1].items[0].source_ids == ["a"]
    assert guide.sections[1].opportunity_types is None
    assert "quote" not in guide.model_dump_json()


def test_route_serves_the_guide(tmp_path):
    (tmp_path / "39.json").write_text(json.dumps(STORED))
    res = client.get("/universities/39/guide")
    assert res.status_code == 200
    body = UniversityGuideResponse.model_validate(res.json())
    assert body.available and body.university_name == "San José State University"
    assert [s.title for s in body.guide.sections] == ["Transfer Services and Orientation", "Academic Culture"]


def test_route_says_when_there_is_no_guide():
    res = client.get("/universities/79/guide")
    assert res.status_code == 200
    assert res.json() == {"university_id": 79, "available": False, "university_name": "University of California, Berkeley"}
    assert client.get("/universities/sjsu/guide").status_code == 422
    assert client.get("/universities/0/guide").status_code == 422


def test_unlisted_universities_are_not_looked_up_or_cached(monkeypatch):
    monkeypatch.setenv("SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "k")

    def no_supabase(request):
        raise AssertionError("looked up a university with no sources")

    for uid in range(1000, 1050):
        assert store.get_guide(uid, transport=httpx.MockTransport(no_supabase)) is None
    assert store._memory == {}


def test_newer_cached_guide_wins_over_the_file(monkeypatch, tmp_path):
    (tmp_path / "39.json").write_text(json.dumps(STORED))
    newer = {**STORED, "generated_at": "2026-11-01T00:00:00+00:00", "last_updated": "2026-11-01"}
    seen = []

    def supabase(request: httpx.Request) -> httpx.Response:
        seen.append(request.url.params["key"])
        return httpx.Response(200, json=[{"key": "guide:39", "payload": newer, "fetched_at": "x"}])

    monkeypatch.setenv("SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "k")
    assert store.get_guide(39, transport=httpx.MockTransport(supabase)).last_updated == "2026-11-01"
    assert seen == ["eq.guide:39"]


def test_supabase_down_falls_back_to_the_file(monkeypatch, tmp_path):
    (tmp_path / "39.json").write_text(json.dumps(STORED))
    monkeypatch.setenv("SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "k")
    down = httpx.MockTransport(lambda r: httpx.Response(503))
    assert store.get_guide(39, transport=down).last_updated == "2026-10-25"


def test_numbers_must_appear_on_a_cited_page():
    raw = answer(
        ("The deposit is $250.", ["sjsu-transfer-steps"], "Your nonrefundable Enrollment Deposit of $250"),
        ("The deposit is $300.", ["sjsu-transfer-steps"], "Your nonrefundable Enrollment Deposit of $250"),
        ("Orientation is one session.", ["sjsu-transfer-orientation"], "must attend one orientation session"),
    )
    kept, dropped = write.verify(raw, [ORIENTATION, STEPS])
    assert [k.text for k in kept] == ["The deposit is $250.", "Orientation is one session."]
    assert dropped[0]["why"] == "numbers not on a cited page ['300']"


# ---- the checked-in SJSU guide ----


def test_the_sjsu_guide_file_is_complete_and_cited():
    entry = campuses.get(39)
    path = entry.path(entry.university_guide.guide)
    stored = json.loads(path.read_text())
    listed = {s.id: s for s in sources.university(39).sources}
    guide = store.to_contract(stored)
    assert [s.id for s in guide.sections] == [s.id for s in sources.load().sections]
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", guide.last_updated)
    for section in stored["sections"]:
        assert 3 <= len(section["items"]) <= write.MAX_ITEMS, section["id"]
        for item in section["items"]:
            assert item["source_ids"] and set(item["source_ids"]) <= listed.keys(), item["text"]
            assert item["quote"].strip() and "!" not in item["text"]
            assert not re.search(r"\bAI\b|\bthis (summer|fall|spring)\b", item["text"]), item["text"]
    for s in guide.sources:
        assert s.url == str(listed[s.id].url) and s.publisher == listed[s.id].publisher


def test_the_sjsu_guide_is_served(monkeypatch):
    monkeypatch.setattr(store, "GUIDES_DIR", None)  # the registry's guide file
    body = client.get("/universities/39/guide").json()
    assert body["available"] and body["guide"]["university_name"] == "San José State University"
    cited = {s["id"] for s in body["guide"]["sources"]}
    assert all(set(i["source_ids"]) <= cited for sec in body["guide"]["sections"] for i in sec["items"])
