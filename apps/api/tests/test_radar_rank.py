"""Ranking /profiles/{id}/opportunities: deterministic score, Claude reasons, limits."""

from datetime import datetime, timedelta, timezone

import anthropic
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.models import OpportunitiesResponse, Profile
from app.services import claude_limits
from app.services.claude_limits import ClaudeLimiter
from app.services.radar import rank

from .test_contract import make_profile

client = TestClient(app)
NOW = datetime(2026, 10, 24, 9, 0, tzinfo=timezone.utc)

PROFILE = Profile(id="p1", created_at=NOW.isoformat(), name="Test", campus="sjsu",
                  sending_institution_id=113, receiving_institution_id=39,
                  majors=["Data Science, B.S."], goals="Land an ML internship by summer",
                  interests=["ai"])


def row(id, title, *, campus="sjsu", type="event", org="SJSU", days=5, deadline_days=None,
        description="", tags=()):
    return {"id": id, "campus": campus, "type": type, "title": title, "org": org,
            "starts_at": (NOW + timedelta(days=days)).isoformat() if days is not None else None,
            "deadline": (NOW + timedelta(days=deadline_days)).isoformat() if deadline_days is not None else None,
            "url": f"https://events.sjsu.edu/event/{id}", "description": description,
            "tags": list(tags), "scraped_at": NOW.isoformat()}


ROWS = [
    row("ai", "Intro to Generative AI Workshop", type="workshop", tags=["artificial intelligence"]),
    row("ds", "Data Science Career Panel", description="Meet alumni working in analytics."),
    row("bjj", "Brazilian Jiu-Jitsu Practice", type="club", days=1),
    row("old", "Last week's AI talk", days=-3),
    row("closed", "AI fellowship", type="program", days=-10, deadline_days=-1),
    row("hack", "Cal Hacks 13.0 AI track", campus="berkeley", type="hackathon", days=None, deadline_days=1),
    row("hack-dup", "Cal Hacks 13.0 AI track", campus="berkeley", type="hackathon", days=0),
]


def test_relevant_items_outrank_unrelated_ones():
    ranked = [s.row["id"] for s in rank.rank(PROFILE, ROWS, NOW)]
    assert "ai" in ranked and "ds" in ranked
    assert "bjj" not in ranked  # matches nothing the student said
    assert "old" not in ranked and "closed" not in ranked  # past start / past deadline
    assert ranked.count("hack") + ranked.count("hack-dup") == 1  # same title from two sources


def test_generic_type_interest_alone_is_not_a_match():
    profile = PROFILE.model_copy(update={"interests": ["hackathons"], "majors": ["History, B.A."], "goals": ""})
    rows = [row("h1", "Health Hackathon 2027", type="hackathon", days=40),
            row("h2", "History Hackathon", type="hackathon", days=40)]
    assert [s.row["id"] for s in rank.rank(profile, rows, NOW)] == ["h2"]


def test_score_records_what_matched():
    s = rank.score(ROWS[0], rank.ProfileTerms.of(PROFILE), NOW)
    assert s.matched["interests"] == ["ai"]
    assert s.matched["majors"] == ["Data Science, B.S."]
    assert 0 < s.score <= 1


def test_deadline_urgency_raises_score():
    terms = rank.ProfileTerms.of(PROFILE)
    soon = rank.score(row("a", "AI fellowship", type="program", deadline_days=2), terms, NOW)
    later = rank.score(row("b", "AI fellowship", type="program", deadline_days=40), terms, NOW)
    assert soon.score > later.score


def test_terms_avoid_substring_false_positives():
    terms = rank.ProfileTerms.of(PROFILE)
    s = rank.score(row("x", "Fair trade coffee social"), terms, NOW)  # "ai" inside "fair"/"trade"
    assert "interests" not in s.matched


def test_claude_writes_reasons_once_then_cache(monkeypatch):
    calls = []

    def fake_claude(profile, items):
        calls.append([s.row["id"] for s in items])
        return {str(s.row["id"]): f"Fits your AI interest ({s.row['id']})." for s in items}

    monkeypatch.setattr(rank, "ask_claude", fake_claude)
    first = rank.ranked_opportunities(PROFILE, ROWS, NOW)
    assert all(o.reason.startswith("Fits your AI interest") for o in first)
    again = rank.ranked_opportunities(PROFILE, ROWS + [row("new", "AI study jam")], NOW)
    assert calls[1] == ["new"]  # only the new item goes to Claude
    assert {o.id: o.reason for o in again}["ai"] == "Fits your AI interest (ai)."


def test_missing_or_failed_reasons_fall_back_to_computed(monkeypatch):
    monkeypatch.setattr(rank, "ask_claude", lambda p, items: {"ai": "Claude reason."})
    out = {o.id: o.reason for o in rank.ranked_opportunities(PROFILE, ROWS, NOW)}
    assert out["ai"] == "Claude reason."
    assert out["ds"] == "Matches your Data Science major."
    assert "bjj" not in out

    def down(profile, items):
        raise anthropic.APIConnectionError(request=None)

    monkeypatch.setattr(rank, "ask_claude", down)
    monkeypatch.setattr(rank, "reason_cache", rank._ReasonCache())
    assert all(o.reason for o in rank.ranked_opportunities(PROFILE, ROWS, NOW))


def test_daily_cap_spent_means_computed_reasons_not_429(monkeypatch):
    monkeypatch.setattr(claude_limits, "limiter", ClaudeLimiter(per_ip_per_min=10, daily_cap=0))
    out = rank.ranked_opportunities(PROFILE, ROWS, NOW)  # ask_claude would raise if called
    assert out and all(o.reason for o in out)


def test_reason_is_one_line_and_capped():
    assert rank._one_line("Line one\nline two") == "Line one line two"
    assert len(rank._one_line("x" * 500)) == rank.MAX_REASON_CHARS


def test_cache_is_bounded():
    cache = rank._ReasonCache(cap=2)
    for k in "abc":
        cache.put(k, k)
    assert cache.get("a") is None and cache.get("c") == "c"


# ---- route ----


def test_route_returns_ranked_contract(radar_fake, monkeypatch):
    now = datetime.now(timezone.utc)
    radar_fake.rows = [dict(r, starts_at=(now + timedelta(days=2)).isoformat()) for r in ROWS[:3]]
    radar_fake.rows.append(dict(ROWS[0], id="b1", campus="berkeley", url="https://events.berkeley.edu/x"))
    monkeypatch.setattr(rank, "ask_claude", lambda p, items: {})
    pid = make_profile()
    res = client.get(f"/profiles/{pid}/opportunities")
    items = OpportunitiesResponse.model_validate(res.json()).items
    assert [i.id for i in items][0] == "ai"
    assert "b1" not in {i.id for i in items}  # other campus, not a hackathon
    assert all("deadline" not in i for i in res.json()["items"])  # omitted, not null
    assert items == sorted(items, key=lambda i: -i.score)


def test_route_marks_droid_alerts_as_notified(radar_fake, monkeypatch):
    now = datetime.now(timezone.utc)
    radar_fake.rows = [dict(r, starts_at=(now + timedelta(days=2)).isoformat()) for r in ROWS[:3]]
    monkeypatch.setattr(rank, "ask_claude", lambda p, items: {})
    pid = make_profile()
    radar_fake.notified[pid] = {"ai"}
    body = client.get(f"/profiles/{pid}/opportunities").json()
    assert {i["id"]: i["notified"] for i in body["items"]} == {i["id"]: i["id"] == "ai" for i in body["items"]}
    assert "ai" in {i["id"] for i in body["items"]}


def test_route_serves_feed_when_notified_read_fails(radar_fake, monkeypatch):
    from app.services.radar import store

    def down(profile_id):
        raise store.StoreError("Supabase unreachable")

    radar_fake.rows = [dict(ROWS[0], starts_at=(datetime.now(timezone.utc) + timedelta(days=2)).isoformat())]
    monkeypatch.setattr(rank, "ask_claude", lambda p, items: {})
    monkeypatch.setattr(store, "notified_ids", down)
    res = client.get(f"/profiles/{make_profile()}/opportunities")
    assert res.status_code == 200 and [i["notified"] for i in res.json()["items"]] == [False]


def test_route_is_under_claude_per_ip_limit(radar_fake, monkeypatch):
    monkeypatch.setattr(claude_limits, "limiter", ClaudeLimiter(per_ip_per_min=2, daily_cap=100))
    pid = make_profile()
    codes = [client.get(f"/profiles/{pid}/opportunities").status_code for _ in range(3)]
    assert codes == [200, 200, 429]


def test_route_reports_storage_outage(monkeypatch):
    from app.services.radar import store

    def down(campus):
        raise store.StoreNotConfigured("Radar storage is not configured")

    monkeypatch.setattr(store, "candidates", down)
    res = client.get(f"/profiles/{make_profile()}/opportunities")
    assert res.status_code == 503


@pytest.mark.parametrize("label,expected", [
    ("Data Science, B.S.", "data science"),
    ("Economics, B.A.", "economics"),
])
def test_phrase_terms_strip_degree(label, expected):
    assert rank._phrase_terms(label)[0] == expected


def test_plural_interest_matches_singular_text():
    profile = PROFILE.model_copy(update={"interests": ["hackathons"]})
    s = rank.score(row("h", "SpartHill Hackathon", type="hackathon"), rank.ProfileTerms.of(profile), NOW)
    assert s.matched["interests"] == ["hackathons"]


def test_staff_only_events_are_demoted():
    terms = rank.ProfileTerms.of(PROFILE)
    staff = rank.score(row("f", "AI assignment design", type="workshop", tags=["faculty", "staff"]), terms, NOW)
    open_ = rank.score(row("s", "AI assignment design", type="workshop", tags=["faculty", "students"]), terms, NOW)
    assert staff.score < open_.score


def test_faculty_only_items_are_left_out():
    rows = [
        row("cfe", "AI in the classroom", type="workshop", org="Center for Faculty Excellence"),
        row("desc", "AI grading workshop", type="workshop", description="A hands-on session for faculty."),
        row("staff", "AI mixer", description="Open to faculty and staff."),
        row("all", "AI town hall", description="Open to faculty, staff, and students."),
        row("mentors", "AI research with faculty mentors", type="program"),
    ]
    ranked = [s.row["id"] for s in rank.rank(PROFILE, rows, NOW)]
    assert sorted(ranked) == ["all", "mentors"]
