"""CampusGroups RSS (sammyapp.sjsu.edu/rss_events) → Parsed items."""

from defusedxml import DefusedXmlException
from defusedxml.ElementTree import ParseError, fromstring

from app.services.radar.extract import Parsed, clean_text, parse_when

MODALITY = {"On-Campus": "in_person", "Off-Campus": "in_person", "Virtual": "online"}
# Placeholders the feed prints instead of a place.
NO_LOCATION = ("private location", "online event")


def extract(raw, source):
    try:
        root = fromstring(raw.get("text") or "")
    except (ParseError, DefusedXmlException) as e:
        raise ValueError(f"unreadable RSS: {e}") from e
    out = []
    for item in root.iter("item"):
        def get(tag):
            return (item.findtext(tag) or "").strip()

        if get("eventDelete") not in ("", "0"):
            continue
        tags = [get("eventType"), get("groupType")] + [t.strip() for t in get("eventTopics").split(",")]
        # "Student Union Ballrooms A/B/C, 1 Washington Square, San Jose, …": the first part names the room.
        place = clean_text(get("eventLocation").split(",")[0])
        if place.lower().startswith(NO_LOCATION):
            place = ""
        out.append(Parsed(
            title=get("title"),
            url=get("eventLink") or get("link"),
            starts_at=parse_when(get("eventStartDateTime")),
            ends_at=parse_when(get("eventEndDateTime")),
            org=get("group"),
            description=get("fullDescription") or get("description"),
            tags=tags,
            type_hints=({"club"} if clean_text(get("groupType")) == "Recognized Student Organization" else set())
            | ({"workshop"} if get("eventType") == "Workshop" else set()),
            location=place,
            modality=MODALITY.get(get("locationType")),
        ))
    return out
