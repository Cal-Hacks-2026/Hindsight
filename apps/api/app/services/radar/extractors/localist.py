"""Localist event API (events.sjsu.edu/api/2/events) → Parsed items."""

from app.services.radar.extract import Parsed, names, parse_when


def extract(raw, source):
    out = []
    for wrapper in (raw.get("json") or {}).get("events") or []:
        e = wrapper.get("event") or {}
        if e.get("status") != "live" or e.get("private"):
            continue
        instances = e.get("event_instances") or []
        inst = (instances[0].get("event_instance") or {}) if instances else {}
        filters = e.get("filters") or {}
        tags = (names(filters.get("event_types")) + names(filters.get("event_topic"))
                + names(filters.get("event_target_audience")) + list(e.get("keywords") or []))
        if e.get("experience") == "virtual":
            tags.append("virtual")
        org = (names(e.get("departments")) + names(e.get("groups")) or [""])[0]
        out.append(Parsed(
            title=e.get("title") or "",
            url=e.get("localist_url") or "",
            starts_at=parse_when(inst.get("start")),
            ends_at=parse_when(inst.get("end")),
            org=org,
            description=e.get("description_text") or "",
            tags=tags,
            type_hints={"workshop"} if "Conferences, Training, Workshops" in tags else set(),
        ))
    return out
