# Campus registry

Application code names no school. Everything specific to a college or university lives here, one
entry per school we hold data for beyond ASSIST, named by its ASSIST institution id:
`data/campuses/<assist_id>.json`. Profiles link to schools by ASSIST id only, and the API, web app and
agent all read these files the same way for every school
(`apps/api/app/services/campuses.py`, `apps/web/src/lib/campuses.ts`, `apps/agent/src/config.ts`).
`apps/api/tests/test_no_hardcoded_schools.py` fails if a school's name, ASSIST id or feed key shows up in
application code.

A school without an entry still works: ASSIST gives its name, term system and agreements, so students get
credits, GE progress and community-college terms. An entry only adds what ASSIST doesn't have.

## Entry

```json
{
  "assist_id": 39,
  "name": "Display name",
  "short_name": "Short name for running text",
  "term_system": "semester",
  "requirements": ["39/requirements/<major>.json"],
  "opportunities": {
    "feed": "key",
    "sources": "39/opportunity-sources.json",
    "programs": "39/programs.json",
    "vocabulary": { "staff_audience_tags": [], "wellness_tags": [], "faculty_prefixes": [] }
  },
  "university_guide": { "sources": "39/guide-sources.json", "guide": "39/guide.json" }
}
```

Paths are relative to this folder. Only `assist_id`, `name` and `short_name` are required.

- `term_system`: `quarter` or `semester`. ASSIST's institution data wins; this is used only when ASSIST
  can't be read, and the default after that is semesters.
- `requirements`: curated degree requirements ([REQUIREMENTS.md](REQUIREMENTS.md)). Any file here gives the
  university the "Full Plan": the planner schedules its upper-division courses after transfer. Every
  file under `<id>/requirements/` must be listed (the web app bundles that folder).
- `opportunities`: the school's Radar feed. `feed` is the opaque key its stored listings, Radar runs and
  agent jobs are kept under (unique, lowercase). `sources` lists the pages Apify scans (format as in
  `data/opportunities/shared-sources.json`, which every feed also scans), `programs` the hand-checked
  recurring programs. `vocabulary` holds words the school's own feeds use that ranking needs: calendar
  audience tags meaning staff only, tags that mean Wellness & Community, and the word in "for <word>
  faculty".
- `university_guide`: the pages its "What to Expect" guide may cite and the checked-in guide
  (`python -m app.services.university.build <assist_id>` writes it). The sections are shared:
  `data/university/sections.json`.

## Who reads a feed

A student reads their target university's feed and, when their own community college has an entry with
`opportunities`, that one too. Each listing from a campus's own sources is labeled with it ("At SJSU, your
target school" before transfer); open listings such as hackathons aren't. A school with no feed adds
nothing, so a student never sees another campus's listings.

## Adding a school

1. Create `<assist_id>.json` with `assist_id`, `name` and `short_name`.
2. Add whatever data you have: requirements files, opportunity sources (then `python -m app.scan <feed>`),
   programs, guide sources (then build the guide).
3. Run the API tests. No code change is needed.
