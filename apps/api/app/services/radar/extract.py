"""Per-kind extractors (extractors/<kind>.py) and the helpers they share (DECISIONS.md D-003, D-006).

Each source kind in data/sources.json has one extractor file with
`extract(raw, source) -> list[Parsed]`. Droid may patch those files (and only those),
so this module treats them as untrusted code:
- every load compiles the file fresh from disk, so a patch takes effect on the next
  scan without a restart (and with no stale bytecode cache);
- `check_source` refuses anything but plain parsing code before it runs: only
  allowlisted `from X import Y` imports, no file/eval/introspection builtins, no
  underscore or frame attributes, no attribute assignment; the module also runs with a reduced set of builtins.
This raises the bar for a bad patch; it is not a sandbox. The shared rules that
make an item safe to show (http(s) URL, title, dates, dedupe) live in normalize.py,
outside Droid's reach.
"""

import ast
import builtins
import html
import re
import types
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any, Callable, Literal
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

from app.services.radar.sources import Source

EXTRACTORS_DIR = Path(__file__).parent / "extractors"
PACIFIC = ZoneInfo("America/Los_Angeles")

ItemType = Literal["event", "workshop", "club", "program", "hackathon", "position"]


@dataclass
class Parsed:
    """What an extractor pulls from one listing; normalize() fills in the rest."""

    title: str
    url: str
    starts_at: datetime | None = None
    ends_at: datetime | None = None
    deadline: datetime | None = None
    org: str = ""
    description: str = ""
    tags: list[str] = field(default_factory=list)
    type_hints: set[ItemType] = field(default_factory=set)  # from the source's own categories


# ---- helpers for extractors ----

_TAG = re.compile(r"<[^>]+>")
_SPACE = re.compile(r"\s+")
_FRACTION = re.compile(r"(\.\d{6})\d+")
_URL_UNSAFE = re.compile(r"[\s\x00-\x1f\x7f]")


def clean_text(value: Any) -> str:
    """HTML or entity-laden text → one line of plain text."""
    if not isinstance(value, str):
        return ""
    text = html.unescape(_TAG.sub(" ", html.unescape(value)))
    return _SPACE.sub(" ", text).strip()


def parse_when(value: Any) -> datetime | None:
    """ISO 8601 datetime or date → aware datetime; None when absent or unparseable."""
    if not isinstance(value, str) or not value.strip():
        return None
    raw = _FRACTION.sub(r"\1", value.strip().replace("Z", "+00:00"))
    try:
        if len(raw) == 10:
            return datetime.combine(date.fromisoformat(raw), datetime.min.time(), PACIFIC)
        dt = datetime.fromisoformat(raw)
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=PACIFIC)


def pacific_midnight(d: date) -> datetime:
    return datetime.combine(d, datetime.min.time(), PACIFIC)


_MONTHS = {m: i for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], start=1)}
_DEVPOST_RANGE = re.compile(
    r"^(?P<m1>[A-Za-z]{3})[a-z]*\.? (?P<d1>\d{1,2})(?:, (?P<y1>\d{4}))?"
    r"(?: - (?:(?P<m2>[A-Za-z]{3})[a-z]*\.? )?(?P<d2>\d{1,2}))?, (?P<y2>\d{4})$"
)


def parse_devpost_dates(text: Any) -> tuple[date, date] | None:
    """Devpost `submission_period_dates` → (first day, last day).

    Forms seen: "Oct 23 - 25, 2026", "Oct 23 - Nov 02, 2026",
    "Dec 30, 2026 - Jan 02, 2027", "Mar 27, 2027".
    """
    if not isinstance(text, str):
        return None
    m = _DEVPOST_RANGE.match(text.strip())
    if not m:
        return None
    try:
        m1 = _MONTHS[m["m1"].lower()]
        m2 = _MONTHS[m["m2"].lower()] if m["m2"] else m1
        y2 = int(m["y2"])
        y1 = int(m["y1"]) if m["y1"] else y2
        start = date(y1, m1, int(m["d1"]))
        end = date(y2, m2, int(m["d2"])) if m["d2"] else start
    except (KeyError, ValueError):
        return None
    if end < start:
        return None
    return start, end


def is_http_url(value: Any) -> bool:
    """An absolute http(s) URL with a host and no whitespace or control characters.
    Scraped URLs are untrusted: javascript:, data:, relative, and malformed ones fail."""
    if not isinstance(value, str) or _URL_UNSAFE.search(value):
        return False
    try:
        parts = urlsplit(value)
        host = parts.hostname
    except ValueError:
        return False
    return parts.scheme in ("http", "https") and bool(host) and value.lower().startswith(f"{parts.scheme}://")


def names(entries: Any) -> list[str]:
    """[{"name": ...}, ...] → the names, skipping anything malformed."""
    return [e["name"] for e in entries or [] if isinstance(e, dict) and isinstance(e.get("name"), str)]


# ---- loading extractors/<kind>.py ----

Extractor = Callable[[dict, Source], list[Parsed]]


class ExtractorError(Exception):
    pass


# The only imports an extractor may make, and the names it may take from each.
ALLOWED_IMPORTS: dict[str, set[str]] = {
    "app.services.radar.extract": {"Parsed", "clean_text", "parse_when", "pacific_midnight",
                                   "parse_devpost_dates", "is_http_url", "names", "PACIFIC"},
    "re": {"compile", "match", "fullmatch", "search", "sub", "split", "findall", "finditer", "escape",
           "I", "IGNORECASE", "M", "MULTILINE", "S", "DOTALL"},
    "json": {"loads", "JSONDecodeError"},
    "html": {"unescape"},
    "datetime": {"date", "datetime", "timedelta", "timezone"},
    "defusedxml": {"DefusedXmlException"},
    "defusedxml.ElementTree": {"fromstring", "ParseError"},
    "typing": {"Any"},
}
_BANNED_NAMES = {"open", "exec", "eval", "compile", "__import__", "globals", "locals", "vars", "dir",
                 "getattr", "setattr", "delattr", "hasattr", "breakpoint", "input", "help", "exit", "quit",
                 "memoryview", "type", "object", "super", "classmethod", "staticmethod", "property"}
_BANNED_ATTRS = {"format", "format_map"}  # str.format can walk attributes the AST check can't see
# Frame, code, and traceback attributes lead back to real globals and builtins.
_BANNED_ATTR = re.compile(r"^(_|f_|gi_|cr_|ag_|tb_|co_)")
_SAFE_BUILTINS = {
    name: getattr(builtins, name) for name in (
        "abs", "all", "any", "bool", "dict", "enumerate", "filter", "float", "frozenset", "int",
        "isinstance", "len", "list", "map", "max", "min", "next", "iter", "range", "reversed", "round",
        "set", "sorted", "str", "sum", "tuple", "zip", "None", "True", "False",
        "Exception", "ValueError", "KeyError", "TypeError", "IndexError", "AttributeError", "StopIteration",
    )
}


def check_source(text: str, filename: str = "<extractor>") -> None:
    """Raise ExtractorError unless `text` is plain parsing code (see module docstring)."""
    try:
        tree = ast.parse(text, filename)
    except SyntaxError as e:
        raise ExtractorError(f"{filename}: syntax error on line {e.lineno}: {e.msg}") from e
    for node in ast.walk(tree):
        line = getattr(node, "lineno", "?")
        if isinstance(node, ast.Import):
            raise ExtractorError(f"{filename}:{line}: use `from <module> import <name>`, not `import`")
        if isinstance(node, ast.ImportFrom):
            allowed = ALLOWED_IMPORTS.get(node.module or "") if node.level == 0 else None
            bad = [a.name for a in node.names if allowed is None or a.name not in allowed]
            if bad:
                raise ExtractorError(f"{filename}:{line}: import of {', '.join(bad)} from "
                                     f"{'.' * node.level}{node.module or ''} is not allowed")
        elif isinstance(node, ast.Name) and (node.id in _BANNED_NAMES or node.id.startswith("__")):
            raise ExtractorError(f"{filename}:{line}: `{node.id}` is not allowed in an extractor")
        elif isinstance(node, ast.Attribute) and (_BANNED_ATTR.match(node.attr) or node.attr in _BANNED_ATTRS):
            raise ExtractorError(f"{filename}:{line}: attribute `.{node.attr}` is not allowed in an extractor")
        elif isinstance(node, (ast.Global, ast.Nonlocal)):
            raise ExtractorError(f"{filename}:{line}: global/nonlocal is not allowed in an extractor")
        if isinstance(node, ast.Attribute) and isinstance(node.ctx, (ast.Store, ast.Del)):
            raise ExtractorError(f"{filename}:{line}: assigning to `.{node.attr}` is not allowed in an extractor")


def _guarded_import(name, globals=None, locals=None, fromlist=(), level=0):
    allowed = ALLOWED_IMPORTS.get(name)
    if level != 0 or allowed is None or not fromlist or not set(fromlist) <= allowed:
        raise ImportError(f"import of {name} is not allowed in an extractor")
    return __import__(name, globals, locals, fromlist, level)


def extractor_path(kind: str) -> Path:
    return EXTRACTORS_DIR / f"{kind}.py"


def load(kind: str) -> Extractor:
    """Compile extractors/<kind>.py from disk now. A broken or refused file raises
    ExtractorError, which normalize() records against that kind's sources only."""
    path = extractor_path(kind)
    try:
        text = path.read_text()
    except OSError as e:
        raise ExtractorError(f"{path.name}: unreadable: {e}") from e
    check_source(text, path.name)
    module = types.ModuleType(f"radar_extractor_{kind}")
    module.__file__ = str(path)
    module.__dict__["__builtins__"] = {**_SAFE_BUILTINS, "__import__": _guarded_import}
    try:
        exec(compile(text, str(path), "exec"), module.__dict__)
    except Exception as e:  # any failure in a patched file must stay contained to its kind
        raise ExtractorError(f"{path.name}: {type(e).__name__}: {e}") from e
    fn = module.__dict__.get("extract")
    if not callable(fn):
        raise ExtractorError(f"{path.name} defines no extract(raw, source) function")
    return fn


def page_function() -> str:
    """The Cheerio Scraper pageFunction, read per scan so a patch reaches the next run."""
    return (EXTRACTORS_DIR / "page_function.js").read_text()
