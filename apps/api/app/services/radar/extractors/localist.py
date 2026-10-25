"""Localist event API (events.sjsu.edu/api/2/events) → Parsed items."""

from app.services.radar.extract import Parsed, clean_text, names, parse_when

MODALITY = {"inperson": "in_person", "virtual": "online", "hybrid": "hybrid"}
HIDDEN_LOCATION = "sign in to"  # "Sign in to download the location"


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
        place = clean_text(e.get("location_name") or e.get("location"))
        room = clean_text(e.get("room_number"))
        if HIDDEN_LOCATION in place.lower():
            place = ""
        out.append(Parsed(
            title=e.get("title") or "",
            url=e.get("localist_url") or "",
            starts_at=parse_when(inst.get("start")),
            ends_at=parse_when(inst.get("end")),
            org=org,
            description=e.get("description_text") or "",
            tags=tags,
            type_hints={"workshop"} if "Conferences, Training, Workshops" in tags else set(),
            location=", ".join(p for p in (place, room) if p),
            modality=MODALITY.get(e.get("experience") or ""),
        ))
    return out
