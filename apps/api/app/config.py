import os

from dotenv import find_dotenv, load_dotenv

# Locally: the single .env at the repo root (see .env.example), found by walking up.
# Deployed: no .env exists and the host's env vars are used. Real env vars always win.
load_dotenv(find_dotenv())

APP_NAME = "Hindsight"

# Comma-separated list of allowed web origins for CORS.
WEB_ORIGINS = [
    o.strip()
    for o in os.getenv("WEB_ORIGIN", "http://localhost:5173").split(",")
    if o.strip()
]

# ASSIST academic year used for matching (id = fall year − 1949; 77 = 2026–27). A college pair
# with no agreements for it yet falls back to its latest published year (AssistService.year_for).
ASSIST_YEAR_ID = 77

# Universities with a profile campus of their own (Radar sources, curated requirements). Any other
# ASSIST university is "other": credits and community-college terms only, no Radar feed.
CAMPUS_BY_ASSIST_ID = {39: "sjsu", 79: "berkeley"}


def campus_for(receiving_institution_id: int) -> str:
    return CAMPUS_BY_ASSIST_ID.get(receiving_institution_id, "other")


def supabase_rest_url() -> str | None:
    """PostgREST base for SUPABASE_URL, which should be the project URL; a pasted
    `.../rest/v1` URL is accepted too."""
    url = (os.getenv("SUPABASE_URL") or "").strip().rstrip("/")
    if not url:
        return None
    return url if url.endswith("/rest/v1") else f"{url}/rest/v1"
