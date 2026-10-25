"""Your University: a sourced "What to Expect" guide per university (SJSU first).

- sources.py: the official pages each guide may cite (data/university/sources.json).
- fetch.py: reads those pages with Apify's Cheerio Scraper, as the Radar does.
- write.py: Claude writes each section only from its pages; every item must quote the
  page it cites, and items whose quote isn't on that page are dropped.
- store.py: guides live in data/university/guides/<id>.json (reviewed in PRs) and in the
  Supabase `university_guide_cache` table; GET serves the newer of the two.
- build.py: `uv run python -m app.services.university.build 39` refreshes a guide.
"""
