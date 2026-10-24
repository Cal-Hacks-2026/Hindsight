# TASKS.md — Who Does What

> Timeline lives in `PHASES.md`. Contracts and scope live in `PROJECT.md`.
> **Atishay is the integrator:** he builds the foundation, owns `main`, and reviews/merges every PR.

## Team

| Person | GitHub | Role |
|---|---|---|
| **Atishay Pahadiya** | `atishaypahadiya` | Foundation, integration, frontend, Figma, product + pitch lead |
| **Shivendra Bhagat (Shiv)** | `sh1vendra` | Backend intelligence: ASSIST, matching, transcript parsing, Claude, Apify, Droid |
| **Amaan Shaghel** | `amaanshaghel` | Research, sponsor liaison, field testing, video |
| **Dhana Karthikeya Ventrapragada** | `vdkarthikeya` | Data curation, Devpost, pitch deck, field testing |

---

## Atishay — foundation + integration + experience

| Phase | Task | Done when |
|---|---|---|
| 0 | Monorepo scaffold, `.env.example`, `.gitignore`, branch protection | Repo pushed, Shiv pulled |
| 0 | Supabase project + schema + Storage bucket | Tables exist, keys in `.env` |
| 0 | FastAPI skeleton: all endpoints stubbed in contract shape | Mock JSON matches PROJECT.md §10 |
| 0 | Contracts: TS types + Pydantic mirrors | Both compile |
| 0 | Vite web shell: routes, typed API client, tokens, PWA manifest | Routes render |
| 0 | Thin slice + deploy (Vercel + API host) | Live URL works end-to-end on stubs |
| 1 | Figma: key screens (Onboarding, Today, Degree, Radar, Agent) | Shared Figma link |
| 1 | `/onboarding` + confirm-courses UI on real endpoints | Real transcript flows through |
| 1 | `/degree`: status chips, gotcha flags, citations, plan | Matches real results |
| 2 | `/radar` + Today: ranked feed, reasons, deadlines | Real items render |
| 3 | `/counselor` chat UI with citations; `/agent` timeline | Both live |
| 3 | Integrate Droid UI + README Droid section (with Shiv) | Factory criteria met |
| 4 | T2 wow features, demo seed, bug bash, freeze | Demo 3× clean |
| All | **Review + merge every PR; keep `main` deployable** | — |

## Shiv — data + intelligence

| Phase | Task | Done when |
|---|---|---|
| 0 | ASSIST client module: XSRF handshake, institutions, majors, agreement fetch (exact label match) | Unit test fetches De Anza → SJSU DS agreement |
| 0 | Agreement parser: double `json.loads`, sort by `position`, groups/cells/articulations joined | Typed parsed object |
| 0 | And/Or evaluator: `Following`, `NFromArea`, And within group, Or between groups, `noArticulationReason`, sequence rule, grade min | Tests pass on saved agreement |
| 1 | Wire into `/assist/majors` + `/match` with `articulation_cache` | Stub replaced, contract unchanged |
| 1 | Transcript parsing (Claude) → `Course[]`; renumbering fallback + confidence | Atishay's transcript parses correctly |
| 1 | Planner v1 using `data/requirements/` prereq edges | `/plan` returns real semesters |
| 2 | Apify Actor (`apps/actor`): normalized output, 3–5 sources per campus | Actor run returns items |
| 2 | `/webhooks/apify` upsert + ranking + Claude `reason` | `/opportunities` real |
| 2 | Publish Actor to Apify Store | Public listing |
| 3 | Counselor endpoint: grounded context + `citations[]` | Demo question answered with citations |
| 3 | Droid: schedule + new-profile trigger, scan job, `agent_events` logging, scope to `apps/actor/` | Run visible in `/agent` |
| 4 | Droid self-healing scraper (break → detect → patch → diff → re-run) | Diff visible in UI |

## Amaan — research, sponsors, field, film

| When | Task | Deliverable |
|---|---|---|
| Fri night | Interview 10+ transfer students on the floor: "What did you find out too late?" | Quotes doc (names only with consent) |
| Sat 9–11 AM | Visit Factory, Apify, Figma, Anthropic booths: confirm exact judging criteria + any requirements | Notes posted in team chat; flag anything that changes scope to Atishay immediately |
| Sat 2–6 PM | Run field tests: students try the app; log tried / completed / rating | Numbers + reactions sheet |
| Sat 2–6 PM | Film on phone (with consent): hands on phone, reactions, team building | Raw clips folder |
| Sat night | Rough-cut demo video (2–3 min), upload unlisted to YouTube | Link for Devpost |

## Dhana — data, Devpost, pitch

| When | Task | Deliverable |
|---|---|---|
| Fri night | Source list for SJSU + Berkeley: event calendars, club directories, dept news, AI workshop pages, Devpost/MLH | `data/sources.json` via PR (Shiv/Atishay review) |
| Fri night | Collect 3–5 real test transcripts from transfer students (with consent; redact names/IDs) | Test files shared privately, **not committed** |
| Sat AM | Draft Devpost page: inspiration, what it does, how we built it, challenges, what's next, track-by-track section | Draft saved on Devpost |
| Sat PM | Pitch deck (5 slides max): story, problem, live demo placeholder, how it's built, vision | Deck link |
| Sat PM | Help run field tests with Amaan | — |
| Sat night | Finalize Devpost: screenshots, video link, all teammates added, **every sponsor track selected** | Submitted draft |

---

## Git rules

- Branches: `atishay/<feature>`, `shiv/<feature>`, `data/<topic>`.
- Small PRs, at least every 1–2 hours. Atishay merges.
- Never change a contract shape without Atishay's sign-off.
- Pull before starting work; never force-push `main`.
- Secrets only in `.env` (shared via DM), never committed.

## Escalation

Anything blocked for **>30 min** → say it in team chat with what you tried. If a T1 item is at risk at a checkpoint, we cut T2 work first.
