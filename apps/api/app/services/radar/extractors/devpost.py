"""Devpost hackathon search API (devpost.com/api/hackathons) → Parsed items."""

from app.services.radar.extract import Parsed, clean_text, names, pacific_midnight, parse_devpost_dates


def extract(raw, source):
    out = []
    for h in (raw.get("json") or {}).get("hackathons") or []:
        if h.get("open_state") == "ended" or h.get("invite_only"):
            continue
        dates = parse_devpost_dates(h.get("submission_period_dates"))
        location = clean_text((h.get("displayed_location") or {}).get("location"))
        themes = names(h.get("themes"))
        prize = clean_text(h.get("prize_amount"))
        parts = [f"Location: {location}." if location else "",
                 f"Themes: {', '.join(themes)}." if themes else "",
                 f"Prizes: {prize}." if prize and prize not in ("$0", "$ 0") else ""]
        out.append(Parsed(
            title=h.get("title") or "",
            url=h.get("url") or "",
            starts_at=pacific_midnight(dates[0]) if dates else None,
            # The submission period's last day is the deadline.
            deadline=pacific_midnight(dates[1]) if dates else None,
            org=h.get("organization_name") or "",
            description=" ".join(p for p in parts if p),
            tags=themes + (["online"] if location.lower() == "online" else []),
            type_hints={"hackathon"},
            location="" if location.lower() == "online" else location,
            modality=("online" if location.lower() == "online" else "in_person") if location else None,
        ))
    return out
