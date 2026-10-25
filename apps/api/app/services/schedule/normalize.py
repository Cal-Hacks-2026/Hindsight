"""Printed schedule values → contract values. Pure and deterministic: Claude copies what
the page says, and this code decides what it means (same split as the transcript parser).

Every helper returns None (or []) when it can't read a value, and the caller flags the row
so the student checks it before confirming.
"""

import re
from datetime import date

from app.services.transcript import normalize_term

WEEKDAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")

# Longest tokens first so "Th" never reads as "T" + "h".
_DAY_TOKENS = [
    ("thursday", "Thu"), ("tuesday", "Tue"), ("saturday", "Sat"), ("sunday", "Sun"),
    ("monday", "Mon"), ("wednesday", "Wed"), ("friday", "Fri"),
    ("thur", "Thu"), ("thu", "Thu"), ("tue", "Tue"), ("tues", "Tue"), ("mon", "Mon"), ("wed", "Wed"),
    ("fri", "Fri"), ("sat", "Sat"), ("sun", "Sun"),
    ("th", "Thu"), ("tu", "Tue"), ("sa", "Sat"), ("su", "Sun"),
    ("m", "Mon"), ("t", "Tue"), ("w", "Wed"), ("r", "Thu"), ("f", "Fri"), ("s", "Sat"), ("u", "Sun"),
]
_DAY_TOKENS.sort(key=lambda t: -len(t[0]))
_BLANK = {"", "tba", "tbd", "arr", "arranged", "online", "async", "asynchronous", "n/a", "na", "-", "--"}

_TIME = re.compile(r"^(\d{1,2})(?::?(\d{2}))?\s*([ap])?\.?\s*m?\.?$", re.IGNORECASE)
_DATE_PATTERNS = (
    re.compile(r"^(?P<m>\d{1,2})/(?P<d>\d{1,2})/(?P<y>\d{2,4})$"),
    re.compile(r"^(?P<y>\d{4})-(?P<m>\d{1,2})-(?P<d>\d{1,2})$"),
)
_DATE_RANGE_SPLIT = re.compile(r"\s*(?:-|–|—|\bto\b)\s*", re.IGNORECASE)


def days(raw: str) -> list[str] | None:
    """'MW' / 'TTh' / 'M W F' / 'TR' / 'Mon, Wed' → ['Mon', 'Wed'] in week order.
    [] for TBA/online-style values; None when the text can't be read as days."""
    text = raw.strip().lower()
    if text in _BLANK:
        return []
    text = re.sub(r"[\s,/&.\-]+", "", text)
    found: set[str] = set()
    i = 0
    while i < len(text):
        for token, day in _DAY_TOKENS:
            if text.startswith(token, i):
                found.add(day)
                i += len(token)
                break
        else:
            return None
    return [d for d in WEEKDAYS if d in found]


def _parse_time(raw: str) -> tuple[int, int, str | None] | None:
    m = _TIME.match(raw.strip())
    if not m:
        return None
    hour, minute = int(m.group(1)), int(m.group(2) or 0)
    meridiem = m.group(3).lower() if m.group(3) else None
    if minute > 59 or hour > 23 or (meridiem and not 1 <= hour <= 12):
        return None
    if m.group(2) is None and meridiem is None and len(m.group(1)) <= 2:
        return None  # a bare "9" isn't a time
    return hour, minute, meridiem


def _to_24(hour: int, minute: int, meridiem: str) -> int:
    hour = hour % 12 + (12 if meridiem == "p" else 0)
    return hour * 60 + minute


def fmt(minutes: int) -> str:
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


def minutes(hhmm: str) -> int:
    hour, minute = hhmm.split(":")
    return int(hour) * 60 + int(minute)


def times(raw_start: str, raw_end: str) -> tuple[str | None, str | None, list[str]]:
    """('9:30', '10:45 AM') → ('09:30', '10:45', []). A missing AM/PM is taken from the
    other time; with neither, 24-hour values are read as is and 1–6 o'clock is read as PM
    (flagged 'time_assumed'). Unreadable or end-before-start → (None, None, ['time_unparsed'])."""
    if raw_start.strip().lower() in _BLANK and raw_end.strip().lower() in _BLANK:
        return None, None, []  # blank, "-", "TBA" and the like
    start, end = _parse_time(raw_start), _parse_time(raw_end)
    if start is None or end is None:
        return None, None, ["time_unparsed"]
    flags: list[str] = []
    (sh, sm, sp), (eh, em, ep) = start, end
    if sp is None and ep is None:
        if sh > 12 or eh > 12 or sh == 0 or raw_start.strip().startswith("0"):
            s, e = sh * 60 + sm, eh * 60 + em  # 24-hour clock
        else:
            # Classes run 7 AM–10 PM: 7–11 o'clock is morning, 12–6 is afternoon or evening.
            sp = "a" if 7 <= sh <= 11 else "p"
            ep = "a" if 7 <= eh <= 11 and (sp == "a") else "p"
            s, e = _to_24(sh, sm, sp), _to_24(eh, em, ep)
            flags.append("time_assumed")
    else:
        if ep is None:
            ep = sp
        if sp is None:
            # "11:30 - 1:20 PM": the start is AM when reading it as PM would put it after the end.
            sp = ep
            if _to_24(sh, sm, sp) >= _to_24(eh, em, ep):
                sp = "a" if ep == "p" else "p"
        s, e = _to_24(sh, sm, sp), _to_24(eh, em, ep)
    if e <= s:
        return None, None, ["time_unparsed"]
    return fmt(s), fmt(e), flags


def mode(raw_mode: str, location: str, has_meeting: bool) -> str:
    """Instruction method as printed → in_person / online / hybrid / asynchronous.
    An online class with no meeting days or times is asynchronous."""
    text = f"{raw_mode} {location}".lower()
    if "async" in text:
        return "asynchronous"
    if "hybrid" in text or "partially online" in text or "blended" in text:
        return "hybrid"
    if re.search(r"\b(online|remote|zoom|virtual|distance|synchronous)\b", text):
        return "online" if has_meeting else "asynchronous"
    return "in_person"


def _date(raw: str) -> str | None:
    for pattern in _DATE_PATTERNS:
        m = pattern.match(raw.strip())
        if m:
            year = int(m.group("y"))
            year += 2000 if year < 100 else 0
            try:
                return date(year, int(m.group("m")), int(m.group("d"))).isoformat()
            except ValueError:
                return None
    return None


def dates(raw: str) -> tuple[str | None, str | None, list[str]]:
    """'09/21/2026 - 12/11/2026' → ('2026-09-21', '2026-12-11', [])."""
    if not raw.strip():
        return None, None, []
    parts = [p for p in _DATE_RANGE_SPLIT.split(raw.strip()) if p]
    if len(parts) != 2:
        return None, None, ["dates_unparsed"]
    start, end = _date(parts[0]), _date(parts[1])
    if start is None or end is None or end < start:
        return None, None, ["dates_unparsed"]
    return start, end, []


_TERM_WORDS = re.compile(r"\b(quarter|semester|term|session|qtr|sem)\b", re.IGNORECASE)
_YEAR_FIRST = re.compile(r"^(\d{4})\s+([A-Za-z]+)$")


def term(raw: str) -> tuple[str, list[str]]:
    """'Fall 2026 Quarter' / '2026 Fall Semester' / 'Winter Quarter 2027' → 'Fall 2026'."""
    text = re.sub(r"\s+", " ", _TERM_WORDS.sub(" ", raw)).strip()
    flipped = _YEAR_FIRST.match(text)
    if flipped:
        text = f"{flipped.group(2)} {flipped.group(1)}"
    normalized = normalize_term(text)
    return (normalized, []) if normalized else (raw.strip(), ["term_unparsed"])


def course(raw: str) -> str:
    """Whitespace and case only; the printed code is kept (see course_key)."""
    return re.sub(r"\s+", " ", raw.strip()).upper()


def units(raw: str) -> float | None:
    m = re.search(r"\d+(?:\.\d+)?", raw)
    return float(m.group()) if m else None


def course_key(code: str) -> str:
    """Comparable form of a course code: 'MATH D001B', 'math-1b' and 'MATH 1B' → 'MATH1B'.

    Colleges print local forms (De Anza adds a campus letter and zero-pads: D001B). The
    letter is dropped only before a zero-padded number, so CCN codes like C1000 stay intact.
    """
    m = re.match(r"^\s*([A-Za-z&]+)[\s\-_.]*([A-Za-z0-9\-. ]+?)\s*$", code)
    if not m:
        return re.sub(r"[^A-Z0-9]", "", code.upper())
    prefix, number = m.group(1).upper(), re.sub(r"[^A-Z0-9]", "", m.group(2).upper())
    padded = re.match(r"^[A-Z]?0+(\d.*)$", number)
    if padded:
        number = padded.group(1)
    return prefix + number
