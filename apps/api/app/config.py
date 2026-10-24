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

# ASSIST academic year used for matching (id = fall year − 1949; 77 = 2026–27).
ASSIST_YEAR_ID = 77
