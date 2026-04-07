import logging
from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException, status
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.contacts.models import Contact
from app.deps import get_db
from app.enrichment.schemas import ApolloWebhookPayload
from app.jobs.models import Job, JobRow

logger = logging.getLogger(__name__)

router = APIRouter(tags=["webhooks"])


@router.post("/webhooks/apollo", status_code=200)
async def receive_apollo_webhook(
    payload: ApolloWebhookPayload,
    x_apollo_secret: str = Header(..., alias="X-Apollo-Secret"),
    db: AsyncSession = Depends(get_db),
):
    """Receive Apollo phone-data webhook callback.

    Per D-42: authenticates via X-Apollo-Secret shared secret header.
    Per D-44: correlates to contact via apollo_id (person.id in webhook payload).
    Per D-46: accepts late webhooks — always updates contact phone if empty.
    Per Pitfall 3: uses SELECT FOR UPDATE to prevent race with timeout checker.
    Returns 200 immediately on valid requests.
    """
    # D-42: Validate shared secret
    if x_apollo_secret != settings.apollo_webhook_secret:
        logger.warning("Webhook rejected: invalid X-Apollo-Secret header")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid webhook secret",
        )

    updated_count = 0

    for person in payload.people:
        if not person.id:
            continue

        # D-44: Find contact by apollo_id using SELECT FOR UPDATE (Pitfall 3)
        result = await db.execute(
            select(Contact)
            .where(Contact.apollo_id == person.id)
            .with_for_update()
        )
        contact = result.scalar_one_or_none()

        if not contact:
            logger.warning(f"Webhook received for unknown apollo_id: {person.id}")
            continue

        # Extract best phone number from waterfall
        phone_number = _extract_best_phone(person)
        if not phone_number:
            continue

        # D-46: Update phone only if not already set (idempotent)
        # Late webhooks still update if phone is empty
        if not contact.phone:
            contact.phone = phone_number
            updated_count += 1
            logger.info(f"Updated phone for contact apollo_id={person.id}")

        # Increment webhook_callbacks_received on all jobs that reference this contact
        job_rows_result = await db.execute(
            select(JobRow.job_id)
            .where(JobRow.contact_id == contact.id)
            .distinct()
        )
        job_ids = [row[0] for row in job_rows_result.all()]

        for job_id in job_ids:
            await db.execute(
                update(Job)
                .where(Job.id == job_id)
                .values(webhook_callbacks_received=Job.webhook_callbacks_received + 1)
            )

    return {"status": "ok", "contacts_updated": updated_count}


def _extract_best_phone(person) -> Optional[str]:
    """Extract the best phone number from webhook person payload.
    Prefers sanitized_number. Picks first valid_number or highest confidence.
    """
    if not person.waterfall or not person.waterfall.phone_numbers:
        return None

    # Prefer valid numbers with sanitized format
    for phone in person.waterfall.phone_numbers:
        if phone.status_cd == "valid_number" and phone.sanitized_number:
            return phone.sanitized_number

    # Fallback: any sanitized number
    for phone in person.waterfall.phone_numbers:
        if phone.sanitized_number:
            return phone.sanitized_number

    # Last resort: raw number
    for phone in person.waterfall.phone_numbers:
        if phone.raw_number:
            return phone.raw_number

    return None
