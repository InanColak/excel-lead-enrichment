"""ENRICH-11, D-42, D-46: Webhook endpoint integration tests.

Tests cover: auth enforcement, phone update, idempotency, unknown apollo_id
handling, job counter incrementing, late webhook acceptance, and invalid payload.
"""

import uuid

import pytest
from sqlalchemy import select

from app.contacts.models import Contact
from app.jobs.models import Job, JobRow, RowStatus


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

TEST_WEBHOOK_SECRET = "test-webhook-secret-42"


async def _create_contact_with_apollo_id(session, apollo_id, email=None, phone=None):
    """Helper: create a Contact record with an apollo_id."""
    contact = Contact(
        email=email or f"{apollo_id}@test.com",
        apollo_id=apollo_id,
        first_name="Test",
        last_name="Contact",
        phone=phone,
    )
    session.add(contact)
    await session.flush()
    await session.refresh(contact)
    return contact


async def _create_job_with_contact(session, user_id, contact):
    """Helper: create a Job + JobRow linked to a contact (for counter tests)."""
    job = Job(
        id=uuid.uuid4(),
        user_id=user_id,
        filename="test.xlsx",
        file_path="/data/uploads/test.xlsx",
        status="awaiting_webhooks",
        total_rows=1,
        valid_rows=1,
        error_rows=0,
    )
    session.add(job)
    await session.flush()

    row = JobRow(
        id=uuid.uuid4(),
        job_id=job.id,
        row_index=0,
        raw_data={"Email": contact.email},
        status=RowStatus.ENRICHED.value,
        contact_id=contact.id,
    )
    session.add(row)
    await session.flush()
    await session.refresh(job)
    return job


# ---------------------------------------------------------------------------
# Webhook tests
# ---------------------------------------------------------------------------


async def test_webhook_valid_request(
    async_client, test_session, mock_webhook_payload, monkeypatch
):
    """ENRICH-11: Valid webhook updates contact phone."""
    from app.config import settings

    monkeypatch.setattr(settings, "apollo_webhook_secret", TEST_WEBHOOK_SECRET)

    contact = await _create_contact_with_apollo_id(
        test_session, "apollo-person-123", email="webhook@test.com"
    )
    assert contact.phone is None

    response = await async_client.post(
        "/api/v1/webhooks/apollo",
        json=mock_webhook_payload,
        headers={"X-Apollo-Secret": TEST_WEBHOOK_SECRET},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["contacts_updated"] == 1

    # Verify phone was updated
    await test_session.refresh(contact)
    assert contact.phone == "+15551234567"


async def test_webhook_invalid_secret(async_client, mock_webhook_payload, monkeypatch):
    """D-42: Wrong X-Apollo-Secret header returns 401."""
    from app.config import settings

    monkeypatch.setattr(settings, "apollo_webhook_secret", TEST_WEBHOOK_SECRET)

    response = await async_client.post(
        "/api/v1/webhooks/apollo",
        json=mock_webhook_payload,
        headers={"X-Apollo-Secret": "wrong-secret"},
    )

    assert response.status_code == 401


async def test_webhook_missing_secret(async_client, mock_webhook_payload, monkeypatch):
    """D-42: Missing X-Apollo-Secret header returns 422 (FastAPI validation)."""
    from app.config import settings

    monkeypatch.setattr(settings, "apollo_webhook_secret", TEST_WEBHOOK_SECRET)

    response = await async_client.post(
        "/api/v1/webhooks/apollo",
        json=mock_webhook_payload,
    )

    assert response.status_code == 422


async def test_webhook_unknown_apollo_id(async_client, test_session, monkeypatch):
    """ENRICH-11: Webhook for unknown apollo_id returns 200 gracefully."""
    from app.config import settings

    monkeypatch.setattr(settings, "apollo_webhook_secret", TEST_WEBHOOK_SECRET)

    payload = {
        "request_id": "req-unknown",
        "people": [
            {
                "id": "apollo-nonexistent-999",
                "waterfall": {
                    "phone_numbers": [
                        {
                            "raw_number": "+1-555-999-0000",
                            "sanitized_number": "+15559990000",
                            "confidence_cd": "high",
                            "status_cd": "valid_number",
                        }
                    ]
                },
            }
        ],
    }

    response = await async_client.post(
        "/api/v1/webhooks/apollo",
        json=payload,
        headers={"X-Apollo-Secret": TEST_WEBHOOK_SECRET},
    )

    assert response.status_code == 200
    assert response.json()["contacts_updated"] == 0


async def test_webhook_idempotent(
    async_client, test_session, mock_webhook_payload, monkeypatch
):
    """D-46: Posting same webhook twice does not change phone on second call."""
    from app.config import settings

    monkeypatch.setattr(settings, "apollo_webhook_secret", TEST_WEBHOOK_SECRET)

    contact = await _create_contact_with_apollo_id(
        test_session, "apollo-person-123", email="idempotent@test.com"
    )

    # First call -- sets phone
    resp1 = await async_client.post(
        "/api/v1/webhooks/apollo",
        json=mock_webhook_payload,
        headers={"X-Apollo-Secret": TEST_WEBHOOK_SECRET},
    )
    assert resp1.status_code == 200
    assert resp1.json()["contacts_updated"] == 1

    await test_session.refresh(contact)
    assert contact.phone == "+15551234567"

    # Second call -- phone already set, should not update
    resp2 = await async_client.post(
        "/api/v1/webhooks/apollo",
        json=mock_webhook_payload,
        headers={"X-Apollo-Secret": TEST_WEBHOOK_SECRET},
    )
    assert resp2.status_code == 200
    assert resp2.json()["contacts_updated"] == 0

    await test_session.refresh(contact)
    assert contact.phone == "+15551234567"  # unchanged


async def test_webhook_late_after_timeout(
    async_client, test_session, monkeypatch
):
    """D-46: Late webhook still updates phone on contact with empty phone."""
    from app.config import settings

    monkeypatch.setattr(settings, "apollo_webhook_secret", TEST_WEBHOOK_SECRET)

    # Simulate a contact that was created by Apollo but phone not yet received
    contact = await _create_contact_with_apollo_id(
        test_session, "apollo-late-456", email="late@test.com", phone=None
    )

    payload = {
        "request_id": "req-late",
        "people": [
            {
                "id": "apollo-late-456",
                "waterfall": {
                    "phone_numbers": [
                        {
                            "raw_number": "+1-555-LATE",
                            "sanitized_number": "+15555283",
                            "confidence_cd": "medium",
                            "status_cd": "valid_number",
                        }
                    ]
                },
            }
        ],
    }

    response = await async_client.post(
        "/api/v1/webhooks/apollo",
        json=payload,
        headers={"X-Apollo-Secret": TEST_WEBHOOK_SECRET},
    )

    assert response.status_code == 200
    assert response.json()["contacts_updated"] == 1

    await test_session.refresh(contact)
    assert contact.phone == "+15555283"


async def test_webhook_increments_job_counter(
    async_client, test_session, mock_webhook_payload, regular_user, monkeypatch
):
    """ENRICH-10: Webhook increments job.webhook_callbacks_received."""
    from app.config import settings

    monkeypatch.setattr(settings, "apollo_webhook_secret", TEST_WEBHOOK_SECRET)

    contact = await _create_contact_with_apollo_id(
        test_session, "apollo-person-123", email="counter@test.com"
    )
    job = await _create_job_with_contact(test_session, regular_user.id, contact)

    assert job.webhook_callbacks_received == 0

    response = await async_client.post(
        "/api/v1/webhooks/apollo",
        json=mock_webhook_payload,
        headers={"X-Apollo-Secret": TEST_WEBHOOK_SECRET},
    )

    assert response.status_code == 200

    # Refresh job from DB and check counter
    await test_session.refresh(job)
    assert job.webhook_callbacks_received == 1


async def test_webhook_invalid_payload(async_client, monkeypatch):
    """ENRICH-11: Malformed JSON body returns 422."""
    from app.config import settings

    monkeypatch.setattr(settings, "apollo_webhook_secret", TEST_WEBHOOK_SECRET)

    response = await async_client.post(
        "/api/v1/webhooks/apollo",
        content=b"this is not json",
        headers={
            "X-Apollo-Secret": TEST_WEBHOOK_SECRET,
            "Content-Type": "application/json",
        },
    )

    assert response.status_code == 422
