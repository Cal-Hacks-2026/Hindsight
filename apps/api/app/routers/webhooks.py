from typing import Any

from fastapi import APIRouter, Body

from app.models import WebhookResponse

router = APIRouter(prefix="/webhooks", tags=["webhooks"])


@router.post("/apify", response_model=WebhookResponse)
def apify(payload: dict[str, Any] = Body(...)) -> WebhookResponse:
    # Phase 2: verify the webhook, fetch the run's dataset, upsert into opportunities (dedupe on url).
    return WebhookResponse(ok=True)
