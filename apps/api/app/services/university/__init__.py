"""Your University: a sourced "What to Expect" guide for each university whose registry entry
(data/campuses/<id>.json → university_guide) lists source pages.

- sources.py: the guide's sections (data/university/sections.json) and the official pages each
  university's guide may cite (its registry entry's university_guide.sources).
- fetch.py: reads those pages with Apify's Cheerio Scraper, as the Radar does.
- write.py: Claude writes each section only from its pages; every item must quote the
  page it cites, and items whose quote isn't on that page are dropped.
- store.py: guides live in the file the registry entry names (reviewed in PRs) and in the
  Supabase `university_guide_cache` table; GET serves the newer of the two.
- build.py: `uv run python -m app.services.university.build <assist id>` refreshes a guide.
"""
