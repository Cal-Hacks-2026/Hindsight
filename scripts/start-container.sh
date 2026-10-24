#!/usr/bin/env bash
# One container, two processes (DECISIONS.md D-006): the public API on $PORT and the
# Droid agent on 127.0.0.1:8787 (not exposed). If either exits, the other is stopped
# and the container exits, so the host restarts it.
#
# As root (the container), the API runs as `node` and the agent as `droid`, so Droid
# can't read the API's environment; the agent gets AGENT_SECRET as a file it deletes
# after reading. Run as a normal user (local), both run as you.
set -uo pipefail
cd "$(dirname "$0")/.."

PORT="${PORT:-8000}"
export AGENT_URL="${AGENT_URL:-http://127.0.0.1:8787}"
export AGENT_API_URL="${AGENT_API_URL:-http://127.0.0.1:${PORT}}"

as_api=() as_agent=() agent_env=()
if [ "$(id -u)" = 0 ]; then
  as_api=(setpriv --reuid=node --regid=node --init-groups --inh-caps=-all)
  as_agent=(setpriv --reuid=droid --regid=droid --init-groups --inh-caps=-all)
  secret_file="$(mktemp /tmp/agent-secret.XXXXXX)"
  printf '%s' "${AGENT_SECRET:-}" > "$secret_file"
  chown droid:droid "$secret_file" && chmod 400 "$secret_file"
  agent_env=(-u AGENT_SECRET AGENT_SECRET_FILE="$secret_file" HOME=/home/droid)
fi

(cd apps/api && exec "${as_api[@]}" .venv/bin/uvicorn app.main:app --host 0.0.0.0 --port "$PORT") &
api=$!

# The agent never needs the API's keys; it also scrubs its own env before starting Droid.
(cd apps/agent && exec "${as_agent[@]}" env -u SUPABASE_SERVICE_ROLE_KEY -u APIFY_TOKEN -u APIFY_WEBHOOK_SECRET \
  -u ANTHROPIC_API_KEY "${agent_env[@]}" node --import tsx src/main.ts) &
agent=$!

trap 'kill "$api" "$agent" 2>/dev/null' TERM INT
while kill -0 "$api" 2>/dev/null && kill -0 "$agent" 2>/dev/null; do sleep 2; done
kill "$api" "$agent" 2>/dev/null
wait
exit 1
