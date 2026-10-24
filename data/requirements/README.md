# Curated major requirements

Upper-division requirements not covered by ASSIST (PROJECT.md §8.2).
One JSON file per major (e.g. `sjsu-data-science-bs.json`); every course and group carries a `source_url`.
Prerequisites are stored as edges for the planner (`apps/api/app/services/planner.py` validates the format).

**Source.** The SJSU files come from SJSU's official 2025-2026 catalog PDF; each `source_url` links the
exact page (`…/2025-2026+Academic+Catalog.pdf#page=N`). The 2026-2027 online catalog blocks automated
access, so it hasn't been checked for changes (DECISIONS.md D-007).

**Only what the catalog says.** Titles, units, prerequisite wording (`prereq_text`) and `notes` are
copied from the catalog. Where it's ambiguous or can't be expressed as edges, the item says so in
`needs_review` instead of guessing; the counselor turns those into an advisor question.

## Format

Top level: `major_label` (the exact ASSIST label), `campus`, `catalog_year`, `source_url`, `notes[]`,
`needs_review[]`, `placeholder` (true only for invented test data), `courses{}`, `groups[]`.

`courses["CS 163"]`:
- `title`, `units` (the minimum for a range), `units_max` (for "1-3 unit(s)")
- `prereqs[]`: all required. May name courses outside the file (shared with another major or
  lower-division); the planner only schedules ones in the file.
- `prereqs_one_of[[...]]`: each inner list is "any one of", e.g. `[["CS 156", "CS 171"]]`
- `prereq_text`: the catalog's wording, including what isn't an edge (standing, placement, consent)
- `terms_offered`: defaults to Fall and Spring; the SJSU catalog doesn't list terms
- `notes[]`, `needs_review[]`, `source_url`

`groups[]`: `id`, `title`, `rule` and `courses[]`, plus `notes[]`, `needs_review[]`, `source_url`.
- `all`: every course
- `n_of` + `n`: that many courses
- `units` + `units`: courses adding up to that many units. `courses` may be empty when the catalog
  names no courses (e.g. Data Science's 9 units of Domain Field Electives); `needs_review` must then
  say why. The planner can't schedule such a group and reports it as not scheduled.

Within one major a course counts toward one group only; across majors it may count for both.
