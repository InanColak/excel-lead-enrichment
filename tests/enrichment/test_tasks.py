"""ENRICH-07, ENRICH-08, JOB-01, D-52: Celery task behavior tests.

Tests the async functions inside the Celery wrappers directly, without
requiring a running Celery worker. Covers job lifecycle transitions,
concurrent isolation, webhook timeout completion, and failure handling.
"""

import uuid
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import select

from app.admin.models import ApiConfig
from app.admin.service import encrypt_api_key
from app.contacts.models import Contact
from app.enrichment.schemas import ApolloEnrichResponse
from app.enrichment.service import process_job
from app.enrichment.tasks import _check_webhook_completion_async, _mark_job_failed
from app.jobs.models import Job, JobRow, RowStatus


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _create_confirmed_job(session, user_id, column_mappings, rows_data, job_id=None):
    """Create a confirmed Job with pending JobRow records."""
    job = Job(
        id=job_id or uuid.uuid4(),
        user_id=user_id,
        filename="test.xlsx",
        file_path="/data/uploads/test.xlsx",
        status="confirmed",
        total_rows=len(rows_data),
        valid_rows=len(rows_data),
        error_rows=0,
        column_mappings=column_mappings,
    )
    session.add(job)
    await session.flush()

    for idx, raw_data in enumerate(rows_data):
        row = JobRow(
            id=uuid.uuid4(),
            job_id=job.id,
            row_index=idx,
            raw_data=raw_data,
            status=RowStatus.PENDING.value,
        )
        session.add(row)

    await session.flush()
    await session.refresh(job)
    return job


def _mock_session_factory(test_session):
    """Build a mock session factory that yields the test session."""

    class _Factory:
        def __call__(self):
            @asynccontextmanager
            async def _ctx():
                yield test_session

            return _ctx()

    return _Factory()


async def _setup_api_key(session):
    """Insert a fake encrypted API key into the DB."""
    encrypted = encrypt_api_key("fake-api-key")
    config = ApiConfig(key="apollo_api_key", value=encrypted)
    session.add(config)
    await session.flush()


SAMPLE_MAPPINGS = [
    {"column": "Email", "detected_type": "email", "confidence": "HIGH"},
    {"column": "First Name", "detected_type": "first_name", "confidence": "HIGH"},
    {"column": "Last Name", "detected_type": "last_name", "confidence": "HIGH"},
    {"column": "Company", "detected_type": "company", "confidence": "MEDIUM"},
]


# ---------------------------------------------------------------------------
# Task tests
# ---------------------------------------------------------------------------


async def test_process_job_background(test_session, regular_user):
    """ENRICH-07, JOB-01: Job transitions CONFIRMED -> PROCESSING -> AWAITING_WEBHOOKS."""
    job = await _create_confirmed_job(
        test_session,
        regular_user.id,
        SAMPLE_MAPPINGS,
        [{"Email": "bg@test.com", "First Name": "BG"}],
    )
    await _setup_api_key(test_session)

    mock_response = ApolloEnrichResponse.model_validate({
        "person": {"id": "apollo-bg-1", "email": "bg@test.com"},
    })

    factory = _mock_session_factory(test_session)

    with patch("app.enrichment.service._get_api_key_from_db", new_callable=AsyncMock, return_value="fake-api-key"), \
         patch("app.enrichment.service.ApolloClient") as MockApolloClass:
        mock_instance = AsyncMock()
        mock_instance.enrich_person = AsyncMock(return_value=mock_response)
        mock_instance.close = AsyncMock()
        MockApolloClass.return_value = mock_instance

        await process_job(job.id, factory)

    await test_session.refresh(job)
    # API call was made -> should be awaiting_webhooks
    assert job.status == "awaiting_webhooks"


async def test_check_webhook_completion_all_received(test_session, regular_user):
    """D-52, JOB-01: All contacts have phone -> job transitions to COMPLETE."""
    job = Job(
        id=uuid.uuid4(),
        user_id=regular_user.id,
        filename="test.xlsx",
        file_path="/data/uploads/test.xlsx",
        status="awaiting_webhooks",
        total_rows=1,
        valid_rows=1,
        error_rows=0,
        api_calls=1,
    )
    test_session.add(job)
    await test_session.flush()

    # Create contact WITH phone (webhook already arrived)
    contact = Contact(
        email="complete@test.com",
        apollo_id="apollo-complete-1",
        phone="+15551234567",
    )
    test_session.add(contact)
    await test_session.flush()

    row = JobRow(
        id=uuid.uuid4(),
        job_id=job.id,
        row_index=0,
        raw_data={"Email": "complete@test.com"},
        status=RowStatus.ENRICHED.value,
        contact_id=contact.id,
    )
    test_session.add(row)
    await test_session.flush()

    factory = _mock_session_factory(test_session)
    await _check_webhook_completion_async(str(job.id), factory)

    await test_session.refresh(job)
    assert job.status == "complete"


async def test_check_webhook_completion_some_missing(test_session, regular_user):
    """D-52, D-43: Contacts missing phone after timeout -> webhook_timeouts > 0."""
    job = Job(
        id=uuid.uuid4(),
        user_id=regular_user.id,
        filename="test.xlsx",
        file_path="/data/uploads/test.xlsx",
        status="awaiting_webhooks",
        total_rows=2,
        valid_rows=2,
        error_rows=0,
        api_calls=2,
    )
    test_session.add(job)
    await test_session.flush()

    # Contact 1: has phone (webhook arrived)
    contact1 = Contact(
        email="has-phone@test.com",
        apollo_id="apollo-has-phone",
        phone="+15551111111",
    )
    test_session.add(contact1)
    await test_session.flush()

    # Contact 2: no phone (webhook timed out)
    contact2 = Contact(
        email="no-phone@test.com",
        apollo_id="apollo-no-phone",
        phone=None,
    )
    test_session.add(contact2)
    await test_session.flush()

    row1 = JobRow(
        id=uuid.uuid4(),
        job_id=job.id,
        row_index=0,
        raw_data={"Email": "has-phone@test.com"},
        status=RowStatus.ENRICHED.value,
        contact_id=contact1.id,
    )
    row2 = JobRow(
        id=uuid.uuid4(),
        job_id=job.id,
        row_index=1,
        raw_data={"Email": "no-phone@test.com"},
        status=RowStatus.ENRICHED.value,
        contact_id=contact2.id,
    )
    test_session.add(row1)
    test_session.add(row2)
    await test_session.flush()

    factory = _mock_session_factory(test_session)
    await _check_webhook_completion_async(str(job.id), factory)

    await test_session.refresh(job)
    assert job.webhook_timeouts == 1
    # email_only counts as enriched -> all rows have some data -> complete
    assert job.status == "complete"


async def test_concurrent_jobs_isolated(test_session, regular_user, admin_user):
    """ENRICH-08: Two jobs for different users don't cross-contaminate rows."""
    await _setup_api_key(test_session)

    job_a = await _create_confirmed_job(
        test_session,
        regular_user.id,
        SAMPLE_MAPPINGS,
        [{"Email": "user-a@test.com", "First Name": "UserA"}],
    )
    job_b = await _create_confirmed_job(
        test_session,
        admin_user.id,
        SAMPLE_MAPPINGS,
        [{"Email": "user-b@test.com", "First Name": "UserB"}],
    )

    mock_response_a = ApolloEnrichResponse.model_validate({
        "person": {"id": "apollo-a", "email": "user-a@test.com"},
    })
    mock_response_b = ApolloEnrichResponse.model_validate({
        "person": {"id": "apollo-b", "email": "user-b@test.com"},
    })

    factory = _mock_session_factory(test_session)

    # Process job A
    with patch("app.enrichment.service._get_api_key_from_db", new_callable=AsyncMock, return_value="fake-api-key"), \
         patch("app.enrichment.service.ApolloClient") as MockApolloClass:
        mock_instance = AsyncMock()
        mock_instance.enrich_person = AsyncMock(return_value=mock_response_a)
        mock_instance.close = AsyncMock()
        MockApolloClass.return_value = mock_instance

        await process_job(job_a.id, factory)

    # Process job B
    with patch("app.enrichment.service._get_api_key_from_db", new_callable=AsyncMock, return_value="fake-api-key"), \
         patch("app.enrichment.service.ApolloClient") as MockApolloClass:
        mock_instance = AsyncMock()
        mock_instance.enrich_person = AsyncMock(return_value=mock_response_b)
        mock_instance.close = AsyncMock()
        MockApolloClass.return_value = mock_instance

        await process_job(job_b.id, factory)

    # Verify job A rows only reference job A contacts
    result_a = await test_session.execute(
        select(JobRow).where(JobRow.job_id == job_a.id)
    )
    rows_a = result_a.scalars().all()
    for row in rows_a:
        if row.contact_id:
            contact_result = await test_session.execute(
                select(Contact).where(Contact.id == row.contact_id)
            )
            contact = contact_result.scalar_one()
            assert contact.apollo_id == "apollo-a"

    # Verify job B rows only reference job B contacts
    result_b = await test_session.execute(
        select(JobRow).where(JobRow.job_id == job_b.id)
    )
    rows_b = result_b.scalars().all()
    for row in rows_b:
        if row.contact_id:
            contact_result = await test_session.execute(
                select(Contact).where(Contact.id == row.contact_id)
            )
            contact = contact_result.scalar_one()
            assert contact.apollo_id == "apollo-b"


async def test_job_lifecycle_full(test_session, regular_user):
    """JOB-01: Full lifecycle CONFIRMED -> PROCESSING -> AWAITING_WEBHOOKS -> COMPLETE."""
    await _setup_api_key(test_session)

    job = await _create_confirmed_job(
        test_session,
        regular_user.id,
        SAMPLE_MAPPINGS,
        [{"Email": "lifecycle@test.com", "First Name": "Lifecycle"}],
    )

    # Step 1: Verify starts as CONFIRMED
    assert job.status == "confirmed"

    mock_response = ApolloEnrichResponse.model_validate({
        "person": {"id": "apollo-lifecycle", "email": "lifecycle@test.com"},
    })

    factory = _mock_session_factory(test_session)

    # Step 2: Process -> should go through PROCESSING -> AWAITING_WEBHOOKS
    with patch("app.enrichment.service._get_api_key_from_db", new_callable=AsyncMock, return_value="fake-api-key"), \
         patch("app.enrichment.service.ApolloClient") as MockApolloClass:
        mock_instance = AsyncMock()
        mock_instance.enrich_person = AsyncMock(return_value=mock_response)
        mock_instance.close = AsyncMock()
        MockApolloClass.return_value = mock_instance

        await process_job(job.id, factory)

    await test_session.refresh(job)
    assert job.status == "awaiting_webhooks"

    # Step 3: Simulate webhook arrival -- set phone on contact
    result = await test_session.execute(
        select(Contact).where(Contact.apollo_id == "apollo-lifecycle")
    )
    contact = result.scalar_one()
    contact.phone = "+15559999999"
    await test_session.flush()

    # Step 4: Check webhook completion -> should transition to COMPLETE
    await _check_webhook_completion_async(str(job.id), factory)

    await test_session.refresh(job)
    assert job.status == "complete"


async def test_catastrophic_failure_marks_failed(test_session, regular_user):
    """D-52: Unexpected exception marks job as failed."""
    job = Job(
        id=uuid.uuid4(),
        user_id=regular_user.id,
        filename="test.xlsx",
        file_path="/data/uploads/test.xlsx",
        status="processing",
        total_rows=1,
        valid_rows=1,
        error_rows=0,
    )
    test_session.add(job)
    await test_session.flush()

    factory = _mock_session_factory(test_session)
    await _mark_job_failed(str(job.id), factory)

    await test_session.refresh(job)
    assert job.status == "failed"
