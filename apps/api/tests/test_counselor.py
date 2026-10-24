"""POST /profiles/{id}/counselor: grounding, tools, citations, advisor questions, limits."""

import json
import os
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace

import anthropic
import httpx2
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.models import ChatMessage, Citation, CounselorResponse, Profile
from app.services import claude_limits, counselor, mocks
from app.services.assist import AssistError
from app.services.claude_limits import ClaudeLimiter
from app.services.counselor import Sources, Student, _Answer
from app.services.db import StoreError
from app.services.radar import store as radar_store

client = TestClient(app)
TODAY = date(2026, 10, 24)
DS, ECON = "Data Science, B.S.", "Economics, B.S."
DEMO_QUESTION = "Can I graduate by Spring 2028 if I add Econ?"

PROFILE = {
    "name": "Atishay", "campus": "sjsu", "sending_institution_id": 113, "receiving_institution_id": 39,
    "majors": [DS], "goals": "Graduate by Spring 2028", "interests": ["ai"],
}


def courses():
    return [c.model_copy(update={"confirmed": True}) for c in mocks.transcript_courses()]


def make_student() -> str:
    pid = client.post("/profiles", json=PROFILE).json()["profile"]["id"]
    client.put(f"/profiles/{pid}/courses", json={"courses": [c.model_dump() for c in courses()]})
    return pid


def ask(pid: str, message: str = DEMO_QUESTION, history: list | None = None):
    return client.post(f"/profiles/{pid}/counselor", json={"message": message, "history": history or []})


def student(**kw) -> Student:
    profile = Profile(id="p1", created_at="2026-10-24T00:00:00Z", **{**PROFILE, **kw})
    return Student(profile=profile, courses=courses(), today=TODAY)


# ---- scripted Claude ----


def tool_call(name, args, id="t1"):
    return lambda req: SimpleNamespace(
        stop_reason="tool_use", parsed_output=None,
        content=[SimpleNamespace(type="tool_use", id=id, name=name, input=args)])


def final(write):
    """`write(req)` → (reply, advisor_question)."""
    def step(req):
        reply, question = write(req)
        return SimpleNamespace(stop_reason="end_turn", content=[],
                               parsed_output=_Answer(reply=reply, advisor_question=question))
    return step


def student_data(req) -> dict:
    for m in req["messages"]:
        if m["role"] == "user" and isinstance(m["content"], list) and m["content"][0].get("type") == "text":
            text = m["content"][0]["text"]
            if text.startswith("<student_data>"):
                return json.loads(text.removeprefix("<student_data>").removesuffix("</student_data>"))
    raise AssertionError("no student_data in request")


def last_tool_result(req) -> dict:
    (result,) = req["messages"][-1]["content"]
    assert result["type"] == "tool_result"
    return json.loads(result["content"])


def source_of(match: dict, course_prefix: str) -> str:
    return next(r["source"] for r in match["requirements"] if r["receiving_course"].startswith(course_prefix))


# ---- the demo question ----


def test_demo_question_runs_the_tools_and_cites_computed_results(counselor_claude, radar_fake,
                                                                 fresh_claude_limiter):
    soon = (datetime.now(timezone.utc) + timedelta(days=3)).isoformat()
    radar_fake.rows.append({"id": "o1", "campus": "sjsu", "type": "program", "title": "AI Fellows Program",
                            "org": "SJSU AI Club", "starts_at": None, "deadline": soon,
                            "url": "https://sjsu.edu/ai-fellows", "description": "", "tags": ["ai"],
                            "scraped_at": soon})
    pid = make_student()

    def answer(req):
        econ = last_tool_result(req)
        ds = student_data(req)["match_results"][0]
        return (f"Can't tell yet. ECON 1B is still missing [{source_of(econ, 'ECON 1B')}], and your Calculus "
                f"is done [{source_of(ds, 'MATH 31')}][S999].", None)

    counselor_claude.steps += [
        tool_call("plan_with_majors", {"majors": [DS, ECON], "target_term": "Spring 2028"}),
        tool_call("match_major", {"major_label": ECON}, id="t2"),
        final(answer),
    ]
    res = ask(pid)
    assert res.status_code == 200, res.text
    body = CounselorResponse.model_validate(res.json())

    # Grounded in this student's computed data.
    data = student_data(counselor_claude.requests[0])
    assert data["profile"]["majors"] == [DS]
    assert {c["code"] for c in data["confirmed_courses"]} >= {"MATH 1A", "ECON 1"}
    assert data["match_results"][0]["summary"] == {"satisfied": 3, "partial": 2, "missing": 3, "at_university": 0}
    assert data["plan"]["semesters"] and data["plan"]["covers"] == counselor.PLAN_COVERS
    assert [o["title"] for o in data["top_opportunities"]] == ["AI Fellows Program"]
    assert "url" not in data["top_opportunities"][0]  # Claude cites by id; it never sees or writes URLs

    # Econ isn't curated for planning, so the planner says so instead of Claude guessing.
    plan_result = last_tool_result(counselor_claude.requests[1])
    assert "Economics" in plan_result["error"] and DS in plan_result["error"]
    econ = last_tool_result(counselor_claude.requests[2])
    assert econ["summary"]["missing"] == 1

    # [S…] → [1], [2] in order of use; unknown ids dropped.
    assert "[1]" in body.reply and "[2]" in body.reply and "S999" not in body.reply and "[S" not in body.reply
    assert [c.source for c in body.citations] == ["assist", "assist"]
    assert "ECON 1B" in body.citations[0].ref and "Economics, B.S." in body.citations[0].label
    assert "MATH 31" in body.citations[1].ref
    assert all(c.url.startswith("https://assist.org/") for c in body.citations)

    # The plan couldn't be computed, so an advisor question is added even though Claude didn't draft one.
    assert "Confirm with your advisor" in body.reply
    assert "Economics, B.S." in body.reply.split("Confirm with your advisor", 1)[1]

    # Every Claude call is charged to the daily cap; tools were allowed on each.
    assert fresh_claude_limiter._day_count == 3
    assert all(r["tool_choice"] == {"type": "auto"} for r in counselor_claude.requests)
    assert {t["name"] for t in counselor_claude.requests[0]["tools"]} == {"plan_with_majors", "match_major"}


def test_claude_drafted_advisor_question_is_kept_and_cited(counselor_claude):
    pid = make_student()

    def answer(req):
        cs = source_of(student_data(req)["match_results"][0], "CS 46A")
        return (f"CIS 22A is partial for CS 46A [{cs}].",
                f"Does CIS 22A alone count for CS 46A under the sequence rule [{cs}]?")

    counselor_claude.steps.append(final(answer))
    body = CounselorResponse.model_validate(ask(pid, "Does CIS 22A count?").json())
    assert body.reply.endswith("“Does CIS 22A alone count for CS 46A under the sequence rule [1]?”")
    assert len(body.citations) == 1 and "CS 46A" in body.citations[0].ref


def test_uncertain_citation_without_question_gets_a_fallback_question(counselor_claude):
    pid = make_student()
    counselor_claude.steps.append(final(lambda req: (
        f"CIS 22A is partial for CS 46A [{source_of(student_data(req)['match_results'][0], 'CS 46A')}].", None)))
    reply = ask(pid, "Does CIS 22A count?").json()["reply"]
    assert "Confirm with your advisor" in reply
    assert "CS 46A - Introduction to Programming: partial" in reply and "sequence_rule" in reply


def test_certain_answer_has_no_advisor_section(counselor_claude):
    pid = make_student()
    counselor_claude.steps.append(final(lambda req: (
        f"Yes, MATH 1A covers it [{source_of(student_data(req)['match_results'][0], 'MATH 30')}].", None)))
    body = ask(pid, "Does MATH 1A count?").json()
    assert "advisor" not in body["reply"].lower()
    assert body["reply"] == "Yes, MATH 1A covers it [1]."


def test_history_goes_before_the_question_and_starts_with_the_student(counselor_claude):
    pid = make_student()
    counselor_claude.steps.append(final(lambda req: ("Ok.", None)))
    history = [{"role": "assistant", "content": "Hi! Ask me anything."},
               {"role": "user", "content": "What's left for DS?"},
               {"role": "assistant", "content": "MATH 39 and CS 46B [1]."}]
    assert ask(pid, "And for Econ?", history).status_code == 200
    messages = counselor_claude.requests[0]["messages"]
    assert [m["role"] for m in messages] == ["user", "assistant", "user"]
    assert messages[0]["content"] == "What's left for DS?"
    assert messages[1]["content"] == "MATH 39 and CS 46B."  # old numbering isn't left for Claude to copy
    assert messages[-1]["content"][1] == {"type": "text", "text": "And for Econ?"}


def test_last_call_cannot_use_tools(counselor_claude, fresh_claude_limiter):
    pid = make_student()
    counselor_claude.steps += [tool_call("match_major", {"major_label": ECON}, id=f"t{i}")
                               for i in range(counselor.MAX_CLAUDE_CALLS)]
    res = ask(pid)
    assert res.status_code == 502
    assert counselor_claude.requests[-1]["tool_choice"] == {"type": "none"}
    assert fresh_claude_limiter._day_count == counselor.MAX_CLAUDE_CALLS


# ---- deterministic pieces ----


def test_plan_uses_assist_matches_and_answers_finish_by():
    s = student()
    plan = s.plan([DS], "Fall 2040")
    assert {"MATH 30", "MATH 31"} <= set(plan["already_done_by_code"])  # via ASSIST, not the transcript code
    scheduled = {c["code"] for sem in plan["semesters"] for c in sem["courses"]}
    assert "MATH 30" not in scheduled and "MATH 39" in scheduled
    assert plan["semesters"][0]["term"] == "Spring 2027"  # first registrable term after 2026-10-24
    assert plan["finishes_by_target"] is True and plan["terms_needed"] == len(plan["semesters"])
    assert s.plan([DS], "Spring 2027")["finishes_by_target"] is False
    unparsed = s.plan([DS], "sometime in 2028")
    assert unparsed["finishes_by_target"] is None and "target_error" in unparsed
    # The DS file is placeholder data, so citing its courses always triggers the advisor question.
    sid = plan["semesters"][0]["courses"][0]["source"]
    assert "placeholder" in s.sources.uncertain[sid]
    assert s.sources.citations[sid].label.startswith("PLACEHOLDER · ")


@pytest.mark.parametrize(("last", "target", "verdict"), [
    ("Fall 2027", "Spring 2028", True), ("Spring 2028", "Spring 2028", True),
    ("Fall 2028", "Spring 2028", False), (None, "Spring 2028", True), ("Fall 2027", "2028", None),
])
def test_finishes_by(last, target, verdict):
    assert counselor.finishes_by(last, target) is verdict


def test_match_major_suggests_exact_labels():
    s = student()
    out = counselor.run_tool(s, "match_major", {"major_label": "Economics"})
    assert "error" in out and set(out["closest_labels"]) >= {"Economics, B.S.", "Economics, B.A."}
    assert not s.sources.gaps  # Claude can retry with an exact label
    assert "summary" in counselor.run_tool(s, "match_major", {"major_label": ECON})


def test_successful_retry_clears_the_plan_gap():
    s = student()
    counselor.run_tool(s, "plan_with_majors", {"majors": ["Econ"], "target_term": None})
    assert "plan" in s.sources.gaps
    counselor.run_tool(s, "plan_with_majors", {"majors": [DS], "target_term": "Spring 2028"})
    assert not s.sources.gaps


def test_unavailable_data_is_reported_not_invented(monkeypatch):
    def assist_down(*a, **kw):
        raise AssistError("timeout")

    def store_down(campus, transport=None):
        raise StoreError("down")

    from app.services.assist import get_service
    monkeypatch.setattr(get_service(), "match", assist_down)
    monkeypatch.setattr(radar_store, "candidates", store_down)
    data = counselor.build_context(student())
    assert data["match_results"] == [{"major_label": DS, "error": "ASSIST is unavailable right now"}]
    assert data["top_opportunities"] == {"error": "Opportunities are unavailable right now"}
    assert data["plan"]["semesters"]  # still planned from the transcript alone


def test_citation_markers_share_one_numbering():
    sources = Sources()
    a = sources.add(Citation(source="web", label="A", url="https://a"))
    b = sources.add(Citation(source="web", label="B", url="https://b"))
    assert sources.add(Citation(source="web", label="A again", url="https://a")) == a
    text, cites = counselor.finish_reply(_Answer(reply=f"x [{b}] y [{a}, {b}] z [S77] .", advisor_question=f"q [{a}]"),
                                         sources)
    assert text == "x [1] y [2][1] z.\n\nConfirm with your advisor. Here's a question you can ask them:\n“q [2]”"
    assert [c.label for c in cites] == ["B", "A"]


# ---- limits and errors ----


def test_counselor_uses_the_claude_per_ip_limit(monkeypatch, counselor_claude):
    monkeypatch.setattr(claude_limits, "limiter", ClaudeLimiter(per_ip_per_min=1, daily_cap=500))
    pid = make_student()
    counselor_claude.steps.append(final(lambda req: ("Ok.", None)))
    assert ask(pid).status_code == 200
    res = ask(pid)
    assert res.status_code == 429 and "Retry-After" in res.headers


def test_daily_cap_stops_before_calling_claude(monkeypatch, counselor_claude):
    monkeypatch.setattr(claude_limits, "limiter", ClaudeLimiter(per_ip_per_min=10, daily_cap=0))
    assert ask(make_student()).status_code == 429
    assert counselor_claude.requests == []


@pytest.mark.parametrize(("message", "history"), [
    ("   ", []),
    ("x" * (counselor.MAX_MESSAGE_CHARS + 1), []),
    ("ok", [{"role": "user", "content": "x" * (counselor.MAX_HISTORY_CHARS + 1)}]),
])
def test_bad_questions_are_422_without_calling_claude(counselor_claude, message, history):
    assert ask(make_student(), message, history).status_code == 422
    assert counselor_claude.requests == []


def _api_error(cls, status):
    response = httpx2.Response(status, request=httpx2.Request("POST", "https://api.anthropic.com/v1/messages"))
    return cls("err", response=response, body=None)


@pytest.mark.parametrize(("error", "status"), [
    (_api_error(anthropic.AuthenticationError, 401), 503),
    (_api_error(anthropic.RateLimitError, 429), 503),
    (_api_error(anthropic.InternalServerError, 500), 502),
])
def test_claude_errors_map_to_statuses(counselor_claude, error, status):
    def fail(req):
        raise error

    counselor_claude.steps.append(fail)
    assert ask(make_student()).status_code == status


def test_refusal_is_an_error_not_an_empty_reply(counselor_claude):
    counselor_claude.steps.append(lambda req: SimpleNamespace(stop_reason="refusal", content=[], parsed_output=None))
    assert ask(make_student()).status_code == 502


def test_unknown_profile_is_404_without_calling_claude(counselor_claude):
    assert ask("00000000-0000-0000-0000-000000000000").status_code == 404
    assert counselor_claude.requests == []


def test_history_window_drops_old_turns():
    turns = [ChatMessage(role="user" if i % 2 else "assistant", content=str(i)) for i in range(30)]
    kept = counselor._history(turns)
    assert len(kept) <= counselor.MAX_HISTORY_MESSAGES and kept[0]["role"] == "user" and kept[-1]["content"] == "29"


@pytest.mark.skipif(not os.getenv("COUNSELOR_LIVE"), reason="set COUNSELOR_LIVE=1 to ask the real Claude")
def test_live_demo_question(monkeypatch, capsys):
    """The judging question against real Claude (ASSIST stays on fixtures). Run with -s to read the reply."""
    monkeypatch.setattr(counselor, "_client", anthropic.Anthropic)
    reply, citations = counselor.answer(student().profile, courses(), DEMO_QUESTION, [], today=TODAY)
    with capsys.disabled():
        print(f"\n{reply}\n")
        for i, c in enumerate(citations, 1):
            print(f"[{i}] {c.source} · {c.label} · {c.ref or ''}")
    assert citations and "[S" not in reply and "http" not in reply
    assert "Confirm with your advisor" in reply  # Econ isn't curated for planning yet
