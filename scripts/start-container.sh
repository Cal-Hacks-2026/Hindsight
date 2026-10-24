#!/usr/bin/env bash
# One container, two processes (DECISIONS.md D-006): the public API on $PORT and the
# Droid agent on 127.0.0.1:8787 (not exposed). If either exits, the other is stopped
# and the container exits, so the host restarts it.
set -uo pipefail
cd "$(dirname "$0")/.."

PORT="${PORT:-8000}"
export AGENT_URL="${AGENT_URL:-http://127.0.0.1:8787}"
export AGENT_API_URL="${AGENT_API_URL:-http://127.0.0.1:${PORT}}"

(cd apps/api && exec .venv/bin/uvicorn app.main:app --host 0.0.0.0 --port "$PORT") &
api=$!

# The agent never needs the API's keys; it also scrubs its own env before starting Droid.
(cd apps/agent && exec env -u SUPABASE_SERVICE_ROLE_KEY -u APIFY_TOKEN -u APIFY_WEBHOOK_SECRET \
  -u ANTHROPIC_API_KEY node --import tsx src/main.ts) &
agent=$!

trap 'kill "$api" "$agent" 2>/dev/null' TERM INT
while kill -0 "$api" 2>/dev/null && kill -0 "$agent" 2>/dev/null; do sleep 2; done
kill "$api" "$agent" 2>/dev/null
wait
exit 1
