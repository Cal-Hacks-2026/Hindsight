# Hindsight

*Everything you'd wish you knew, before you need it.*

An AI counselor for California community-college transfer students. See `PROJECT.md` (what/why), `PHASES.md` (timeline), `TASKS.md` (owners).

## Layout

```
apps/web            Vite + React 19 + TS PWA (plain CSS)
apps/api            FastAPI (Python, uv) — Phase 0 endpoints return mock data
apps/api/supabase   schema.sql (PROJECT.md §9)
apps/actor          Apify Actor (Phase 2)
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

Checks:

```bash
cd apps/api && uv run pytest     # contract smoke tests for every endpoint
npm run typecheck                # web + contracts
```

## Contracts

`packages/contracts/src/index.ts` and `apps/api/app/models/contracts.py` must stay in lockstep. Shapes are frozen after Phase 0 — changes need Atishay's sign-off.
