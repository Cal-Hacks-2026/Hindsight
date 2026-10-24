# Hindsight API + Droid agent in one container (DECISIONS.md D-006).
# Droid patches extractors on this container's disk and the API runs them from the same
# disk, so a patch reaches the very next re-scan. Patches don't survive a redeploy; each
# one is kept as a `diff` row in agent_events for a human to commit.
#
# Two OS users: the API runs as `node`; the agent (and so Droid) runs as `droid`, which
# can't read the API's environment, and owns only the extractors folder.
FROM node:22-bookworm-slim

RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates && rm -rf /var/lib/apt/lists/* \
  && useradd --create-home --uid 1001 droid
COPY --from=ghcr.io/astral-sh/uv:0.13.4 /uv /uvx /usr/local/bin/

USER node
WORKDIR /app
ENV UV_PYTHON_INSTALL_DIR=/home/node/.python UV_LINK_MODE=copy PYTHONUNBUFFERED=1

COPY --chown=node:node apps/api/pyproject.toml apps/api/uv.lock apps/api/.python-version apps/api/
RUN cd apps/api && uv sync --frozen --no-dev

COPY --chown=node:node apps/agent/package.json apps/agent/package-lock.json apps/agent/
RUN cd apps/agent && npm ci --omit=dev

COPY --chown=node:node data data
COPY --chown=node:node apps/api apps/api
COPY --chown=node:node apps/agent apps/agent
COPY --chown=node:node scripts/start-container.sh scripts/

# The only place Droid can write: owned by droid, readable by the API's group.
USER root
RUN chown -R droid:node apps/api/app/services/radar/extractors \
  && chmod 750 apps/api/app/services/radar/extractors && chmod 640 apps/api/app/services/radar/extractors/*

EXPOSE 8000
CMD ["scripts/start-container.sh"]
