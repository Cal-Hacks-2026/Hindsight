# GE list fixtures

Real De Anza College (ASSIST id 113) transferability lists from
`GET https://assist.org/api/transferability/courses?institutionId=113&academicYearId=<year>&listType=<CALGETC|IGETC>`,
fetched 2026-10-25 and trimmed with `app.services.ge.lists.trim` (only the fields the API reads).

- `calgetc-113-77.json`, `igetc-113-77.json` (2026–27): the whole lists, used for options.
- Earlier years (`igetc-113-70/73/74/75/76`, `calgetc-113-76`): only the courses on the De Anza
  persona transcripts in `tests/fixtures/personas/make_fixtures.py`, to keep the repo small.

The fake ASSIST (`tests/assist_fake.py`) serves these; any other college or year comes back as an
empty list, as ASSIST does for an unpublished year.
