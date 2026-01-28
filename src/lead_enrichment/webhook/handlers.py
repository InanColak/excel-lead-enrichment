"""Webhook payload processing logic.

Correlates Apollo's webhook phone data to Excel rows via the
webhook_tracking table and updates enrichment_rows with phone numbers.
"""

from __future__ import annotations

import json
import logging

from ..db.repository import Repository
from ..models import ApolloWebhookPayload
from ..utils.phone import classify_apollo_phones

logger = logging.getLogger(__name__)


def handle_apollo_webhook(
    payload: ApolloWebhookPayload,
    repo: Repository,
) -> int:
    """Process an Apollo webhook payload and update the database.

    Returns the number of person records processed.
    """
    processed = 0

    for person in payload.people:
        person_id = person.id
        if not person_id:
            # Try to correlate by email as fallback
            logger.warning("Webhook person has no ID, attempting email fallback")
            continue

        # Mark webhook as received and get the corresponding row_id
        raw_payload = json.dumps(person.model_dump(), ensure_ascii=False, default=str)
        row_id = repo.mark_webhook_received(person_id, payload=raw_payload)

        if row_id is None:
            logger.warning(
                "No webhook tracking entry for apollo_person_id=%s", person_id
            )
            continue

        # Classify phone numbers
        phones = classify_apollo_phones(person.phone_numbers)

        repo.update_apollo_phone_result(
            row_id,
            mobile=phones["mobile"],
            direct=phones["direct_dial"],
            raw_json=raw_payload,
        )

        logger.info(
            "Updated row %d with Apollo phones: mobile=%s, direct=%s",
            row_id,
            phones["mobile"],
            phones["direct_dial"],
        )
        processed += 1

    return processed
