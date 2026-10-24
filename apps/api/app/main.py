import logging

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.config import APP_NAME, WEB_ORIGINS
from app.models import HealthResponse
from app.routers import agent, assist, internal_agent, profiles, webhooks
from app.routers.profiles import TRANSCRIPT_NOTES_HEADER
from app.services.claude_limits import RateLimited
from app.services.db import StoreError, StoreNotConfigured

log = logging.getLogger(__name__)

app = FastAPI(title=f"{APP_NAME} API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=WEB_ORIGINS,
    allow_methods=["*"],
    allow_headers=["*"],
    # Not CORS-safelisted, so the browser hides them unless exposed.
    expose_headers=[TRANSCRIPT_NOTES_HEADER, "Retry-After"],
)


@app.exception_handler(RateLimited)
async def rate_limited(request: Request, exc: RateLimited) -> JSONResponse:
    return JSONResponse(status_code=429, content={"detail": exc.detail},
                        headers={"Retry-After": str(exc.retry_after)})


@app.exception_handler(StoreError)
async def store_error(request: Request, exc: StoreError) -> JSONResponse:
    # The message can carry Supabase's error body; keep that in the server log only.
    log.error("storage error on %s %s: %s", request.method, request.url.path, exc)
    detail = "Storage is not configured" if isinstance(exc, StoreNotConfigured) else "Storage is unavailable"
    return JSONResponse(status_code=exc.status, content={"detail": detail})

app.include_router(profiles.router)
app.include_router(assist.router)
app.include_router(agent.router)
app.include_router(webhooks.router)
app.include_router(internal_agent.router)


@app.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    return HealthResponse(status="ok", app=APP_NAME)
