"""Class schedule: normalization, the two sample fixtures, free blocks, the store, and the routes.

Claude is replaced by the rows it returned for each fixture (fixtures/schedule/recorded/),
and Supabase by an in-memory fake; no network calls unless SCHEDULE_LIVE=1.
"""

import asyncio
import json
import os
from datetime import date
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.models import (
    FreeBlocksResponse,
    PlanResponse,
    ScheduledClass,
    ScheduledPlanResponse,
    ScheduleResponse,
    Semester,
    SemesterCourse,
)
from app.services.schedule import normalize, parser, store, week
from app.services.schedule.parser import _Row, to_class

from .test_contract import make_profile

client = TestClient(app)

FIXTURES = Path(__file__).parent / "fixtures" / "schedule"
PDF, PNG = FIXTURES / "sample-schedule.pdf", FIXTURES / "sample-schedule.png"
# The real store functions, before the autouse fake replaces them.
REAL_REPLACE, REAL_SCHEDULE = store.replace_schedule, store.schedule


def recorded(path: Path) -> list[_Row]:
    return [_Row(**r) for r in json.loads((FIXTURES / "recorded" / f"{path.name}.json").read_text())]


def parsed(path: Path) -> list[ScheduledClass]:
    return [to_class(r) for r in recorded(path)]


def saved(path: Path) -> list[ScheduledClass]:
    return week.validate(parsed(path))


def klass(course="MATH 1B", days=("Mon", "Wed"), start="09:30", end="11:20", mode="in_person", **kw) -> ScheduledClass:
    return ScheduledClass(term=kw.pop("term", "Fall 2026"), course=course, title=kw.pop("title", "Course"),
                          mode=mode, days=list(days), start_time=start, end_time=end,
                          confirmed=kw.pop("confirmed", True), **kw)


class FakeScheduleStore:
    def __init__(self):
        self.rows: dict[str, list[ScheduledClass]] = {}

    def replace_schedule(self, profile_id, rows, transport=None):
        self.rows[profile_id] = list(rows)

    def schedule(self, profile_id, transport=None):
        return list(self.rows.get(profile_id, []))


@pytest.fixture(autouse=True)
def schedule_fake(monkeypatch) -> FakeScheduleStore:
    fake = FakeScheduleStore()
    monkeypatch.setattr(store, "replace_schedule", fake.replace_schedule)
    monkeypatch.setattr(store, "schedule", fake.schedule)
    monkeypatch.setattr(parser, "cache", parser._Cache())
    return fake


@pytest.fixture
def claude(monkeypatch) -> list[str]:
    """Replays the recorded rows for whichever fixture is uploaded; records each call."""
    calls: list[str] = []
    by_bytes = {PDF.read_bytes(): recorded(PDF), PNG.read_bytes(): recorded(PNG)}

    async def fake_extract(data, media_type):
        calls.append(media_type)
        return by_bytes[data]

    monkeypatch.setattr(parser, "extract_rows", fake_extract)
    return calls


# ---- Normalization ----


@pytest.mark.parametrize("raw,expected", [
    ("MW", ["Mon", "Wed"]), ("TTh", ["Tue", "Thu"]), ("TR", ["Tue", "Thu"]), ("M W F", ["Mon", "Wed", "Fri"]),
    ("Mon, Wed", ["Mon", "Wed"]), ("Thursday", ["Thu"]), ("SaSu", ["Sat", "Sun"]), ("WM", ["Mon", "Wed"]),
    ("TBA", []), ("-", []), ("", []), ("9:30", None),
])
def test_days(raw, expected):
    assert normalize.days(raw) == expected


@pytest.mark.parametrize("start,end,expected", [
    ("9:30 AM", "11:20 AM", ("09:30", "11:20", [])),
    ("11:30", "1:20 PM", ("11:30", "13:20", [])),  # start's AM/PM taken so it stays before the end
    ("1:30 PM", "3:20", ("13:30", "15:20", [])),
    ("6:00 PM", "8:15 PM", ("18:00", "20:15", [])),
    ("12:30 pm", "1:45 pm", ("12:30", "13:45", [])),
    ("13:30", "14:45", ("13:30", "14:45", [])),
    ("0830", "0920", ("08:30", "09:20", [])),
    ("8:00", "9:15", ("08:00", "09:15", ["time_assumed"])),
    ("1:30", "2:45", ("13:30", "14:45", ["time_assumed"])),
    ("-", "-", (None, None, [])),
    ("TBA", "TBA", (None, None, [])),
    ("10:00 AM", "9:00 AM", (None, None, ["time_unparsed"])),
    ("noon", "1 PM", (None, None, ["time_unparsed"])),
])
def test_times(start, end, expected):
    assert normalize.times(start, end) == expected


@pytest.mark.parametrize("raw,expected", [
    ("Fall 2026 Quarter", "Fall 2026"), ("2026 Fall Semester", "Fall 2026"),
    ("Winter Quarter 2027", "Winter 2027"), ("spring 2027", "Spring 2027"),
])
def test_terms(raw, expected):
    assert normalize.term(raw) == (expected, [])


def test_unreadable_term_is_kept_and_flagged():
    assert normalize.term("2026FA") == ("2026FA", ["term_unparsed"])


@pytest.mark.parametrize("mode,location,meets,expected", [
    ("In Person", "S44", True, "in_person"),
    ("", "S44", True, "in_person"),
    ("Online Synchronous", "ONLINE", True, "online"),
    ("Online Asynchronous", "ONLINE", False, "asynchronous"),
    ("", "ONLINE", False, "asynchronous"),  # online with no meeting time
    ("Hybrid", "AT 203", True, "hybrid"),
    ("Partially Online", "AT 203", True, "hybrid"),
])
def test_mode(mode, location, meets, expected):
    assert normalize.mode(mode, location, meets) == expected


@pytest.mark.parametrize("a,b", [
    ("MATH D001B", "MATH 1B"), ("math-1b", "MATH 1B"), ("CIS D022C", "CIS 22C"), ("STAT C1000", "STAT C1000"),
])
def test_course_key_matches_local_forms(a, b):
    assert normalize.course_key(a) == normalize.course_key(b)


def test_course_key_keeps_ccn_and_distinct_numbers():
    assert normalize.course_key("STAT C1000") != normalize.course_key("STAT 1000")
    assert normalize.course_key("MATH 1B") != normalize.course_key("MATH 1BH")
    assert normalize.course_key("MATH 10") != normalize.course_key("MATH 1")


def test_dates():
    assert normalize.dates("09/21/2026 - 12/11/2026") == ("2026-09-21", "2026-12-11", [])
    assert normalize.dates("") == (None, None, [])
    assert normalize.dates("12/11/2026 - 09/21/2026") == (None, None, ["dates_unparsed"])


# ---- The two sample fixtures ----


def test_fixtures_are_watermarked():
    assert b"/Title (SAMPLE \\267 TEST DATA" in PDF.read_bytes()  # PDFDocEncoding for "·"
    assert PNG.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"


def test_pdf_fixture_rows():
    rows = parsed(PDF)
    assert [(r.course, r.days, r.start_time, r.end_time, r.mode) for r in rows] == [
        ("MATH D001B", ["Mon", "Wed"], "09:30", "11:20", "in_person"),
        ("CIS D022C", ["Tue", "Thu"], "13:30", "15:20", "hybrid"),
        ("CIS D022C", ["Fri"], "10:30", "12:20", "hybrid"),  # the lab: same CRN, second meeting
        ("ENGL C1000", ["Tue", "Thu"], "09:30", "11:20", "online"),
        ("ECON D001A", [], None, None, "asynchronous"),
    ]
    assert {r.term for r in rows} == {"Fall 2026"}
    assert {(r.start_date, r.end_date) for r in rows} == {("2026-09-21", "2026-12-11")}
    first = rows[0]
    assert (first.crn, first.section, first.professor, first.units, first.location) == \
        ("40112", "01", "Test Instructor A", 5.0, "S44")
    assert not any(r.confirmed for r in rows)
    assert all(r.flags == [] for r in rows)


def test_png_fixture_rows():
    rows = parsed(PNG)
    assert [(r.course, r.days, r.start_time, r.end_time, r.mode) for r in rows] == [
        ("MATH D001C", ["Tue", "Thu"], "11:30", "13:20", "in_person"),
        ("CIS D035A", ["Mon", "Wed"], "18:00", "20:15", "in_person"),
        ("STAT C1000", [], None, None, "asynchronous"),
        ("PHYS D004A", ["Mon", "Wed", "Fri"], "08:30", "09:20", "hybrid"),
    ]
    assert {r.term for r in rows} == {"Winter 2027"}
    assert all(r.start_date is None for r in rows)


def test_tba_in_person_class_is_flagged():
    row = to_class(_Row(term="Fall 2026", crn="1", course="MATH 1B", title="Calculus", section="", professor="",
                        units="5", location="S44", instruction_mode="In Person", days="TBA", start_time="TBA",
                        end_time="TBA", dates="", legible=False))
    assert row.mode == "in_person" and row.days == [] and row.flags == ["unclear_scan", "no_meeting_time"]
    assert row.section is None and row.professor is None


def test_term_totals_count_a_lecture_and_lab_once():
    totals = week.term_totals(saved(PDF) + saved(PNG))
    assert [(t.term, t.units, t.classes) for t in totals] == [("Fall 2026", 18.5, 4), ("Winter 2027", 20.5, 4)]


# ---- Validation ----


def test_validate_confirms_and_cleans():
    (row,) = week.validate([klass(days=("Wed", "Mon", "Mon"), flags=["time_assumed"], confirmed=False)])
    assert row.confirmed and row.flags is None and row.days == ["Mon", "Wed"]


def test_validate_clears_async_times():
    (row,) = week.validate([klass(mode="asynchronous")])
    assert (row.days, row.start_time, row.end_time) == ([], None, None)


@pytest.mark.parametrize("kw,message", [
    ({"start": "11:00", "end": "10:00"}, "end time must be after"),
    ({"start": "9:30", "end": "11:20"}, "times must look like"),
    ({"start": "09:30", "end": None}, "both a start and an end"),
    ({"course": " "}, "course and term are required"),
    ({"start_date": "2026-12-11", "end_date": "2026-09-21"}, "end date must be after"),
    ({"start_date": "12/11/2026"}, "dates must look like"),
])
def test_validate_rejects(kw, message):
    with pytest.raises(week.InvalidSchedule, match=message):
        week.validate([klass(**kw)])


# ---- Free blocks ----


def blocks(response: FreeBlocksResponse, day: str) -> list[tuple[str, str]]:
    (d,) = [d for d in response.days if d.day == day]
    return [(b.start, b.end) for b in d.blocks]


def test_free_blocks_for_the_pdf_fixture():
    res = week.free_blocks(saved(PDF), date(2026, 10, 28))  # a Wednesday
    assert res.week == "2026-10-26" and (res.day_start, res.day_end) == ("07:00", "22:00")
    assert [d.day for d in res.days] == ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    assert [d.date for d in res.days][::6] == ["2026-10-26", "2026-11-01"]
    assert blocks(res, "Mon") == [("07:00", "09:30"), ("11:20", "22:00")]
    assert blocks(res, "Tue") == [("07:00", "09:30"), ("11:20", "13:30"), ("15:20", "22:00")]
    assert blocks(res, "Fri") == [("07:00", "10:30"), ("12:20", "22:00")]
    assert blocks(res, "Sat") == [("07:00", "22:00")]  # the asynchronous class blocks nothing
    assert res.days[0].blocks[0].minutes == 150


def test_free_blocks_outside_class_dates_are_open():
    res = week.free_blocks(saved(PDF), date(2027, 1, 6))  # after the Fall classes end
    assert all(blocks(res, d.day) == [("07:00", "22:00")] for d in res.days)


def test_free_blocks_clip_merge_and_drop_short_gaps():
    rows = [klass(start="06:00", end="08:00"), klass(start="08:10", end="09:00"),
            klass(start="08:30", end="10:00"), klass(start="21:00", end="23:00")]
    res = week.free_blocks(rows, date(2026, 10, 26))
    assert blocks(res, "Mon") == [("10:00", "21:00")]  # 8:00–8:10 is under 15 minutes


# ---- Planned courses ----


def test_scheduled_plan_courses_match_local_codes():
    semesters = [
        Semester(term="Fall 2026", courses=[SemesterCourse(code="MATH 1B", title="Calculus", units=5, reason="", prereqs=[]),
                                            SemesterCourse(code="MATH 1C", title="Calculus", units=5, reason="", prereqs=[])]),
        Semester(term="Winter 2027", courses=[SemesterCourse(code="CIS 22C", title="Data", units=4.5, reason="", prereqs=[])]),
    ]
    marked = week.scheduled_plan_courses(semesters, saved(PDF))
    assert [(c.code, c.planned_term, c.scheduled_term, c.crn) for c in marked] == [
        ("MATH 1B", "Fall 2026", "Fall 2026", "40112"),
        ("CIS 22C", "Winter 2027", "Fall 2026", "40387"),
    ]


# ---- Store (Supabase via PostgREST, mocked) ----


def test_store_round_trip(monkeypatch):
    monkeypatch.setenv("SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "test-key")
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.method == "GET":
            return httpx.Response(200, json=[{
                "term": "Fall 2026", "course": "MATH D001B", "title": "Calculus II", "crn": "40112", "section": "01",
                "professor": None, "units": "5.0", "location": "S44", "mode": "in_person", "days": ["Mon", "Wed"],
                "start_time": "09:30:00", "end_time": "11:20:00", "start_date": "2026-09-21", "end_date": None}])
        return httpx.Response(201 if request.method == "POST" else 204)

    transport = httpx.MockTransport(handler)
    REAL_REPLACE("p1", saved(PDF)[:2], transport=transport)
    post, delete = requests
    body = json.loads(post.content)
    assert [r["position"] for r in body] == [0, 1] and "flags" not in body[0] and "confirmed" not in body[0]
    assert body[0]["profile_id"] == "p1" and body[0]["days"] == ["Mon", "Wed"]
    assert delete.method == "DELETE" and "not.in." in delete.url.params["id"]

    (row,) = REAL_SCHEDULE("p1", transport=transport)
    assert (row.start_time, row.end_time, row.units, row.confirmed) == ("09:30", "11:20", 5.0, True)
    assert requests[-1].url.params["order"] == "position"


# ---- Routes ----


def test_upload_pdf_then_confirm_then_read(claude, schedule_fake):
    pid = make_profile()
    res = client.post(f"/profiles/{pid}/schedule", files={"file": ("s.pdf", PDF.read_bytes(), "application/pdf")})
    assert res.status_code == 200, res.text
    upload = ScheduleResponse.model_validate(res.json())
    assert len(upload.rows) == 5 and not any(r.confirmed for r in upload.rows) and upload.terms is None
    assert schedule_fake.rows == {}  # nothing saved before the student confirms
    assert "start_time" not in res.json()["rows"][4]  # nulls omitted, as on other routes

    res = client.put(f"/profiles/{pid}/schedule", json={"rows": res.json()["rows"]})
    assert res.status_code == 200, res.text
    assert all(r.confirmed for r in schedule_fake.rows[pid])

    got = ScheduleResponse.model_validate(client.get(f"/profiles/{pid}/schedule").json())
    assert [r.course for r in got.rows] == [r.course for r in upload.rows]
    assert [(t.term, t.units, t.classes) for t in got.terms] == [("Fall 2026", 18.5, 4)]


def test_upload_png(claude):
    res = client.post(f"/profiles/{make_profile()}/schedule",
                      files={"file": ("s.png", PNG.read_bytes(), "image/png")})
    assert res.status_code == 200, res.text
    assert [r["course"] for r in res.json()["rows"]] == ["MATH D001C", "CIS D035A", "STAT C1000", "PHYS D004A"]
    assert claude == ["image/png"]


def test_same_file_twice_calls_claude_once(claude, fresh_claude_limiter):
    pid = make_profile()
    for _ in range(2):
        res = client.post(f"/profiles/{pid}/schedule", files={"file": ("s.pdf", PDF.read_bytes(), "application/pdf")})
        assert res.status_code == 200
    assert claude == ["application/pdf"]


def test_empty_schedule_reads_as_empty():
    res = client.get(f"/profiles/{make_profile()}/schedule")
    assert res.status_code == 200 and res.json() == {"rows": [], "terms": []}


@pytest.mark.parametrize("name,data,media,status", [
    ("s.txt", b"hello", "text/plain", 415),
    ("s.heic", b"x", "image/heic", 415),
    ("s.pdf", b"", "application/pdf", 422),
])
def test_upload_rejects(claude, name, data, media, status):
    res = client.post(f"/profiles/{make_profile()}/schedule", files={"file": (name, data, media)})
    assert res.status_code == status
    assert claude == []


def test_upload_with_no_classes_is_422(monkeypatch):
    async def none(data, media_type):
        return []

    monkeypatch.setattr(parser, "extract_rows", none)
    res = client.post(f"/profiles/{make_profile()}/schedule", files={"file": ("s.pdf", b"%PDF", "application/pdf")})
    assert res.status_code == 422 and "No classes" in res.json()["detail"]


def test_unknown_profile_is_404(claude):
    missing = "00000000-0000-0000-0000-000000000000"
    assert client.get(f"/profiles/{missing}/schedule").status_code == 404
    assert client.put(f"/profiles/{missing}/schedule", json={"rows": []}).status_code == 404
    assert client.post(f"/profiles/{missing}/schedule",
                       files={"file": ("s.pdf", PDF.read_bytes(), "application/pdf")}).status_code == 404
    assert claude == []


def test_put_rejects_bad_rows_plainly():
    bad = klass(start="11:00", end="10:00").model_dump(exclude_none=True)
    res = client.put(f"/profiles/{make_profile()}/schedule", json={"rows": [bad]})
    assert res.status_code == 422 and res.json()["detail"] == "Row 1 (MATH 1B): the end time must be after the start time"


def test_free_blocks_route(schedule_fake):
    pid = make_profile()
    schedule_fake.rows[pid] = saved(PDF) + saved(PNG)
    res = client.get(f"/profiles/{pid}/schedule/free-blocks", params={"week": "2026-10-28"})
    assert res.status_code == 200, res.text
    fall = FreeBlocksResponse.model_validate(res.json())
    # Winter rows have no printed dates, so they count every week unless a term is chosen.
    assert blocks(fall, "Mon") == [("07:00", "08:30"), ("11:20", "18:00"), ("20:15", "22:00")]
    only_fall = FreeBlocksResponse.model_validate(client.get(
        f"/profiles/{pid}/schedule/free-blocks", params={"week": "2026-10-28", "term": "fall 2026"}).json())
    assert blocks(only_fall, "Mon") == [("07:00", "09:30"), ("11:20", "22:00")]
    assert client.get(f"/profiles/{pid}/schedule/free-blocks", params={"week": "Oct 28"}).status_code == 422
    assert client.get(f"/profiles/{pid}/schedule/free-blocks").status_code == 422


def test_planned_route_marks_scheduled_courses(schedule_fake, monkeypatch):
    from app.routers import profiles

    pid = make_profile()
    calls = []

    # No defaults: the route must pass every argument (plan()'s own defaults are Query objects).
    def fake_plan(profile_id, *, majors, transfer_term, start_term, ge, ge_pattern):
        calls.append((majors, transfer_term, start_term, ge, ge_pattern))
        return PlanResponse(semesters=[Semester(term="Winter 2027", courses=[
            SemesterCourse(code="MATH 1C", title="Calculus III", units=5, reason="", prereqs=[]),
            SemesterCourse(code="MATH 2A", title="Differential Equations", units=5, reason="", prereqs=[])])])

    monkeypatch.setattr(profiles, "plan", fake_plan)
    res = client.get(f"/profiles/{pid}/schedule/planned")
    assert res.json() == {"courses": []} and calls == []  # no schedule: the plan isn't built

    schedule_fake.rows[pid] = saved(PNG)
    res = client.get(f"/profiles/{pid}/schedule/planned", params={"transfer_term": "Fall 2028"})
    marked = ScheduledPlanResponse.model_validate(res.json()).courses
    assert [(c.code, c.scheduled_term, c.crn) for c in marked] == [("MATH 1C", "Winter 2027", "10234")]
    assert calls == [(None, "Fall 2028", None, False, None)]
    client.get(f"/profiles/{pid}/schedule/planned", params={"ge": "true", "ge_pattern": "igetc"})
    assert calls[-1] == (None, None, None, True, "igetc")


# ---- Live (opt-in): one real Claude call per fixture ----


@pytest.mark.skipif(not os.getenv("SCHEDULE_LIVE"), reason="set SCHEDULE_LIVE=1 to call Claude")
@pytest.mark.parametrize("path,media,expected", [
    (PDF, "application/pdf", {"MATH D001B", "CIS D022C", "ENGL C1000", "ECON D001A"}),
    (PNG, "image/png", {"MATH D001C", "CIS D035A", "STAT C1000", "PHYS D004A"}),
])
def test_live_fixture_parse(path, media, expected):
    rows = asyncio.run(parser.parse_schedule(path.read_bytes(), media))
    assert {r.course for r in rows} == expected
