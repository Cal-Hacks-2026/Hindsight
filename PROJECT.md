# PROJECT.md — Hindsight (Cal Hacks 13.0)

> **Read this first.** This is the source of truth for what we are building, why, and what is out of scope.
> Companion docs: `PHASES.md` (build timeline) and `TASKS.md` (who does what).

---

## 0. Status & naming

- **Name:** **Hindsight** — tagline: *"Everything you'd wish you knew, before you need it."* (alt kept in reserve: Day One)
- **Repo:** `github.com/Cal-Hacks-2026/Hindsight`
- **Code identifier:** product name lives in one config constant (`APP_NAME = "Hindsight"`); never hardcode it in logic.
- **Event:** Cal Hacks 13.0, Palace of Fine Arts, SF. Build freeze **Saturday 2:00 PM**. Devpost deadline **Sunday 8:50 AM**. Judging Sunday 10:30 AM (live demo required).
- **Rule:** all project code is written during the event. Nothing pre-written is copied in.

---

## 1. Problem statement

Four-year students learn how a university works by osmosis over two years: which credits count, which clubs matter, which workshops happen, which programs open in August and close in September. **Transfer students arrive as juniors with half the time and none of the map.**

The failures are concrete:
- **Credits:** A counselor reads you the ASSIST.org page. Nobody tells you, *for your exact transcript and your exact majors*, what counts, what's missing, and in what order to take the rest. Hidden rules (e.g. "complete entire sequence at same institution prior to transfer", minimum grades, letter-grade-only) silently cost students a semester.
- **Opportunities:** Workshops from top AI companies, club-funded hackathon trips, open club positions, and programs with deadlines are scattered across club pages and department sites. Transfers find out after the deadline — or never.

**Named community:** California community-college transfer students at four-year universities (demo campuses: **SJSU** and **UC Berkeley**; sending college: **De Anza**).

**Founder story (lived problem):** Atishay transferred De Anza → SJSU (Data Science + Economics). His counselor read him ASSIST. He learned about a major AI-company student program only after it had closed.

---

## 2. Thesis (why this isn't "just ask ChatGPT")

> **ChatGPT answers the questions you know to ask. A transfer student's real problem is the questions they don't know to ask.**

Our product does three things a chat window cannot:
1. **Ground truth** — real ASSIST articulation agreements and live-scraped campus data, not model memory.
2. **It comes to you** — it watches campus on a schedule and alerts you *before* deadlines. Chat waits to be asked.
3. **It knows you** — your transcript, majors, and goals persist, so every recommendation is personal.

---

## 3. One-liner & elevator pitch

**One-liner:** An AI counselor for transfer students that knows your transcript and everything happening on campus — and tells you what you'd otherwise find out too late.

**Elevator pitch (30s):**
> "I transferred from De Anza to SJSU this fall. My counselor read me the ASSIST page. Nobody told me which of my credits actually count toward Data Science and Econ — or that the program I wanted had closed a month before I arrived. Four-year students figure this out over two years. Transfers get half the time. We read your transcript against official articulation data, map exactly what's left, and every day scan campus for the events, clubs, and opportunities that fit you — before the deadline, not after."

**Never pitch it as "a course planner."** Lead with the story and the catch.

---

## 4. Product: one loop, three pillars

```
            ┌──────────────── STUDENT PROFILE ────────────────┐
            │ transcript · target campus · majors · goals     │
            └────────────────────────┬────────────────────────┘
                                     │
     ┌───────────────────────────────┼───────────────────────────────┐
     ▼                               ▼                               ▼
 ACADEMICS                     CAMPUS RADAR                    OPPORTUNITIES
 what counts / what's left     events, workshops, clubs        funded trips, open club
 critical path                 that fit you                    positions, programs + deadlines
 (ASSIST, deterministic)       (Apify, scheduled)              (Apify + matcher)
     └───────────────────────────────┼───────────────────────────────┘
                                     ▼
                       CLAUDE — the counselor
             explains · prioritizes · plans · cites sources
                                     ▼
                  DROID — the agent that acts on a schedule
         runs scans · repairs broken scrapers · logs every step
```

---

## 5. Feature tiers (scope rules)

| Tier | Feature | Status by 2 PM Sat |
|---|---|---|
| **T1 — must work live** | Transcript upload → parsed courses → student confirms list | Required |
| **T1** | Deterministic articulation match vs real ASSIST: satisfied / partial / missing, with gotcha flags | Required |
| **T1** | Remaining requirements + semester plan respecting prerequisites | Required |
| **T1** | Campus Radar: scraped events/opportunities ranked for the profile | Required |
| **T1** | One opportunity alert with a deadline, explained by Claude | Required |
| **T1** | Agent log: Droid's scheduled run visible (plan, steps, results) | Required |
| **T2 — wow layer** | Interactive degree map (critical path highlighted) | If time |
| **T2** | What-if: add/remove a major → plan reflows live | If time |
| **T2** | Droid self-healing scraper with visible diff | If time (strong for Factory track) |
| **T2** | PWA push notification on phone | If time |
| **T3 — vision only (pitch slide, do NOT build)** | Club position matching, mentorship, admin/office navigator, recruiting timeline | Roadmap |

**Scope rule:** if a task isn't T1 and T1 isn't done, don't start it.

---

## 6. Accuracy & safety design (Anthropic track: "where could it go wrong")

- **Matching is deterministic code. Claude never decides whether a credit counts.** Claude explains, prioritizes, and plans on top of computed results.
- **Every academic claim cites its source** (ASSIST agreement key + requirement row, or catalog URL). UI shows the citation.
- **Transcript parsing is human-confirmed:** Claude extracts courses → student reviews/edits the list → only then do we match.
- **Uncertainty is explicit:** confidence badge per result; anything ambiguous says "confirm with your advisor" and drafts the question for them.
- **Opportunities link to the original source page.** No invented events, no invented deadlines.
- **Privacy:** transcripts stored in Supabase Storage under the user's profile only; never sent anywhere except the Claude API for parsing.

---

## 7. Tech stack

| Layer | Choice |
|---|---|
| Frontend | **Vite + React 19 + TypeScript**, PWA, plain CSS with design tokens (from Figma). Deployed on **Vercel** |
| Backend | **Python + FastAPI**. Deployed on Railway/Render (team picks in Phase 0) |
| Data / auth / files | **Supabase** (Postgres + Auth + Storage) |
| LLM | **Claude via Anthropic API** (model ID in env var `ANTHROPIC_MODEL`) |
| Scraping | **Apify** — custom Actor (Crawlee, JS/TS), called via `apify-client` from FastAPI |
| Agent | **Factory Droid SDK** (TS or Python per docs) — scheduled runs + scoped scraper repair |
| Design | **Figma** (with Figma Agent) |

### Monorepo layout
```
/
├── PROJECT.md  PHASES.md  TASKS.md  README.md
├── apps/
│   ├── web/                 # Vite React PWA
│   │   └── src/{routes,components,lib/api.ts,styles/tokens.css}
│   ├── api/                 # FastAPI
│   │   └── app/{main.py,routers/,services/,models/,data/}
│   └── actor/               # Apify Actor (campus scraper)
├── packages/
│   └── contracts/           # shared API types (TS) mirrored by Pydantic models
├── data/
│   └── requirements/        # curated upper-division major requirements (with source URLs)
└── .env.example
```

---

## 8. Data sources

### 8.1 ASSIST (articulation) — verified working
- **Handshake (required):** `GET https://assist.org/` first with a browser-like User-Agent; read the `X-XSRF-TOKEN` cookie; send it back as header `X-XSRF-TOKEN` on every API call. Without it the API returns **400**.
- `GET /api/institutions` → IDs. Known: **SJSU = 39**, **De Anza = 113**. Look up UC Berkeley at runtime (do not hardcode a guess).
- `GET /api/institutions/{sendingId}/agreements` → partner schools + year IDs.
- `GET /api/agreements?receivingInstitutionId=&sendingInstitutionId=&academicYearId=&categoryCode=major` → `reports[]` with `label` + `key`. **Match labels exactly** (e.g. `"Data Science, B.S."`, not substring — "Population Data Science" exists).
- `GET /api/articulation/Agreements?Key={key}` → full agreement.
- Year IDs: **77 = 2026–27**, 72 = 2021–22 (id = fall year − 1949).

**Agreement structure (critical):**
- `result.templateAssets` and `result.articulations` are **JSON strings inside JSON** → `json.loads` again.
- `templateAssets`: list of `RequirementGroup` / titles / `GeneralText` (HTML policy text). Each group has `instruction.type`:
  - `"Following"` → complete **all** courses in the group
  - `"NFromArea"` + `amount` → complete **N** of the listed courses
  - group `attributes` may hold rules like `"Minimum grade required: C or better"`
  - cells in `sections[].rows[].cells[]` each have an `id` (= `templateCellId`) and the receiving course
- `articulations`: list keyed by `templateCellId` → `sendingArticulation`:
  - `items[]` = CourseGroups; **within a group `courseConjunction` (usually `"And"`)**
  - `courseGroupConjunctions[]` = **`"Or"` between groups**
  - `noArticulationReason: "No Current Articulation"` → must be taken at the university
  - course-level `attributes` may contain **"Complete entire sequence at same institution prior to transfer"** → partial sequences earn nothing
- Sort everything by `position`; arrays are unordered.
- **Course renumbering:** CA community colleges now use common course numbers (e.g. `ENGL C1001`, `STAT C1000`). Older transcripts use old numbers. Match against the agreement **for the academic year the course was taken**; fall back to title + units similarity and flag low confidence.
- **Cache** every fetched agreement in Supabase (`articulation_cache`); the API is unofficial.

### 8.2 Major requirements beyond ASSIST
ASSIST covers lower-division prep. Upper-division requirements come from the university catalog. For the demo, curate **SJSU Data Science B.S.** and **SJSU Economics** (+ one Berkeley major if time) as JSON in `data/requirements/`, each item with `source_url`. Prerequisites stored as edges for the planner.

### 8.3 Campus Radar (Apify Actor)
Actor input: `{ campus, sources[] }`. Sources per campus (curated list from the team): event calendars, club directories, department news, AI/tech workshop pages, Devpost/MLH hackathon listings. Output normalized items:
```json
{ "title": "", "type": "event|workshop|club|program|hackathon|position",
  "org": "", "campus": "sjsu|berkeley", "starts_at": "", "deadline": "",
  "url": "", "description": "", "tags": [], "scraped_at": "" }
```
Publish the Actor for Apify's Best Actor award.

---

## 9. Supabase schema (v1)

```sql
profiles(id uuid pk, name text, sending_institution_id int, receiving_institution_id int,
         campus text, majors text[], goals text, interests text[], created_at timestamptz)
transcript_courses(id uuid pk, profile_id uuid fk, prefix text, number text, title text,
         units numeric, grade text, term text, academic_year_id int, confirmed bool)
articulation_cache(key text pk, sending_id int, receiving_id int, year_id int,
         major_label text, payload jsonb, fetched_at timestamptz)
match_results(id uuid pk, profile_id uuid fk, major_label text, result jsonb, created_at timestamptz)
plans(id uuid pk, profile_id uuid fk, semesters jsonb, created_at timestamptz)
opportunities(id uuid pk, campus text, type text, title text, org text, starts_at timestamptz,
         deadline timestamptz, url text unique, description text, tags text[], scraped_at timestamptz)
profile_opportunities(profile_id uuid, opportunity_id uuid, score numeric, reason text,
         notified bool, primary key(profile_id, opportunity_id))
agent_events(id uuid pk, run_id uuid, kind text, -- plan|step|diff|result|error
         message text, payload jsonb, created_at timestamptz)
```

---

## 10. API contract (frozen after Phase 0)

All responses JSON. Phase 0 stubs return exactly these shapes with mock data.

| Method | Path | Request | Response |
|---|---|---|---|
| POST | `/profiles` | `{name, campus, sending_institution_id, receiving_institution_id, majors[], goals, interests[]}` | `{profile}` |
| GET | `/profiles/{id}` | — | `{profile}` |
| POST | `/profiles/{id}/transcript` | multipart PDF/image | `{courses: Course[]}` (unconfirmed) |
| PUT | `/profiles/{id}/courses` | `{courses: Course[]}` | `{courses: Course[]}` (confirmed) |
| GET | `/assist/majors` | `?sending=&receiving=&year=` | `{majors: [{label, key}]}` |
| POST | `/profiles/{id}/match` | `{major_label}` | `MatchResult` |
| GET | `/profiles/{id}/plan` | `?majors=` | `{semesters: Semester[]}` |
| GET | `/profiles/{id}/opportunities` | — | `{items: RankedOpportunity[]}` |
| POST | `/profiles/{id}/counselor` | `{message, history[]}` | `{reply, citations: Citation[]}` |
| POST | `/agent/run` | `{campus}` | `{run_id}` |
| GET | `/agent/events` | `?run_id=` | `{events: AgentEvent[]}` |
| POST | `/webhooks/apify` | Apify payload | `{ok: true}` |

```ts
type Course = { prefix: string; number: string; title: string; units: number;
                grade: string; term: string; academic_year_id?: number; confirmed: boolean };
type Requirement = { id: string; group_title: string; rule: "all" | "n_of"; n?: number;
                     receiving_course: string; status: "satisfied" | "partial" | "missing" | "at_university";
                     satisfied_by: string[]; flags: string[]; // e.g. "sequence_rule", "min_grade_C"
                     citation: Citation; confidence: "high" | "medium" | "low" };
type MatchResult = { major_label: string; agreement_key: string; requirements: Requirement[];
                     summary: { satisfied: number; partial: number; missing: number; at_university: number } };
type Semester = { term: string; courses: { code: string; title: string; units: number;
                  reason: string; prereqs: string[] }[] };
type RankedOpportunity = { id: string; title: string; type: string; org: string; url: string;
                           starts_at?: string; deadline?: string; score: number; reason: string };
type Citation = { source: "assist" | "catalog" | "web"; label: string; url: string; ref?: string };
type AgentEvent = { run_id: string; kind: "plan" | "step" | "diff" | "result" | "error";
                    message: string; payload?: unknown; created_at: string };
```

---

## 11. Frontend routes

| Route | Purpose |
|---|---|
| `/onboarding` | campus, majors, goals → transcript upload → confirm courses |
| `/` (Today) | top alerts + deadlines + this week's picks |
| `/degree` | match results, gotcha flags, semester plan (T2: interactive map + what-if) |
| `/radar` | ranked events/opportunities with "why this fits you" |
| `/counselor` | Claude chat grounded in profile + results, with citations |
| `/agent` | Droid run log: plan → steps → diffs → results |

---

## 12. Sponsor track strategy

| Track | Their criteria | How we satisfy it |
|---|---|---|
| **Anthropic** | Named community; real lived problem; works Monday; thoughtful Claude use incl. where it could go wrong | Community = CA CC transfers. Founder lived it. Deterministic matching + citations + human-confirmed transcript = our failure-mode story |
| **Factory Droid SDK** | Droid does real work in the running product on a designed trigger; scoped permissions with safety; visible plans/steps/diffs; README explains where/how. Scores poorly: chatbot wrapper, slides-only, invisible agent | Droid runs on a **schedule** (and on new profile) → runs campus scans → matches → writes alerts. **Self-healing:** if a scraper breaks, Droid patches it, permission-scoped to `apps/actor/` only, and the diff shows in `/agent`. README section required |
| **Apify** | Meaningful use; top 5 projects + **Best Actor** for an Actor built for the event | Custom campus Actor is the Radar's data source; published to Apify Store |
| **Figma** | TBD (check the Figma track doc / booth) | All screens designed in Figma first (Figma Agent), files kept clean and linked in Devpost |

---

## 13. Demo script (2 minutes, judging)

1. **(15s) Story:** "My counselor read me ASSIST…"
2. **(40s) Academics:** upload Atishay's real transcript → confirm → match → show a **gotcha caught** (sequence rule / renumbered course / grade minimum) with its ASSIST citation → semester plan.
3. **(35s) Radar:** "Every morning it scans campus." Show `/agent` run log → ranked opportunities → one alert with a deadline and Claude's "why this fits you."
4. **(15s) Counselor:** ask "Can I graduate by Spring 2028 if I add Econ?" → cited answer.
5. **(15s) Close:** field-test numbers from Saturday + vision (every transfer, every campus on ASSIST).

---

## 14. Non-negotiables for anyone writing code (including Claude Code)

- Do not change an API contract shape without the integrator (Atishay) approving.
- No secrets in the repo. `.env` is gitignored; update `.env.example` when adding a variable.
- No mocked data in the final demo for Apify-sourced items or ASSIST results.
- Every academic claim shown to a user carries a citation.
- `main` always runs. Work on branches, open PRs, Atishay merges.
