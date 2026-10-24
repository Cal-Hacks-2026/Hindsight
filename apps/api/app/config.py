import os
from pathlib import Path

from dotenv import load_dotenv

# Single .env at the repo root (see .env.example). Real env vars win.
load_dotenv(Path(__file__).resolve().parents[3] / ".env")

APP_NAME = "Hindsight"

# Comma-separated list of allowed web origins for CORS.
WEB_ORIGINS = [
    o.strip()
    for o in os.getenv("WEB_ORIGIN", "http://localhost:5173").split(",")
    if o.strip()
]
