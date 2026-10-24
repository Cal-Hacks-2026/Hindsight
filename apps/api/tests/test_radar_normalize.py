"""Radar normalization against a real Cheerio Scraper dataset (trimmed), captured 2026-10-24."""

import json
from datetime import date, datetime, timezone
from pathlib import Path

import pytest

from app.services.radar import extract
from app.services.radar import normalize as n
from app.services.radar import sources

FIXTURE = Path(__file__).parent / "fixtures" / "radar" / "dataset-2026-10-24.json"
SCRAPED = datetime(2026, 10, 24, 9, 0, tzinfo=timezone.utc)


@pytest.fixture
def dataset() -> list[dict]:
    return json.loads(FIXTURE.read_text())


@pytest.fixture
def result(dataset):
    return n.normalize(dataset, SCRAPED)


def by_url(result, url):
    return next(i for i in result.items if i.url == url)


def test_sources_file_is_valid():
    data = sources.load()
    for campus in ("sjsu", "berkeley"):
        assert len(data.campuses[campus]) >= 3
    every = [s for group in data.campuses.values() for s in group] + data.shared
    assert len({s.id for s in every}) == len(every)
    assert all(s.url.scheme == "https" for s in every)
    assert all(callable(extract.load(s.kind)) for s in every)  # every kind has a loadable extractor
    assert sources.by_id("mlh-2027-california") in sources.for_campus("sjsu")
    assert sources.by_id("nope") is None


def test_every_item_matches_section_8_3(result):
    assert result.items
    for item in result.items:
        assert item.url.startswith("https://") and item.title and item.org
        assert item.campus in ("sjsu", "berkeley")
        assert item.scraped_at == SCRAPED.isoformat()
        assert set(item.model_dump()) == {"title", "type", "org", "campus", "starts_at", "deadline",
                                          "url", "description", "tags", "scraped_at"}


def test_localist_uses_event_page_and_next_instance(result):
    item = by_url(result, "https://events.sjsu.edu/event/open-lab-ai-center")
    assert item.title == "Open Lab Hours at AI Center for Civic and Social Good"
    assert item.starts_at == "2026-10-26T09:00:00-07:00"
    assert item.deadline is None  # Localist has no deadlines; we never make one up
    assert item.org == "Dr. Martin Luther King Jr. Library"
    assert "artificial intelligence" in item.tags and "ai" in item.tags  # source topic + source tag
    assert item.campus == "sjsu"


def test_campusgroups_rss(result):
    hack = by_url(result, "https://sammyapp.sjsu.edu/NETS/rsvp?id=379796")
    assert hack.type == "hackathon" and hack.starts_at == "2026-10-24T07:00:00-07:00"
    meeting = next(i for i in result.items if i.title == "Weekly Club Meeting")
    assert meeting.type == "club"  # hosted by a Recognized Student Organization
    assert "recognized student organization" in meeting.tags


def test_livewhale_strips_html_and_keeps_external_event_url(result):
    seminar = next(i for i in result.items if i.title.startswith("Condensed Matter Seminar"))
    assert seminar.starts_at == "2026-10-26T14:30:00-07:00" and seminar.org == "Physics"
    assert seminar.description.startswith("Understanding and controlling") and "<" not in seminar.description
    library = by_url(result, "https://berkeley.libcal.com/event/17661114")
    assert library.description == "" and library.org == "Library"


def test_devpost_open_hackathon_kept_until_deadline(result):
    item = by_url(result, "https://cal-hacks-13-0.devpost.com/")  # started Oct 23, submissions close Oct 25
    assert item.deadline == "2026-10-25T00:00:00-07:00"


def test_devpost_dates_become_start_and_deadline(result):
    item = by_url(result, "https://hackstorm3.devpost.com/")
    assert item.type == "hackathon"
    assert item.starts_at == "2027-01-15T00:00:00-08:00"
    assert item.deadline == "2027-01-17T00:00:00-08:00"
    assert "Location: San Francisco, California, USA." in item.description


def test_mlh_filters_by_location_and_links_the_hackathon_site(result):
    urls = {i.url for i in result.items}
    assert "https://diamondhacks.acmucsd.com/" in urls
    assert "https://hack.sbcs.io/" not in urls  # Stony Brook, NY
    item = by_url(result, "https://calhacks.io/")
    assert item.starts_at == "2026-10-23T17:00:00+00:00" and item.org == "Major League Hacking"
    assert "in-person" in item.tags


def test_ended_items_are_dropped(dataset):
    later = datetime(2026, 10, 26, 0, 0, tzinfo=timezone.utc)
    urls = {i.url for i in n.normalize(dataset, later).items}
    assert "https://calhacks.io/" not in urls  # MLH endsAt 2026-10-25T19:00Z
    assert "https://cal-hacks-13-0.devpost.com/" not in urls  # submissions closed Oct 25
    assert "https://hackstorm3.devpost.com/" in urls


def test_unknown_sources_and_failed_fetches_are_skipped(dataset):
    bad = [dict(dataset[0], sourceId="made-up"), dict(dataset[0], campus="stanford"),
           {"sourceId": "sjsu-devpost", "campus": "sjsu", "#error": True}]
    res = n.normalize(bad, SCRAPED)
    assert res.items == [] and res.skipped == {"unknown_source": 2, "fetch_failed": 1}


def test_dedupes_on_url(dataset):
    res = n.normalize(dataset + dataset, SCRAPED)
    assert len(res.items) == len({i.url for i in res.items}) == len(n.normalize(dataset, SCRAPED).items)
    assert res.skipped["duplicate_url"] == len(res.items)


@pytest.mark.parametrize("text,expected", [
    ("Oct 23 - 25, 2026", (date(2026, 10, 23), date(2026, 10, 25))),
    ("Oct 23 - Nov 02, 2026", (date(2026, 10, 23), date(2026, 11, 2))),
    ("Dec 30, 2026 - Jan 02, 2027", (date(2026, 12, 30), date(2027, 1, 2))),
    ("Mar 27, 2027", (date(2027, 3, 27), date(2027, 3, 27))),
    ("Rolling", None),
    ("Feb 30 - 31, 2027", None),
    (None, None),
])
def test_parse_devpost_dates(text, expected):
    assert n.parse_devpost_dates(text) == expected


def test_parse_when():
    assert n.parse_when("2026-07-29T13:00:00.0000000-07:00").isoformat() == "2026-07-29T13:00:00-07:00"
    assert n.parse_when("2026-10-25").isoformat() == "2026-10-25T00:00:00-07:00"
    assert n.parse_when("2026-10-23T17:00:00Z").isoformat() == "2026-10-23T17:00:00+00:00"
    assert n.parse_when("next Tuesday") is None and n.parse_when("") is None and n.parse_when(None) is None


@pytest.mark.parametrize("title,hints,expected", [
    ("Intro to PyTorch Workshop", set(), "workshop"),
    ("Data Science Fellowship info", set(), "program"),
    ("Now hiring: research assistants", set(), "position"),
    ("Weekly Meeting", {"club"}, "club"),
    ("Weekly Meeting", {"club", "workshop"}, "workshop"),
    ("Anything", {"hackathon"}, "hackathon"),
    ("Life hacks for finals", set(), "hackathon"),
    ("Guest lecture", set(), "event"),
])
def test_infer_type(title, hints, expected):
    assert n.infer_type(title, hints) == expected


def test_rss_xml_bombs_are_refused():
    bomb = ('<?xml version="1.0"?><!DOCTYPE r [<!ENTITY a "aaaaaaaaaa"><!ENTITY b "&a;&a;&a;&a;">]>'
            "<rss><channel><item><title>&b;</title></item></channel></rss>")
    raw = {"sourceId": "sjsu-club-events", "campus": "sjsu", "text": bomb}
    assert n.normalize([raw], SCRAPED).items == []


@pytest.mark.parametrize("url,ok", [
    ("https://events.sjsu.edu/event/x", True),
    ("http://example.com", True),
    ("HTTPS://Example.com/a", True),
    ("javascript:alert(1)", False),
    ("data:text/html,<script>alert(1)</script>", False),
    ("JavaScript://example.com/%0aalert(1)", False),
    ("/relative/path", False),
    ("//example.com/no-scheme", False),
    ("https:///no-host", False),
    ("https://exa mple.com", False),
    ("https://example.com/\njavascript:alert(1)", False),
    ("https://example.com/\x00", False),
    ("https://[::1", False),
    ("ftp://example.com", False),
    (None, False),
])
def test_is_http_url(url, ok):
    assert extract.is_http_url(url) is ok


def test_non_http_urls_are_dropped(dataset):
    raw = json.loads(json.dumps(next(r for r in dataset if r["sourceId"] == "berkeley-devpost")))
    hacks = raw["json"]["hackathons"]
    hacks[0]["url"] = "javascript:alert(document.cookie)"
    res = n.normalize([raw], SCRAPED)
    assert all(extract.is_http_url(i.url) for i in res.items)
    assert "javascript:alert(document.cookie)" not in {i.url for i in res.items}
    assert res.skipped["missing_title_or_url"] >= 1


def test_reports_parsed_counts_and_fetch_failures_per_source(dataset):
    failed = {"sourceId": "berkeley-devpost", "campus": "berkeley", "#error": True}
    res = n.normalize([r for r in dataset if r["sourceId"] != "berkeley-devpost"] + [failed], SCRAPED)
    assert res.parsed["sjsu-events-ai-tech"] > 0
    assert res.fetched["berkeley-devpost"] == res.fetch_failed["berkeley-devpost"] == 1
    assert res.parsed["berkeley-devpost"] == 0 and res.errors == {}


def test_a_broken_extractor_fails_only_its_own_sources(dataset):
    def load(kind):
        if kind == "localist":
            raise extract.ExtractorError("localist.py: syntax error on line 3: invalid syntax")
        return extract.load(kind)

    res = n.normalize(dataset, SCRAPED, load=load)
    assert set(res.errors) == {"sjsu-events-ai-tech"} and "syntax error" in res.errors["sjsu-events-ai-tech"]
    assert res.parsed["sjsu-events-ai-tech"] == 0 and res.skipped["extractor_error"] == 1
    assert res.per_source["berkeley-devpost"] > 0 and res.per_source["sjsu-club-events"] > 0


def test_extractor_exceptions_and_bad_returns_are_contained(dataset):
    def load(kind):
        if kind == "devpost":
            return lambda raw, source: [{"title": "not a Parsed"}]
        if kind == "localist":
            return lambda raw, source: {}["missing"]
        return extract.load(kind)

    res = n.normalize(dataset, SCRAPED, load=load)
    assert "must return a list of Parsed" in res.errors["berkeley-devpost"]
    assert "KeyError" in res.errors["sjsu-events-ai-tech"]
    assert res.per_source["sjsu-club-events"] > 0


def test_extractors_get_a_copy_of_the_source(dataset):
    def load(kind):
        def extract_(raw, source):
            source.tags.append("tampered")  # a list mutation, which the AST guard allows
            return []
        return extract_

    n.normalize(dataset, SCRAPED, load=load)
    assert all("tampered" not in s.tags for s in sources.load().campuses["sjsu"])


@pytest.mark.parametrize("bad", [
    {"starts_at": "2026-10-30"},  # a string where a datetime belongs
    {"deadline": datetime(2026, 10, 30)},  # naive datetime
    {"tags": "ai"},
    {"title": None},
])
def test_malformed_parsed_fields_fail_only_that_source(dataset, bad):
    def load(kind):
        if kind == "localist":
            return lambda raw, source: [extract.Parsed(**{"title": "t", "url": "https://x.org", **bad})]
        return extract.load(kind)

    res = n.normalize(dataset, SCRAPED, load=load)
    assert "must return a list of Parsed" in res.errors["sjsu-events-ai-tech"]
    assert res.per_source["sjsu-club-events"] > 0
