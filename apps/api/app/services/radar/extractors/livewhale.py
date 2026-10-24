"""LiveWhale JSON feed (events.berkeley.edu/live/json/...) → Parsed items."""

from app.services.radar.extract import Parsed, parse_when


def extract(raw, source):
    out = []
    for e in (raw.get("json") or {}).get("data") or []:
        if e.get("is_canceled"):
            continue
        tags = list(e.get("tags") or []) + list(e.get("event_types") or [])
        if e.get("is_online"):
            tags.append("online")
        out.append(Parsed(
            title=e.get("title") or "",
            url=e.get("url") or "",
            starts_at=parse_when(e.get("date_iso")),
            ends_at=parse_when(e.get("date2_iso")),
            org=e.get("group_title") or "",
            description=e.get("summary") or "",
            tags=tags,
        ))
    return out
