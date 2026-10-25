"""Build or refresh a university's guide.

    cd apps/api && uv run python -m app.services.university.build 39
    ... --cached-pages   # reuse the pages saved by the last build instead of an Apify run
    ... --dry-run        # fetch and report; no Claude calls, nothing written

One Apify run reads every source page. A section is rewritten by Claude (one call) only
when its pages or the prompt changed since the guide file was written; otherwise the
section is reused as is. The result goes to data/university/guides/<id>.json and to the
Supabase cache. Review the file's diff before committing it.
"""

import argparse
import json
import logging
import sys
from datetime import datetime, timezone
from typing import Any

from app.services.university import fetch, sources, store, write

log = logging.getLogger(__name__)


def build(university_id: int, pages: list[fetch.Page], previous: dict[str, Any] | None = None,
          now: datetime | None = None) -> dict[str, Any]:
    uni = sources.university(university_id)
    if uni is None:
        raise SystemExit(f"No sources for university {university_id} in {sources.SOURCES_FILE}")
    now = now or datetime.now(timezone.utc)
    reused = {s["id"]: s for s in (previous or {}).get("sections", [])}
    by_id = {p.source_id: p for p in pages}

    sections = []
    for section in sources.load().sections:
        section_pages = [by_id[s.id] for s in uni.for_section(section.id) if s.id in by_id]
        digest = write.input_hash(uni.name, section, section_pages)
        if (old := reused.get(section.id)) and old.get("input_hash") == digest:
            log.info("section %s unchanged; reused", section.id)
            sections.append({**old, "title": section.title, "opportunity_types": section.opportunity_types})
            continue
        log.info("section %s: writing from %d pages", section.id, len(section_pages))
        try:
            written = write.write_section(uni.name, section, section_pages)
        except Exception as e:  # one failed section shouldn't throw away the others' calls
            log.error("section %s failed: %s; %s", section.id, e, "kept the previous one" if old else "left empty")
            if old:
                sections.append(old)
            continue
        sections.append({
            "id": section.id, "title": section.title, "opportunity_types": section.opportunity_types,
            "input_hash": written.input_hash,
            "items": [item.__dict__ for item in written.items],
            "not_covered": written.not_covered,
        })

    cited = {sid for sec in sections for item in sec["items"] for sid in item["source_ids"]}
    source_rows = [{"id": s.id, "title": s.title, "publisher": s.publisher, "url": str(s.url),
                    "retrieved_on": by_id[s.id].retrieved_on}
                   for s in uni.sources if s.id in cited and s.id in by_id]
    return {
        "university_id": uni.id,
        "university_name": uni.name,
        "last_updated": max((s["retrieved_on"] for s in source_rows), default=now.date().isoformat()),
        "generated_at": now.isoformat(timespec="seconds"),
        "sections": sections,
        "sources": source_rows,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("university_id", type=int)
    parser.add_argument("--cached-pages", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    uni = sources.university(args.university_id)
    if uni is None:
        print(f"No sources for university {args.university_id}", file=sys.stderr)
        return 1
    pages = store.cached_pages(uni.id) if args.cached_pages else fetch.fetch_pages(uni)
    print(f"{len(pages)} of {len(uni.sources)} pages usable: "
          + ", ".join(f"{p.source_id} ({len(p.text)})" for p in pages))
    if args.dry_run:
        return 0
    if not args.cached_pages and not store.save_pages(uni.id, pages):
        print("Pages not cached (Supabase not configured or table missing)", file=sys.stderr)

    path = store.guide_file(uni.id)
    previous = json.loads(path.read_text()) if path.exists() else None
    guide = build(uni.id, pages, previous)
    cached = store.save_guide(guide)
    items = sum(len(s["items"]) for s in guide["sections"])
    print(f"Wrote {path} ({len(guide['sections'])} sections, {items} items, {len(guide['sources'])} sources)"
          + ("" if cached else "; not cached in Supabase"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
