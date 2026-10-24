"""Transcript parsing: deterministic normalization, renumbering flags, and the route.

Claude is stubbed; no network calls.
"""

import asyncio
import json

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.models import CoursesResponse
from app.services import transcript
from app.services.transcript import _Row, academic_year_id, assess, normalize_term, to_course

from .test_contract import make_profile

client = TestClient(app)


def row(prefix="MATH", number="1A", term="Fall 2023", legible=True, **kw) -> _Row:
    return _Row(prefix=prefix, number=number, title=kw.get("title", "Course"), units=kw.get("units", 5),
                grade=kw.get("grade", "A"), term=term, legible=legible)


@pytest.mark.parametrize("raw,term,year_id", [
    ("Fall 2023", "Fall 2023", 74),
    ("winter 2024", "Winter 2024", 74),
    ("Spring  2024", "Spring 2024", 74),
    ("Summer 2024", "Summer 2024", 74),
    ("Fall 2025", "Fall 2025", 76),
])
def test_term_and_academic_year(raw, term, year_id):
    assert normalize_term(raw) == term
    assert academic_year_id(term) == year_id


def test_unparsed_term_keeps_raw_and_flags_low():
    course = to_course(row(term="2023FA"))
    assert course.term == "2023FA" and course.academic_year_id is None and not course.confirmed
    note = assess(course)
    assert note.confidence == "low" and "term_unparsed" in note.flags


def test_number_normalized():
    assert to_course(row(prefix=" stat ", number="C 1000")).number == "C1000"


@pytest.mark.parametrize("prefix,number,term,confidence,flags", [
    ("MATH", "1A", "Fall 2023", "high", []),
    ("STAT", "C1000", "Fall 2025", "high", ["common_course_number"]),
    ("STAT", "C1000", "Fall 2023", "low", ["common_course_number", "ccn_before_rollout"]),
    ("MATH", "C2210", "Fall 2026", "medium", ["common_course_number", "ccn_unrecognized"]),
    ("ENGL", "1A", "Fall 2023", "high", ["pre_ccn_number"]),
    ("ENGL", "1A", "Fall 2025", "medium", ["legacy_number_after_ccn"]),
])
def test_renumbering_flags(prefix, number, term, confidence, flags):
    note = assess(to_course(row(prefix=prefix, number=number, term=term)))
    assert (note.confidence, note.flags) == (confidence, flags)


def test_unclear_scan_is_low():
    note = assess(to_course(row()), legible=False)
    assert note.confidence == "low" and note.flags == ["unclear_scan"]


def test_route_returns_unconfirmed_courses_and_aligned_notes(monkeypatch):
    async def fake_extract(data, media_type):
        assert media_type == "application/pdf"
        return [row(), row(prefix="STAT", number="C1000", term="Fall 2023")]

    monkeypatch.setattr(transcript, "extract_rows", fake_extract)
    res = client.post(f"/profiles/{make_profile()}/transcript",
                      files={"file": ("t.pdf", b"%PDF-1.4", "application/pdf")})
    assert res.status_code == 200
    courses = CoursesResponse.model_validate(res.json()).courses
    assert [c.academic_year_id for c in courses] == [74, 74]
    assert not any(c.confirmed for c in courses)
    # Contract shape unchanged: no extra keys on Course.
    assert set(res.json()["courses"][0]) == set(type(courses[0]).model_fields)
    notes = json.loads(res.headers["x-transcript-notes"])
    assert [n["code"] for n in notes] == ["MATH 1A", "STAT C1000"]
    assert notes[1]["confidence"] == "low"


@pytest.mark.parametrize("content_type,body,status", [
    ("image/heic", b"x", 415),
    ("application/pdf", b"", 422),
])
def test_route_rejects_bad_uploads(content_type, body, status):
    res = client.post(f"/profiles/{make_profile()}/transcript", files={"file": ("t", body, content_type)})
    assert res.status_code == status


def test_route_maps_parser_errors(monkeypatch):
    async def unavailable(data, media_type):
        raise transcript.ParsingUnavailable("not configured")

    monkeypatch.setattr(transcript, "extract_rows", unavailable)
    res = client.post(f"/profiles/{make_profile()}/transcript",
                      files={"file": ("t.png", b"\x89PNG", "image/png")})
    assert res.status_code == 503


def test_route_rejects_oversized_upload(monkeypatch):
    monkeypatch.setattr(transcript, "MAX_UPLOAD_BYTES", 10)
    res = client.post(f"/profiles/{make_profile()}/transcript",
                      files={"file": ("t.pdf", b"%PDF-" + b"x" * 100, "application/pdf")})
    assert res.status_code == 413


ACCEPTED = "PDF, PNG, JPEG or WebP"


@pytest.mark.parametrize("content_type", ["image/gif", "text/plain", "application/msword"])
def test_route_names_the_accepted_upload_types(content_type):
    res = client.post(f"/profiles/{make_profile()}/transcript", files={"file": ("t", b"x", content_type)})
    assert res.status_code == 415 and ACCEPTED in res.json()["detail"]


@pytest.mark.parametrize("content_type", ["image/gif", "text/plain"])
def test_parser_rejects_what_the_route_rejects(content_type):
    """AUDIT I-24: the route and the parser accept the same types."""
    with pytest.raises(transcript.UnsupportedUpload, match=ACCEPTED):
        asyncio.run(transcript.parse_transcript(b"x", content_type))


@pytest.mark.parametrize("content_type", ["application/pdf", "image/png", "image/jpeg", "image/webp"])
def test_route_accepts_every_type_the_parser_reads(monkeypatch, content_type):
    async def fake_parse(data, media_type):
        return [], []

    monkeypatch.setattr(transcript, "parse_transcript", fake_parse)
    res = client.post(f"/profiles/{make_profile()}/transcript", files={"file": ("t", b"x", content_type)})
    assert res.status_code == 200


def test_heic_keeps_its_own_hint():
    res = client.post(f"/profiles/{make_profile()}/transcript", files={"file": ("t", b"x", "image/heic")})
    assert res.status_code == 415 and "export the photo as JPEG or PNG" in res.json()["detail"]
