# Hindsight

*Everything you'd wish you knew, before you need it.*

An AI counselor for California community-college transfer students. See `PROJECT.md` (what/why), `PHASES.md` (timeline), `TASKS.md` (owners).

## Layout

```
apps/web            Vite + React 19 + TS PWA (plain CSS)
apps/api            FastAPI (Python, uv) — Phase 0 endpoints return mock data
apps/api/supabase   schema.sql (PROJECT.md §9)
apps/agent          Droid service (Factory Droid SDK, Node/TS): scheduled + triggered Radar runs
apps/actor          Placeholder; Radar uses Apify's Cheerio Scraper instead (DECISIONS.md D-002)
packages/contracts  Shared API types (PROJECT.md §10), mirrored in apps/api/app/models
data/requirements   Curated upper-division requirements (Phase 1)
```

## Run locally

Prereqs: Node 20+, Python 3.12+, [uv](https://docs.astral.sh/uv/).

```bash
cp .env.example .env        # one .env at the repo root, read by both apps
npm install                 # installs web + contracts workspaces

# terminal 1 — API on http://localhost:8000 (docs at /docs)
cd apps/api && uv run uvicorn app.main:app --reload --port 8000

# terminal 2 — web on http://localhost:5173
npm run dev:web
```

Optional, terminal 3 — the Droid agent (see "Where Droid runs" below):

```bash
cd apps/agent && npm install && npm start   # needs FACTORY_API_KEY and AGENT_SECRET in .env
```

Checks:

```bash
cd apps/api && uv run pytest     # contract smoke tests for every endpoint
npm run typecheck                # web + contracts
cd apps/agent && npm test && npm run typecheck
```

## Contracts

`packages/contracts/src/index.ts` and `apps/api/app/models/contracts.py` must stay in lockstep. Shapes are frozen after Phase 0 — changes need Atishay's sign-off.

## Where Droid runs (Factory Droid SDK)

Droid is the agent that keeps Campus Radar fresh. It does real work in the running product, not in a chat window.

**What it does.** Each run, Droid (through `@factory/droid-sdk` in `apps/agent`):

1. writes a plan (its TodoWrite list),
2. scans the campus's sources on Apify (`scan_campus`),
3. **self-heals**: if a source comes back `empty` or with an `extractor_error`, it reads the fetched page data and that source's extractor, patches the extractor with the smallest fix, and re-runs the scan's extraction on the same fetched pages (`rescan`) to confirm the source is `ok`,
4. re-ranks every profile's Radar feed (`rank_profiles`),
5. writes alerts (`write_alerts`): a profile's top 5 ranked items whose deadline (or start) is within 7 days get `notified = true`,
6. finishes with a structured summary.

Every plan, step, diff, result, and error is a row in Supabase `agent_events`, served by `GET /agent/events?run_id=`, which the `/agent` page reads. A patch is recorded as a `diff` row with the unified diff.

**Triggers.**
- Schedule: every `AGENT_INTERVAL_MINUTES` (default 120, to conserve credits; `0` turns it off) for each campus in `AGENT_CAMPUSES`.
- Manual: `POST /agent/run {campus}` (the demo button). A click within `AGENT_MANUAL_COOLDOWN_MINUTES` (default 2) of the last manual run for that campus returns that run's id, instead of starting another paid run.
- New profile: `POST /profiles` hands the agent a `profile_created` run that ranks and alerts for that profile only (no scan). Since anyone can create a profile, at most `AGENT_PROFILE_RUNS_PER_HOUR` (default 6) of these start a Droid session; past that, the agent ranks and alerts directly and logs why.

**How it runs.** The Node SDK starts the `droid` CLI (npm package `droid`, pinned in `apps/agent`) as a local subprocess and talks to it over stdio. There's no daemon; the model runs on Factory's side with `FACTORY_API_KEY`, and tools run on this machine. In production the API and the agent share one container (`Dockerfile`, `scripts/start-container.sh`). The API is public on `$PORT`, and the agent listens only on `127.0.0.1:8787`. They have to share a disk: Droid patches extractor files, and the API runs them on the next re-scan. A redeploy resets patches; the `diff` rows are how a human turns a good patch into a PR. **Droid never commits.**

```
web /agent ──GET /agent/events──────────────────────────┐
web "Run now" ──POST /agent/run──► API ──POST /runs──► apps/agent ──stdio──► droid CLI ──► Factory model
POST /profiles ─────────────────► API ──POST /runs──►     │  ▲                    │
                                  ▲                       │  └─ schedule           │ tools: scan_campus, get_source_raw,
                                  └── /internal/agent/* ◄─┘   (AGENT_SECRET)       │ rescan, rank_profiles, write_alerts,
                                      scan · rescan · raw · rank · alerts · events │ ApplyPatch on extractors/ only
```

**What Droid can touch (DECISIONS.md D-003, D-006).**
- **Edits:** only `apps/api/app/services/radar/extractors/<kind>.py`, and within that only the files whose sources failed in this run. Edits must be in-place updates (no creating, deleting, or moving files), with at most `AGENT_MAX_PATCHES` (default 4) per run. It's enforced in `apps/agent/src/policy.ts`. The session runs at autonomy **Off**, so every call with a side effect asks that handler first, including calls made inside Droid's Script tool or by a subagent. The handler refuses everything else.
- **No shell, no web.** Shell commands, URL fetches, and web searches all ask for permission and are always refused. Droid reaches the outside world only through our five tools, which are bound to the run's campus (and profile). Droid never sees a profile id.
- **No secrets.** Droid's Read tool can't be gated, so the container keeps secrets out of its reach rather than out of its sight:
  - The agent, and so Droid, runs as its own OS user (`droid`). The API runs as `node`, so Droid can't read the API's environment through `/proc`. The API also marks itself non-dumpable, so even processes running as `node` can't read it.
  - The start script withholds the Supabase, Apify, and Anthropic keys from the agent. It passes `AGENT_SECRET` as a file the agent deletes after reading, and the agent strips its environment to a short allowlist before starting Droid (the SDK passes `process.env` to the CLI).
  - What's left is Droid's own Factory key. The run log redacts it, `AGENT_SECRET`, and anything shaped like an API key before writing, since the log is public.
  - `/internal/agent/*` accepts only loopback connections, so even a leaked `AGENT_SECRET` is useless from outside the container.
  - The API refuses to read an extractor that is a symlink or not a regular file, and the permission handler refuses to patch one, since Droid's user owns that folder.
  - When you run it locally, both processes run as you and the repo-root `.env` is readable. The container has no `.env`.
- **Run logs carry no profile ids.** `/agent/events` is public and a profile id works like a password (it's how a student gets back to their profile), so the internal rank and alerts endpoints return counts and opportunities only.
- **Patched code runs in its own process.** The API runs extractors in a separate Python process (`extract_worker.py`): an empty environment, isolated mode, a timeout, and JSON in and out, all re-validated. A patch can't reach the API's keys or memory.
  - Inside that process, `extract.py` still checks the code first: only allowlisted `from X import Y` imports (`json`, `re`, `html`, `datetime`, `defusedxml`, our helpers), no `open`/`eval`/introspection, no underscore or frame attributes, no `match`, no attribute assignment, and a reduced set of Python built-ins.
  - Each call gets a copy of its source config, and a broken or refused extractor fails only its own sources.
  - The rules that make an item safe to show (http(s) URL, real title, dates only from the source, dedupe) live in `normalize.py`, outside Droid's folder.
- **Page data is untrusted.** Fetched pages reach Droid labelled as third-party data, and the prompt tells it to ignore any instructions inside them. The permission scope above is what limits the damage if it doesn't.

**Try it.** `cd apps/agent && npm run smoke:live` runs one real Droid session against a temporary copy of `extractors/` with `localist.py` deliberately broken and a stubbed API. It uses Factory credits but writes nothing to Supabase or Apify. Droid should patch the extractor, the run should log the diff, and the re-run should report the source `ok`.

**Env.** `FACTORY_API_KEY`, `AGENT_SECRET` (shared by API and agent), `AGENT_INTERVAL_MINUTES`, `AGENT_CAMPUSES`, optional `DROID_MODEL`, `AGENT_MAX_PATCHES`, `AGENT_RUN_TIMEOUT_MINUTES`, `AGENT_PROFILE_RUNS_PER_HOUR`; see `.env.example`.
