# PHASES.md — Build Timeline

> Build window: **Fri 8:30 PM → Sat 2:00 PM (≈17.5 hrs).** Build freeze at 2:00 PM sharp.
> Each phase ends with a **checkpoint**: everything merged to `main`, deployed, and the demo path still works.
> Scope rules and contracts live in `PROJECT.md`. Owners live in `TASKS.md`.

---

## Overview

| Phase | Window | Goal | Exit criteria (checkpoint) |
|---|---|---|---|
| **0 — Foundation** | Fri 8:30 PM – 12:30 AM | Walking skeleton: every layer exists and connects | Stubbed end-to-end slice live on Vercel + API host |
| **1 — Academics core** | 12:30 AM – 4:30 AM | Real transcript → real ASSIST match → plan | Atishay's transcript produces a cited match + plan |
| **2 — Campus Radar** | 4:30 AM – 8:30 AM | Apify Actor → opportunities → ranked feed | Real scraped items ranked for a profile, in the UI |
| **3 — Counselor + Droid** | 8:30 AM – 11:30 AM | Claude counselor + scheduled Droid runs + agent log | Droid run visible end-to-end in `/agent`; counselor answers with citations |
| **4 — Wow + freeze** | 11:30 AM – 2:00 PM | T2 polish, bug bash, deploy, freeze | Demo script runs 3× clean on deployed URL |
| After freeze | Sat 2:00 PM → Sun 8:50 AM | Field testing, video, Devpost, pitch | Submitted by **8:50 AM Sunday** |

**Sync points (5 min, all four people):** 12:30 AM, 4:30 AM, 8:30 AM, 11:30 AM, 2:00 PM.
**Sleep:** coders take staggered 60–90 min naps (one at a time) only after a checkpoint passes.

---

## Phase 0 — Foundation (Fri 8:30 PM – 12:30 AM) · Owner: Atishay

**Goal:** a thin, ugly, end-to-end system with frozen interfaces, so work can fan out without collisions.

1. **Repo scaffold** (monorepo layout per PROJECT.md §7): `apps/web`, `apps/api`, `apps/actor`, `packages/contracts`, `data/requirements`, `.env.example`, `.gitignore` (include `.env`, `node_modules`, `__pycache__`, `.venv`).
2. **Supabase:** create project, run schema from PROJECT.md §9, enable Storage bucket `transcripts`, put keys in `.env`.
3. **FastAPI skeleton:** every endpoint in PROJECT.md §10 exists and returns **mock data in the exact contract shape**. CORS for the web origin. `/health` endpoint.
4. **Contracts:** TS types in `packages/contracts`, mirrored Pydantic models in `apps/api/app/models`.
5. **Web shell:** Vite + React 19 + TS, routes from PROJECT.md §11, `lib/api.ts` typed client, `styles/tokens.css` placeholder tokens, PWA manifest.
6. **Thin slice:** `/onboarding` → upload file → stub `/transcript` → confirm → stub `/match` → render on `/degree`.
7. **Deploy:** web → Vercel; api → Railway or Render. Env vars set in both.
8. **Branch protection on `main`** (PRs required, Atishay merges).

**Parallel during Phase 0 (no foundation conflicts):**
- Shiv: standalone ASSIST client module + parser + And/Or evaluator with unit tests against a saved agreement (module only, no API wiring yet).
- Amaan + Dhana: user interviews on the floor; curated source URL list for SJSU + Berkeley.

**Checkpoint 12:30 AM:** deployed URL shows the stubbed slice working; contracts frozen.

---

## Phase 1 — Academics core (12:30 AM – 4:30 AM)

1. Plug Shiv's ASSIST module into `/assist/majors` and `/profiles/{id}/match` (with `articulation_cache`).
2. **Transcript parsing:** PDF/image → Claude → `Course[]`; confirm screen edits and saves.
3. **Matcher:** evaluate `Following` / `NFromArea`, And/Or groups, `noArticulationReason`, sequence rule, grade minimums; per-requirement status + flags + citation + confidence.
4. **Course renumbering handling:** year-of-course agreement lookup; similarity fallback flagged low confidence.
5. Curate `data/requirements/` for SJSU Data Science B.S. + Economics (with `source_url`).
6. **Planner v1:** remaining requirements → semesters, respecting prereq edges and a unit cap.
7. UI: `/degree` real results — status chips, gotcha flags, citation links, semester plan.

**Checkpoint 4:30 AM:** Atishay's real transcript → correct match with ≥1 gotcha surfaced → plan renders.

---

## Phase 2 — Campus Radar (4:30 AM – 8:30 AM)

1. **Apify Actor** (`apps/actor`, Crawlee): input `{campus, sources[]}`, output normalized items (PROJECT.md §8.3). Start with 3–5 reliable sources per campus.
2. FastAPI triggers the Actor via `apify-client`; `/webhooks/apify` upserts into `opportunities` (dedupe on `url`).
3. **Ranking:** score each opportunity vs profile (majors, goals, interests, deadline urgency); Claude writes the one-line `reason`.
4. UI: `/radar` ranked list with "why this fits you", deadline countdown, source link; `/` (Today) shows top 3 + nearest deadline.
5. Publish the Actor to the Apify Store (Best Actor eligibility).

**Checkpoint 8:30 AM:** real scraped items for SJSU + Berkeley, ranked for a profile, visible in UI.

---

## Phase 3 — Counselor + Droid (8:30 AM – 11:30 AM)

1. **Counselor:** `/counselor` endpoint grounded in profile + match results + plan + top opportunities; must return `citations[]`; refuses to assert credit decisions not in computed results.
2. **Droid integration (Factory Droid SDK):**
   - Trigger: schedule (cron) + "new profile created".
   - Job: run campus scan → rank → write alerts; log `plan` / `step` / `result` to `agent_events`.
   - Scope: Droid may only modify files in `apps/actor/`; no network writes beyond our API.
3. UI: `/agent` timeline of runs (plan → steps → results), live-refresh polling.
4. README section: where and how Droid is used (required by Factory track).

**Checkpoint 11:30 AM:** trigger a run → watch it in `/agent` → new alert appears on Today; counselor answers the demo question with citations.

---

## Phase 4 — Wow + freeze (11:30 AM – 2:00 PM)

Pick in this order; stop when time runs out:
1. **Droid self-healing scraper:** break a selector on purpose → Droid detects failed scrape → patches `apps/actor/` → diff shown in `/agent` → re-run succeeds.
2. **Interactive degree map** with critical path highlighted.
3. **What-if:** toggle Econ double major → plan reflows.
4. **PWA push** for one alert on a phone.

Then, non-negotiable from **1:15 PM**:
- Bug bash on the deployed URL, run the demo script (PROJECT.md §13) **3× clean**.
- Seed a demo profile; pre-warm caches.
- **2:00 PM: freeze.** Only bug fixes after this, merged by Atishay.

---

## After freeze (non-build)

| When | What |
|---|---|
| Sat 2:00 – 6:00 PM | Field testing with transfer students on the floor; log numbers + quotes; film |
| Sat evening | Demo video (2–3 min), Devpost **draft submitted**, screenshots |
| Sat night | Pitch rehearsal ×5; prepare answers: "how do you know it's right?", "what's real vs mocked?", "who uses this Monday?" |
| **Sun 8:50 AM** | **Devpost final.** Select every sponsor track. Add all four teammates |
| Sun 10:30 AM | Whole team at the table for judging |
