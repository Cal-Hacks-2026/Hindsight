import hmac
import logging
import os
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Body, Header, HTTPException

from app.models import WebhookResponse
from app.services.radar import scan, store

log = logging.getLogger(__name__)

router = APIRouter(prefix="/webhooks", tags=["webhooks"])


def _ingest(run_id: str) -> None:
    try:
        scan.ingest_run(run_id)
    except (scan.ScanError, store.StoreError) as e:
        log.error("radar: ingesting Apify run %s failed: %s", run_id, e)


@router.post("/apify", response_model=WebhookResponse)
def apify(background: BackgroundTasks, payload: dict[str, Any] = Body(...),
          secret: str | None = Header(None, alias=scan.WEBHOOK_SECRET_HEADER)) -> WebhookResponse:
    """Apify ad-hoc webhook (set by scan.start_scan) → upsert the run's items in the background.

    Only the run id is taken from the body; ingest_run re-reads the run from Apify.
    """
    expected = os.getenv("APIFY_WEBHOOK_SECRET")
    if not expected:
        raise HTTPException(status_code=503, detail="Webhook not configured")
    if not secret or not hmac.compare_digest(secret, expected):
        raise HTTPException(status_code=401, detail="Bad webhook secret")

    event = payload.get("eventType")
    run_id = (payload.get("eventData") or {}).get("actorRunId")
    if event != "ACTOR.RUN.SUCCEEDED":
        log.info("radar: ignoring Apify %s for run %s", event, run_id)
        return WebhookResponse(ok=True)
    if not isinstance(run_id, str) or not scan.RUN_ID.match(run_id):
        raise HTTPException(status_code=422, detail="Missing eventData.actorRunId")
    background.add_task(_ingest, run_id)
    return WebhookResponse(ok=True)
