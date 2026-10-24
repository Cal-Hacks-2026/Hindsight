from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.config import APP_NAME, WEB_ORIGINS
from app.models import HealthResponse
from app.routers import agent, assist, profiles, webhooks
from app.routers.profiles import TRANSCRIPT_NOTES_HEADER
from app.services.claude_limits import RateLimited

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

app.include_router(profiles.router)
app.include_router(assist.router)
app.include_router(agent.router)
app.include_router(webhooks.router)


@app.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    return HealthResponse(status="ok", app=APP_NAME)
