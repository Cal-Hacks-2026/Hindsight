"""MLH season page (mlh.com/seasons/...): the page's embedded Next.js JSON → Parsed items."""

from json import loads

from app.services.radar.extract import Parsed, clean_text, is_http_url, parse_when

FORMATS = {"physical": "in-person", "hybrid_physical": "hybrid", "digital": "online"}
MODALITY = {"physical": "in_person", "hybrid_physical": "hybrid", "digital": "online"}


def extract(raw, source):
    out = []
    for blob in raw.get("embeddedJson") or []:
        try:
            events = (loads(blob).get("props") or {}).get("upcomingEvents") or []
        except (ValueError, AttributeError):
            continue  # one unreadable blob doesn't sink the page's other blobs
        for e in events:
            location = clean_text(e.get("location"))
            if source.location_contains and not any(w.lower() in location.lower() for w in source.location_contains):
                continue
            url = e.get("websiteUrl") or ""
            if not is_http_url(url) and isinstance(e.get("url"), str):
                url = f"https://www.mlh.com{e['url']}"
            fmt = FORMATS.get(e.get("formatType") or "", "")
            focus = list(((e.get("customFields") or {}).get("hackathon_focus")) or [])
            out.append(Parsed(
                title=e.get("name") or "",
                url=url,
                starts_at=parse_when(e.get("startsAt")),
                ends_at=parse_when(e.get("endsAt")),
                description=f"MLH member hackathon in {location}." if location else "MLH member hackathon.",
                tags=focus + ([fmt] if fmt else []),
                type_hints={"hackathon"},
                location=location,
                modality=MODALITY.get(e.get("formatType") or ""),
            ))
    return out
