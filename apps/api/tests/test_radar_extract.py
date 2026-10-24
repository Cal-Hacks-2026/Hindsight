"""The guard on extractors/<kind>.py, the files Droid may patch (DECISIONS.md D-003, D-006)."""

import pytest

from app.services.radar import extract

OK = '''
from json import loads
from app.services.radar.extract import Parsed, parse_when

def _title(e):
    return (e.get("title") or "").strip()

def extract(raw, source):
    return [Parsed(title=_title(e), url=e.get("url") or "") for e in loads(raw["text"])]
'''


def test_real_extractors_pass_the_guard():
    for path in sorted(extract.EXTRACTORS_DIR.glob("*.py")):
        extract.check_source(path.read_text(), path.name)


def test_plain_parsing_code_loads_and_runs(tmp_path, monkeypatch):
    monkeypatch.setattr(extract, "EXTRACTORS_DIR", tmp_path)
    (tmp_path / "demo.py").write_text(OK)
    fn = extract.load("demo")
    (item,) = fn({"text": '[{"title": " Hi ", "url": "https://x.org"}]'}, None)
    assert item == extract.Parsed(title="Hi", url="https://x.org")


@pytest.mark.parametrize("snippet,why", [
    ("import os", "not `import`"),
    ("from os import environ", "not allowed"),
    ("from subprocess import run", "not allowed"),
    ("from app.services.db import client", "not allowed"),
    ("from app.services.radar.extract import Path", "not allowed"),
    ("from json import codecs", "not allowed"),
    ("from . import x", "not allowed"),
    ("x = open('/etc/passwd').read()", "`open`"),
    ("x = eval('1')", "`eval`"),
    ("x = __import__('os')", "`__import__`"),
    ("x = getattr(1, 'real')", "`getattr`"),
    ("x = ().__class__", "`.__class__`"),
    ("x = (i for i in []).gi_frame", "`.gi_frame`"),
    ("x = e.f_back", "`.f_back`"),
    ("x = '{0.__class__}'.format(1)", "`.format`"),
    ("x = __builtins__", "`__builtins__`"),
    ("def f():\n    global y", "global"),
    ("def extract(raw, source):\n    source.url = 'https://evil.example'", "assigning to `.url`"),
    ("def extract(raw, source):\n    del source.tags", "assigning to `.tags`"),
    ("def extract(raw, source)\n    return []", "syntax error"),
    ("match source:\n    case object(__class__=c):\n        pass", "`match`"),
    ("x = int.mro()", "`.mro`"),
    ("try:\n    pass\nexcept:\n    pass", "bare `except:`"),
])
def test_guard_refuses_unsafe_code(snippet, why):
    with pytest.raises(extract.ExtractorError, match=why.replace("(", r"\(").replace(".", r"\.")):
        extract.check_source(snippet, "patched.py")


def test_load_reports_a_missing_extract_function(tmp_path, monkeypatch):
    monkeypatch.setattr(extract, "EXTRACTORS_DIR", tmp_path)
    (tmp_path / "empty.py").write_text("X = 1\n")
    with pytest.raises(extract.ExtractorError, match="defines no extract"):
        extract.load("empty")


def test_load_contains_import_time_errors(tmp_path, monkeypatch):
    monkeypatch.setattr(extract, "EXTRACTORS_DIR", tmp_path)
    (tmp_path / "boom.py").write_text("X = {}['missing']\n")
    with pytest.raises(extract.ExtractorError, match="KeyError"):
        extract.load("boom")


def test_builtins_are_reduced_at_runtime(tmp_path, monkeypatch):
    """Even code the AST check misses can't reach file builtins."""
    monkeypatch.setattr(extract, "EXTRACTORS_DIR", tmp_path)
    monkeypatch.setattr(extract, "check_source", lambda text, filename="": None)
    (tmp_path / "sneaky.py").write_text("def extract(raw, source):\n    return open('/etc/hosts')\n")
    with pytest.raises(NameError):
        extract.load("sneaky")({}, None)


def test_a_patch_is_picked_up_on_the_next_load(tmp_path, monkeypatch):
    monkeypatch.setattr(extract, "EXTRACTORS_DIR", tmp_path)
    path = tmp_path / "k.py"
    path.write_text("def extract(raw, source):\n    return []\n")
    assert extract.load("k")({}, None) == []
    path.write_text("from app.services.radar.extract import Parsed\n"
                    "def extract(raw, source):\n    return [Parsed(title='t', url='https://a.b')]\n")
    assert len(extract.load("k")({}, None)) == 1


# ---- isolated runner ----

from datetime import datetime, timezone  # noqa: E402

from app.services.radar import sources  # noqa: E402

SRC = sources.by_id("sjsu-events-ai-tech")


def _write(tmp_path, kind, body):
    (tmp_path / f"{kind}.py").write_text(body)


def test_isolated_runner_round_trips_parsed_items(tmp_path):
    _write(tmp_path, "k", "from datetime import datetime, timezone\n"
           "from app.services.radar.extract import Parsed\n"
           "def extract(raw, source):\n"
           "    return [Parsed(title=raw['t'], url='https://a.b', starts_at=datetime(2026, 11, 1, tzinfo=timezone.utc),"
           " tags=['x'], type_hints={'workshop'})]\n")
    (res,) = extract.run_isolated({"k": [({"t": "Hi"}, SRC)]}, extractors_dir=tmp_path)["k"]
    assert res == [extract.Parsed(title="Hi", url="https://a.b", starts_at=datetime(2026, 11, 1, tzinfo=timezone.utc),
                                  tags=["x"], type_hints={"workshop"})]


def test_isolated_runner_starts_with_no_environment(monkeypatch):
    """The API's keys never reach the process that runs patched code."""
    import subprocess

    seen = {}
    real_run = subprocess.run

    def spy(args, **kwargs):
        seen.update(args=args, env=kwargs.get("env"))
        return real_run(args, **kwargs)

    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "sb_secret_should_not_leak")
    monkeypatch.setattr(extract.subprocess, "run", spy)
    extract.run_isolated({"localist": [({"json": {"events": []}}, SRC)]})
    assert seen["env"] == {} and seen["args"][1] == "-I"


def test_isolated_runner_times_out_one_kind(tmp_path):
    _write(tmp_path, "slow", "def extract(raw, source):\n    while True:\n        try:\n            pass\n"
           "        except Exception:\n            pass\n")
    _write(tmp_path, "fast", "def extract(raw, source):\n    return []\n")
    monkey = extract.KIND_TIMEOUT_S
    extract.KIND_TIMEOUT_S = 1
    try:
        out = extract.run_isolated({"slow": [({}, SRC)], "fast": [({}, SRC)]}, extractors_dir=tmp_path)
    finally:
        extract.KIND_TIMEOUT_S = monkey
    assert "did not finish" in str(out["slow"][0]) and out["fast"] == [[]]


def test_isolated_runner_fails_closed_on_a_dead_process(tmp_path):
    out = extract.run_isolated({"k": [({}, SRC)]}, extractors_dir=tmp_path, timeout=0.001)
    assert isinstance(out["k"][0], extract.ExtractorError)


@pytest.mark.parametrize("forged", [
    "nope", {"title": 1, "url": "", "org": "", "description": "", "tags": [], "type_hints": []},
    {"title": "t", "url": "u", "org": "", "description": "", "tags": [], "type_hints": [], "starts_at": "2026-11-01"},
    {"title": "t", "url": "u", "org": "", "description": "", "tags": "x", "type_hints": []},
])
def test_worker_output_is_revalidated(forged):
    with pytest.raises((ValueError, TypeError)):
        extract.parsed_from_json(forged)


def test_symlinked_extractors_are_refused(tmp_path, monkeypatch):
    """Droid's OS user owns the folder; a link must not point the API at its own files."""
    secret = tmp_path / "secret.txt"
    secret.write_text("sb_secret_x = 1\n")
    folder = tmp_path / "extractors"
    folder.mkdir()
    (folder / "k.py").symlink_to(secret)
    (folder / "page_function.js").symlink_to(secret)
    monkeypatch.setattr(extract, "EXTRACTORS_DIR", folder)
    with pytest.raises(extract.ExtractorError, match="unreadable"):
        extract.load("k")
    with pytest.raises(OSError):
        extract.page_function()
