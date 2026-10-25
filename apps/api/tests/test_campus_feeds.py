"""Which opportunity feeds a profile reads, from the campus registry by ASSIST id (radar/feeds.py),
with a made-up registry so the rules don't depend on today's data."""

import pytest

from app.models import Profile
from app.services import campuses, planner
from app.services.assist import service as assist_service
from app.services.radar import feeds, sources

UNI, COLLEGE, BARE_UNI, BARE_COLLEGE = 9001, 9002, 9003, 9004
REAL_LOAD = campuses.load  # before the fixture swaps in the made-up registry


def _source(sid: str) -> sources.Source:
    return sources.Source(id=sid, name=sid, kind="localist", url=f"https://{sid}.example.edu/api",
                          homepage=f"https://{sid}.example.edu/", org=sid)


@pytest.fixture(autouse=True)
def registry(monkeypatch):
    reg = campuses.Registry(campuses={
        UNI: campuses.Campus(assist_id=UNI, name="Example State University", short_name="ESU",
                             term_system="semester",
                             opportunities=campuses.Opportunities(feed="esu", sources="x.json")),
        COLLEGE: campuses.Campus(assist_id=COLLEGE, name="Example College", short_name="Example",
                                 term_system="quarter",
                                 opportunities=campuses.Opportunities(feed="exc", sources="y.json")),
        BARE_UNI: campuses.Campus(assist_id=BARE_UNI, name="Bare University", short_name="BU"),
    })
    monkeypatch.setattr(campuses, "load", lambda directory=None: reg)
    monkeypatch.setattr(sources, "load", lambda: sources.SourcesFile(
        campuses={"esu": [_source("esu")], "exc": [_source("exc")]}, shared=[]))
    return reg


def profile(receiving: int, sending: int, stage: str | None = "community_college") -> Profile:
    return Profile(id="p", created_at="", name="T", campus="other", sending_institution_id=sending,
                   receiving_institution_id=receiving, majors=["Data Science, B.S."], goals="g",
                   interests=["ai"], stage=stage)


ROWS = {
    "esu": [{"id": "e1", "campus": "esu", "type": "event", "title": "ESU talk"},
            {"id": "h1", "campus": "esu", "type": "hackathon", "title": "Open hack"}],
    "exc": [{"id": "c1", "campus": "exc", "type": "club", "title": "College club"},
            {"id": "h1", "campus": "esu", "type": "hackathon", "title": "Open hack"}],
}


def test_university_first_then_the_students_own_college():
    assert [(f.key, f.role) for f in feeds.for_profile(profile(UNI, COLLEGE))] == [
        ("esu", "university"), ("exc", "college")]
    assert [f.key for f in feeds.for_profile(profile(UNI, BARE_COLLEGE))] == ["esu"]
    assert [f.key for f in feeds.for_profile(profile(BARE_UNI, COLLEGE))] == ["exc"]


def test_no_feed_for_either_school_reads_nothing():
    assert feeds.for_profile(profile(BARE_UNI, BARE_COLLEGE)) == []
    assert feeds.candidates(profile(BARE_UNI, BARE_COLLEGE), read=lambda key: ROWS[key]) == []


def test_candidates_are_labeled_with_their_campus_and_each_kept_once():
    rows = feeds.candidates(profile(UNI, COLLEGE), with_programs=False, read=lambda key: ROWS[key])
    assert [(r["id"], r["campus_id"]) for r in rows] == [("e1", UNI), ("h1", None), ("c1", COLLEGE)]


def test_where_says_whose_listing_it_is():
    p = profile(UNI, COLLEGE)
    assert feeds.where(p, UNI) == "ESU (the student's target university)"
    assert feeds.where(profile(UNI, COLLEGE, stage="transferred"), UNI) == "ESU (the student's university)"
    assert feeds.where(p, COLLEGE) == "Example (the student's community college)"
    assert feeds.where(p, None) is None


def test_full_plan_and_short_names_come_from_the_registry():
    major = planner.Major(major_label="X, B.S.", university_id=UNI, catalog_year="2025-26", source_url="u",
                          courses={}, groups=[])
    assert planner.full_plan(UNI, [major]) and not planner.full_plan(BARE_UNI, [major])
    assert planner.uncurated_message(UNI, ["Y, B.S."]).startswith("We don't have ESU's Y, B.S. requirements")
    assert planner.uncurated_message(424242, ["Y, B.S."]).startswith("We don't have your university's")


def test_term_system_falls_back_to_the_registry_then_semesters(monkeypatch):
    svc = assist_service.AssistService.__new__(assist_service.AssistService)
    monkeypatch.setattr(svc, "_institutions_by_id", lambda: {UNI: {"termType": 1}})
    assert svc.term_system(UNI) == "quarter"  # ASSIST wins over the registry's "semester"
    assert svc.term_system(COLLEGE) == "quarter"  # ASSIST silent: the registry
    assert svc.term_system(BARE_UNI) == "semester"  # neither: the stated default


def test_registry_rejects_a_mismatched_file_name(tmp_path):
    (tmp_path / "5.json").write_text('{"assist_id": 6, "name": "A", "short_name": "A"}')
    with pytest.raises(ValueError, match="doesn't match"):
        REAL_LOAD(tmp_path)


def test_registry_rejects_two_campuses_sharing_a_feed():
    feed = campuses.Opportunities(feed="same", sources="s.json")
    with pytest.raises(ValueError, match="share an opportunities feed"):
        campuses.Registry(campuses={1: campuses.Campus(assist_id=1, name="A", short_name="A", opportunities=feed),
                                    2: campuses.Campus(assist_id=2, name="B", short_name="B", opportunities=feed)})
