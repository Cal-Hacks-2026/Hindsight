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
