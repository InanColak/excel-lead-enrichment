"""FastAPI webhook server that receives Apollo phone number callbacks."""

from __future__ import annotations

import logging

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from ..models import ApolloWebhookPayload

logger = logging.getLogger(__name__)

app = FastAPI(title="Apollo Webhook Receiver", docs_url=None, redoc_url=None)


@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}


@app.post("/webhook/apollo")
async def receive_apollo_webhook(request: Request) -> JSONResponse:
    """Receive phone number data from Apollo.

    Apollo POSTs this payload asynchronously after a people/match call
    with reveal_phone_number=true. We parse the phone numbers and
    update the database via the handler.
    """
    from .handlers import handle_apollo_webhook

    body = await request.json()
    logger.info("Received Apollo webhook payload")

    try:
        payload = ApolloWebhookPayload.model_validate(body)
        repo = request.app.state.repo
        processed = handle_apollo_webhook(payload, repo)
        logger.info("Processed %d person(s) from webhook", processed)
        return JSONResponse({"status": "received", "processed": processed})
    except Exception:
        logger.exception("Error processing Apollo webhook")
        # Return 200 anyway so Apollo doesn't retry endlessly
        return JSONResponse({"status": "error"}, status_code=200)
