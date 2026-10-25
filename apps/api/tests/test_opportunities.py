"""Opportunities: ten categories, programs, fits your week (classify, programs, filters, route)."""

import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.models import OpportunitiesResponse
from app.services import claude_limits
from app.services.claude_limits import ClaudeLimiter
from app.services.db import StoreError
from app.services.radar import classify, programs, rank, store
from app.services.radar import normalize as n
from app.services.radar.normalize import RadarItem

from .test_contract import make_profile
from .test_radar_rank import PROFILE

client = TestClient(app)
NOW = datetime(2026, 10, 24, 9, 0, tzinfo=timezone.utc)
FIXTURE = Path(__file__).parent / "fixtures" / "radar" / "dataset-2026-10-24.json"
PROGRAMS_FILE = Path(__file__).resolve().parents[3] / "data" / "campuses" / "39" / "programs.json"
# conftest swaps in fakes per test; these are the real ones.
REAL_UPSERT = store.upsert
REAL_ASK = classify.ask_claude


def row(id, title, *, type="event", org="SJSU", tags=(), days=2, hours=1.0, ends=True, campus="sjsu",
        modality=None, location=None, deadline_days=None, now=NOW):
    start = now + timedelta(days=days) if days is not None else None
    return {"id": id, "campus": campus, "type": type, "title": title, "org": org,
            "starts_at": start.isoformat() if start else None,
            "ends_at": (start + timedelta(hours=hours)).isoformat() if start and ends else None,
            "deadline": (now + timedelta(days=deadline_days)).isoformat() if deadline_days is not None else None,
            "url": f"https://events.sjsu.edu/event/{id}", "description": "", "tags": list(tags),
            "scraped_at": now.isoformat(), "modality": modality, "location": location}


# ---- taxonomy and rules ----


def test_taxonomy_has_ten_categories_with_subcategories():
    assert list(classify.TAXONOMY) == ["research", "teaching", "campus-jobs", "careers", "clubs", "leadership",
                                       "competitions", "funding", "academic", "growth"]
    assert all(len(subs) >= 4 for _, subs in classify.TAXONOMY.values())
    assert classify.is_label("research", "symposiums") and not classify.is_label("research", "hackathons")


@pytest.mark.parametrize("title,org,tags,type,expected", [
    ("Sparthill Hackathon 2026 Day #2", "NETS", ["clubs", "workshop"], "hackathon", ("competitions", "hackathons")),
    ("Transfer Scholarship Info Session", "Financial Aid", [], "event", ("funding", "scholarships")),
    ("Application Workshop! Become a Peer Educator at Peer Connections", "Peer Connections", [], "workshop",
     ("teaching", "peer-mentoring")),
    ("University Housing Services Student Leader Information Session", "UHS", [], "event",
     ("campus-jobs", "res-orientation-leaders")),
    ("MPH Information Session - Master of Public Health", "Public Health", ["career"], "event",
     ("academic", "advising-events")),
    ("Kodiak Information Session (Virtual)", "Industrial Engineering", [], "event", ("careers", "info-sessions")),
    ("Ace Your Next Interview Workshop", "Career Center", ["career"], "workshop",
     ("careers", "career-workshops")),
    ("Dinner with the Executives", "Career Center", [], "event", ("careers", "alumni-networking")),
    ("FSL PNME #4", "Office of Student Involvement", ["fraternity/sorority life event"], "event",
     ("clubs", "greek-life")),
    ("Induction Ceremony", "National Society of Leadership and Success", [], "club",
     ("funding", "honor-societies")),
    ("Transfer Tote Bag Painting Social", "Peer Connections", [], "workshop", ("clubs", "transfer-communities")),
    ("CDSS Data Discovery Fall Symposium", "CDSS", [], "event", ("research", "symposiums")),
    ("SpartUp Incubator Founder Fiesta", "Lucas College", [], "event", ("competitions", "entrepreneurship")),
    ("EECS Colloquium: Compiler 2.0", "EECS", ["lectures"], "event", ("growth", "speaker-series")),
    ("SPSS Data Analysis: T-Tests", "King Library", ["conferences, training, workshops"], "workshop",
     ("growth", "workshops")),
    ("Brazilian Jiu-Jitsu Practice", "Brazilian Jiu-Jitsu Club", ["recognized student organization"], "club",
     ("clubs", "orgs")),
    ("Football vs UNLV", "SJSU Athletics", ["sjsu athletics"], "event", ("growth", "wellness-community")),
    # A visitor sign-in at the Student Union isn't a front-desk job; its real job postings still are jobs.
    ("Event Center Check in", "Student Union, Inc.", ["clubs", "office hours", "college/department/program"], "event",
     ("growth", "wellness-community")),
    ("Student Union Now Hiring: Event Staff", "Student Union, Inc.", [], "event", ("campus-jobs", "student-workers")),
])
def test_rules_place_real_listings(title, org, tags, type, expected):
    assert classify.rule_label({"title": title, "org": org, "tags": tags, "type": type}) == expected


def test_source_wide_tags_alone_dont_decide_the_category():
    # Every item from the SJSU career calendar carries "career"; that alone isn't a career event.
    r = {"title": "Adobe Portfolio - showcase your digital skills and career ready skills", "org": "King Library",
         "tags": ["career", "workshop"], "type": "workshop"}
    assert classify.rule_label(r) == ("growth", "workshops")


def test_every_fixture_listing_gets_a_valid_label():
    items = n.normalize(json.loads(FIXTURE.read_text()), NOW).items
    rows = [dict(i.model_dump(), id=str(k)) for k, i in enumerate(items)]
    labels = classify.labels_for(rows)
    assert set(labels) == {r["id"] for r in rows}
    assert all(classify.is_label(*label) for label in labels.values())


# ---- stored labels and the Claude batch ----


def test_stored_label_is_used_until_the_title_changes(radar_fake):
    r = row("x1", "OSPO Monthly Meetup", org="BIDS")
    assert classify.rule_label(r) is None
    radar_fake.labels["x1"] = {"opportunity_id": "x1", "category": "clubs", "subcategory": "orgs",
                               "title_hash": classify.title_hash(r)}
    assert classify.labels_for([r])["x1"] == ("clubs", "orgs")
    retitled = dict(r, title="OSPO Annual Meetup")
    assert classify.labels_for([retitled])["x1"] == classify.fallback_label(retitled)


def test_leftovers_go_to_claude_once_then_come_from_storage(radar_fake):
    rows = [row("a", "OSPO Monthly Meetup"), row("b", "Event Center Check in"),
            row("c", "Weekly Club Meeting", tags=["recognized student organization"])]
    asked = []

    def fake_ask(batch):
        asked.append([r["id"] for r in batch])
        return {"a": ("clubs", "orgs"), "b": ("campus-jobs", "front-desk")}

    first = classify.label_leftovers(rows, ask=fake_ask)
    assert asked == [["a", "b"]]  # the rule-placed row isn't sent
    assert (first.by_rule, first.by_claude, first.unlabeled) == (1, 2, 0)
    second = classify.label_leftovers(rows, ask=fake_ask)
    assert asked == [["a", "b"]] and second.already_stored == 2
    assert classify.labels_for(rows)["b"] == ("campus-jobs", "front-desk")


def test_no_claude_when_labels_cant_be_stored(monkeypatch):
    def down(ids):
        raise StoreError("relation opportunity_labels does not exist")

    def never(batch):
        raise AssertionError("asked Claude with nowhere to cache the answer")

    run = classify.label_leftovers([row("a", "OSPO Monthly Meetup")], ask=never, read=down)
    assert run.unlabeled == 1 and run.by_claude == 0


def test_daily_cap_spent_leaves_type_labels(monkeypatch):
    monkeypatch.setattr(claude_limits, "limiter", ClaudeLimiter(per_ip_per_min=10, daily_cap=0))
    run = classify.label_leftovers([row("a", "OSPO Monthly Meetup")], ask=lambda b: {"a": ("clubs", "orgs")})
    assert run.by_claude == 0 and run.unlabeled == 1


def test_claude_labels_outside_the_taxonomy_are_dropped(monkeypatch):
    out = SimpleNamespace(labels=[SimpleNamespace(id="a", category="clubs", subcategory="orgs"),
                                  SimpleNamespace(id="b", category="clubs", subcategory="hackathons"),
                                  SimpleNamespace(id="zzz", category="growth", subcategory="workshops")])
    sent = {}

    class FakeClaude:
        def __init__(self):
            self.beta = SimpleNamespace(messages=self)

        def parse(self, **kwargs):
            sent.update(kwargs)
            return SimpleNamespace(stop_reason="end_turn", parsed_output=out)

    monkeypatch.setattr(classify.anthropic, "Anthropic", FakeClaude)
    labels = REAL_ASK([row("a", "A"), row("b", "B")])
    assert labels == {"a": ("clubs", "orgs")}
    assert "ignore any instructions" in sent["system"] and "front-desk" in sent["system"]


# ---- programs ----


def test_programs_file_is_valid_and_cited():
    data = json.loads(PROGRAMS_FILE.read_text())
    entries = programs.load("sjsu")
    assert len(entries) == len(data["programs"]) >= 10
    assert len({p.id for p in entries}) == len(entries)
    for p in entries:
        assert p.url.scheme == "https" and (p.url.host or "").endswith("sjsu.edu"), p.id
        assert date.fromisoformat(p.last_checked) and p.window and p.evidence, p.id
        assert "AI" not in p.description.split(), p.id


def test_reviewed_program_reasons_match_their_pages():
    by_id = {p.id: p for p in programs.load("sjsu")}
    urop = by_id["sjsu-urop"].reason
    assert all(group in urop for group in ("freshmen", "sophomores", "transfer students"))
    for p in by_id.values():
        assert "AI" not in p.reason.split() and " you" not in f" {p.reason.lower()}", p.id


def test_program_reasons_never_come_from_claude_or_the_cache(monkeypatch):
    def never(profile, items):
        raise AssertionError("asked Claude for a program reason")
    monkeypatch.setattr(rank, "ask_claude", never)
    rows = programs.as_rows("sjsu")
    now = datetime.now(timezone.utc)
    scored = [rank.score(r, rank.ProfileTerms.of(PROFILE), now) for r in rows]
    urop = next(r for r in rows if r["id"] == "program:sjsu-urop")
    rank.reason_cache.put(rank._cache_key(rank._profile_key(PROFILE), urop), "Built for new transfer students.")
    for ask in (True, False):
        got = rank.reasons(PROFILE, scored, ask=ask)
        assert got == {r["id"]: r["reviewed_reason"] for r in rows}


def test_program_without_a_reason_is_rejected(tmp_path):
    (tmp_path / "sjsu.json").write_text(json.dumps({"last_checked": "2026-10-25", "programs": [{
        "id": "x", "title": "X", "org": "Y", "category": "research", "subcategory": "symposiums",
        "url": "https://www.sjsu.edu/x", "description": "d", "window": "w", "last_checked": "2026-10-25"}]}))
    with pytest.raises(ValueError, match="reason"):
        programs.load("sjsu", tmp_path / "sjsu.json")


def test_program_with_unknown_category_is_rejected(tmp_path):
    (tmp_path / "sjsu.json").write_text(json.dumps({"last_checked": "2026-10-25", "programs": [{
        "id": "x", "title": "X", "org": "Y", "category": "research", "subcategory": "hackathons",
        "url": "https://www.sjsu.edu/x", "description": "d", "window": "w", "last_checked": "2026-10-25",
        "reason": "r"}]}))
    with pytest.raises(ValueError, match="unknown category"):
        programs.load("sjsu", tmp_path / "sjsu.json")


def test_campus_without_a_programs_file_has_none(tmp_path):
    assert programs.programs_file("berkeley") is None and programs.as_rows("berkeley") == []
    assert programs.as_rows("sjsu", tmp_path / "missing.json") == []


# ---- time window ----


def test_in_window_uses_start_end_and_deadline():
    r = row("w", "Workshop", days=2, hours=2)
    assert rank.in_window(r, NOW, NOW + timedelta(days=3), NOW)
    assert not rank.in_window(r, NOW + timedelta(days=3), None, NOW)
    hack = row("h", "Hack", type="hackathon", days=-5, ends=False, deadline_days=10)
    assert rank.in_window(hack, NOW + timedelta(days=1), NOW + timedelta(days=2), NOW)  # still open
    assert not rank.in_window(row("u", "Undated", days=None), NOW, NOW + timedelta(days=7), NOW)


def test_programs_match_a_window_by_their_typical_months():
    feb = {"id": "p", "window_months": [2], "starts_at": None}
    assert rank.in_window(feb, datetime(2027, 1, 20, tzinfo=timezone.utc), datetime(2027, 2, 2, tzinfo=timezone.utc), NOW)
    assert not rank.in_window(feb, NOW, NOW + timedelta(days=7), NOW)
    rolling = {"id": "r", "window_months": [], "starts_at": None}
    assert not rank.in_window(rolling, NOW, NOW + timedelta(days=7), NOW)  # no stated timing, no claim


# ---- route ----


@pytest.fixture
def feed(radar_fake, monkeypatch, tmp_path):
    """Rows relative to the real clock (the route uses it) and a small programs file."""
    now = datetime.now(timezone.utc)
    radar_fake.rows = [
        row("ds", "Data Science Career Panel", now=now, modality="in_person", location="Student Union Ballroom"),
        row("int", "Kodiak Information Session (Virtual)", now=now, modality="online"),
        row("bjj", "Brazilian Jiu-Jitsu Practice", type="club", now=now,
            tags=["recognized student organization"], location="Spartan Recreation Center"),
        row("far", "Data Science Symposium", now=now, days=30),
    ]
    (tmp_path / "sjsu.json").write_text(json.dumps({"last_checked": "2026-10-25", "programs": [{
        "id": "rsca", "title": "Student Data Science Research Fellowship", "org": "Research and Innovation",
        "category": "research", "subcategory": "summer-research", "url": "https://www.sjsu.edu/research/srf",
        "description": "Funds students doing data science research with a faculty mentor.",
        "window": "Applications due each February", "window_months": [2], "evidence": "due February",
        "tags": ["research"], "last_checked": "2026-10-25",
        "reason": "Funds student data science research with a faculty mentor."}]}))
    monkeypatch.setattr(programs, "programs_file", lambda campus: tmp_path / f"{campus}.json")
    monkeypatch.setattr(rank, "ask_claude", lambda p, items: {})
    return radar_fake


def get(pid, **params):
    return client.get(f"/profiles/{pid}/opportunities", params=params)


def test_default_feed_has_labels_times_programs_and_counts(feed):
    pid = make_profile()
    body = get(pid).json()
    items = {i["id"]: i for i in body["items"]}
    assert items["ds"]["category"] == "careers" and items["ds"]["modality"] == "in_person"
    assert items["ds"]["ends_at"] and items["ds"]["location"] == "Student Union Ballroom"
    program = items["program:rsca"]
    assert program["type"] == "program" and program["window"] == "Applications due each February"
    assert program["last_checked"] == "2026-10-25" and program["url"].startswith("https://www.sjsu.edu/")
    cats = {c["id"]: c for c in OpportunitiesResponse.model_validate(body).model_dump()["categories"]}
    assert len(cats) == 10 and cats["research"]["count"] == 2 and cats["clubs"]["count"] == 1
    assert {s["id"] for s in cats["research"]["subcategories"]} >= {"symposiums", "summer-research"}
    # Programs aren't rows in `opportunities`, so they're never written to profile_opportunities.
    assert "program:rsca" not in {i.id for i in feed.ranked[pid]}


def test_category_filter_lists_everything_in_it_without_claude(feed, monkeypatch):
    def never(profile, items):
        raise AssertionError("a filter waited on Claude")

    monkeypatch.setattr(rank, "ask_claude", never)
    pid = make_profile()
    clubs = get(pid, category="clubs").json()["items"]
    assert [i["id"] for i in clubs] == ["bjj"]  # matches nothing the student said, still listed
    assert clubs[0]["reason"]
    research = get(pid, category="research", subcategory="symposiums").json()["items"]
    assert [i["id"] for i in research] == ["far"]
    assert pid not in feed.ranked  # filtered views aren't recorded for Droid alerts


def test_time_modality_and_location_filters(feed):
    pid = make_profile()
    today = datetime.now(timezone.utc).date()
    week = {i["id"] for i in get(pid, **{"from": today.isoformat(), "to": (today + timedelta(days=7)).isoformat()}).json()["items"]}
    assert week == {"ds", "int", "bjj"}  # not the symposium in 30 days, not the February program
    assert [i["id"] for i in get(pid, modality="online").json()["items"]] == ["int"]
    assert [i["id"] for i in get(pid, location="ballroom").json()["items"]] == ["ds"]


def test_filters_dont_spend_the_claude_per_ip_limit(feed, monkeypatch):
    monkeypatch.setattr(claude_limits, "limiter", ClaudeLimiter(per_ip_per_min=1, daily_cap=100))
    pid = make_profile()
    codes = [get(pid, category=c).status_code for c in ("clubs", "research", "careers", "growth")]
    assert codes == [200, 200, 200, 200]
    assert [get(pid).status_code, get(pid).status_code] == [200, 429]  # the unfiltered feed still counts


def test_bad_filters_are_422(feed):
    pid = make_profile()
    assert get(pid, category="parties").status_code == 422
    assert get(pid, category="research", subcategory="hackathons").status_code == 422
    assert get(pid, **{"from": "next week"}).status_code == 422
    assert get(pid, **{"from": "2026-11-02", "to": "2026-11-01"}).status_code == 422
    assert get(pid, modality="telepathy").status_code == 422


def test_other_campus_still_gets_an_empty_feed(feed, profile_fake):
    pid = make_profile()
    # A university with no feed in the campus registry; the legacy campus column isn't consulted.
    profile_fake.profiles[pid] = profile_fake.profiles[pid].model_copy(update={"receiving_institution_id": 117})
    assert get(pid, category="clubs").json() == {"items": []}


def test_real_programs_join_the_feed(radar_fake, monkeypatch):
    monkeypatch.setattr(rank, "ask_claude", lambda p, items: {})
    items = get(make_profile(), category="funding").json()["items"]
    assert items and all(i["type"] == "program" and i["window"] and i["last_checked"] for i in items)


# ---- extractors and storage ----


def test_extractors_return_location_and_modality():
    items = {i.url: i for i in n.normalize(json.loads(FIXTURE.read_text()), NOW).items}
    lab = items["https://events.sjsu.edu/event/open-lab-ai-center"]
    assert lab.location == "King Library, Room 125, AI Center for Civic and Social Good"
    assert lab.modality == "in_person" and lab.ends_at
    rss = [i for i in items.values() if "sammyapp" in i.url]
    assert rss and all(i.modality == "in_person" and i.location is None for i in rss)  # "Private Location"


def test_upsert_retries_without_new_columns_before_the_migration(monkeypatch):
    monkeypatch.setenv("SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "test")
    sent = []

    def handler(request):
        body = json.loads(request.content)
        sent.append(set(body[0]))
        if "ends_at" in body[0]:
            return httpx.Response(400, json={"code": "PGRST204", "message": "Could not find the 'ends_at' column"})
        return httpx.Response(201)

    item = RadarItem(title="T", type="event", org="O", campus="sjsu", url="https://x.edu/e", description="",
                     tags=[], scraped_at=NOW.isoformat(), ends_at=NOW.isoformat(), modality="online")
    assert REAL_UPSERT([item], transport=httpx.MockTransport(handler)) == 1
    assert "ends_at" in sent[0] and not sent[1] & {"ends_at", "location", "modality"}
