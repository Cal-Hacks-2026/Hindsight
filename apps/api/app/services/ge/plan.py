"""Missing GE areas → planner slots for the before-transfer terms (/plan?ge=true)."""

from collections import Counter

from app.models import GeArea, GeResponse
from app.services.planner import FALLBACK_CC_UNITS, GeSlot


def _units(area: GeArea, fallback: float) -> float:
    """The most common unit count among the area's approved courses."""
    found = Counter(o.units for o in area.options or [] if o.units > 0)
    return found.most_common(1)[0][0] if found else fallback


def slots(progress: GeResponse) -> list[GeSlot]:
    """One slot per course still needed in each required area, in area order. In-progress
    areas are planned as done (as the planner treats in-progress courses). A lab still needed
    alongside 5A or 5B rides on that course instead of taking a term slot of its own."""
    fallback = FALLBACK_CC_UNITS[progress.term_system]
    open_areas = [a for a in progress.areas if a.required and a.status == "missing" and a.options]
    codes = {a.code for a in open_areas}
    lab_on = next((c for c in ("5A", "5B") if c in codes), None) if "5C" in codes else None
    out: list[GeSlot] = []
    for a in open_areas:
        if a.code == "5C" and lab_on:
            continue
        label = f"{progress.pattern_name} {a.code}"
        reason = (f"{progress.pattern_name} Area {a.code}: {a.title}. Take one of the "
                  f"{len(a.options or [])} approved courses at {progress.institution or 'your college'}"
                  f"{', with a lab (5C)' if a.code == lab_on else ''}."
                  f"{' ' + a.note if a.courses_required > 1 and a.note else ''}")
        units = _units(a, fallback)
        options = [o.code for o in a.options or []]
        subjects = None
        if a.courses_required > 1 and a.code == "4":  # two subjects at least (rules.Area.disciplines)
            subjects = tuple(sorted({c.code.rpartition(" ")[0] for c in a.courses}))
            if len(subjects) == 1:  # the open slots must bring a second subject
                options = [o for o in options if o.rpartition(" ")[0] != subjects[0]]
        out += [GeSlot(area=label, title=a.title, units=units, options=options, reason=reason,
                       subjects=subjects)] * a.still_needed
    return out
