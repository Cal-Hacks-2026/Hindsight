from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import APP_NAME, WEB_ORIGINS
from app.models import HealthResponse
from app.routers import agent, assist, profiles, webhooks

app = FastAPI(title=f"{APP_NAME} API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=WEB_ORIGINS,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(profiles.router)
app.include_router(assist.router)
app.include_router(agent.router)
app.include_router(webhooks.router)


@app.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    return HealthResponse(status="ok", app=APP_NAME)
