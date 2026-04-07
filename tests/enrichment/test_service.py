"""ENRICH-01 through ENRICH-10: Enrichment service unit tests.

Tests cover: field extraction, dedup grouping, DB-first cache lookup,
contact creation from Apollo, not-found status, row UUID preservation,
original file untouched, and job metrics tracking.
"""

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.admin.models import ApiConfig
from app.admin.service import encrypt_api_key
from app.contacts.models import Contact
from app.enrichment.schemas import ApolloEnrichResponse
from app.enrichment.service import (
    batch_contact_lookup,
    build_dedup_groups,
    extract_field,
    process_job,
)
from app.jobs.models import Job, JobRow, RowStatus


# ---------------------------------------------------------------------------
# extract_field tests
# ---------------------------------------------------------------------------


def test_extract_field_email(sample_column_mappings):
    """ENRICH-01: Extracts email from raw_data, lowercased."""
    raw_data = {"Email": "John@ACME.COM", "First Name": "John"}
    result = extract_field(raw_data, sample_column_mappings, "email")
    assert result == "john@acme.com"


def test_extract_field_missing(sample_column_mappings):
    """Returns None when field type not in mappings."""
    raw_data = {"Email": "john@acme.com"}
    result = extract_field(raw_data, sample_column_mappings, "phone")
    assert result is None


def test_extract_field_first_name(sample_column_mappings):
    """Extracts first name, stripped but not lowered."""
    raw_data = {"First Name": "  John  "}
    result = extract_field(raw_data, sample_column_mappings, "first_name")
    assert result == "John"


def test_extract_field_empty_value(sample_column_mappings):
    """Returns None for empty string values."""
    raw_data = {"Email": "  "}
    result = extract_field(raw_data, sample_column_mappings, "email")
    assert result is None


# ---------------------------------------------------------------------------
# build_dedup_groups tests
# ---------------------------------------------------------------------------


def _make_row(row_id, raw_data, status="pending"):
    """Create a mock JobRow-like object for pure function tests."""
    return SimpleNamespace(
        id=row_id or uuid.uuid4(),
        raw_data=raw_data,
        status=status,
    )


def test_build_dedup_groups_by_email(sample_column_mappings):
    """ENRICH-02: Two rows with same email are grouped together."""
    row1 = _make_row(uuid.uuid4(), {"Email": "john@acme.com", "First Name": "John"})
    row2 = _make_row(uuid.uuid4(), {"Email": "john@acme.com", "First Name": "John D"})
    groups = build_dedup_groups([row1, row2], sample_column_mappings)

    assert len(groups) == 1
    key = "email:john@acme.com"
    assert key in groups
    assert len(groups[key]) == 2


def test_build_dedup_groups_by_linkedin(sample_column_mappings):
    """ENRICH-02: Two rows with same LinkedIn URL grouped together."""
    row1 = _make_row(uuid.uuid4(), {"LinkedIn": "linkedin.com/in/johndoe"})
    row2 = _make_row(uuid.uuid4(), {"LinkedIn": "linkedin.com/in/johndoe"})
    groups = build_dedup_groups([row1, row2], sample_column_mappings)

    assert len(groups) == 1
    key = "linkedin:linkedin.com/in/johndoe"
    assert key in groups
    assert len(groups[key]) == 2


def test_build_dedup_groups_unique_rows(sample_column_mappings):
    """ENRICH-02: Rows with different emails get separate groups."""
    row1 = _make_row(uuid.uuid4(), {"Email": "john@acme.com"})
    row2 = _make_row(uuid.uuid4(), {"Email": "jane@smith.co"})
    groups = build_dedup_groups([row1, row2], sample_column_mappings)

    assert len(groups) == 2


def test_build_dedup_groups_no_identifier(sample_column_mappings):
    """ENRICH-02: Row with no email/LinkedIn gets unique key row:{uuid}."""
    row_id = uuid.uuid4()
    row = _make_row(row_id, {"First Name": "John", "Company": "Acme"})
    groups = build_dedup_groups([row], sample_column_mappings)

    assert len(groups) == 1
    key = f"row:{row_id}"
    assert key in groups


def test_build_dedup_groups_skips_non_pending(sample_column_mappings):
    """Only pending rows are included in dedup groups."""
    row1 = _make_row(uuid.uuid4(), {"Email": "john@acme.com"}, status="pending")
    row2 = _make_row(uuid.uuid4(), {"Email": "jane@smith.co"}, status="enriched")
    groups = build_dedup_groups([row1, row2], sample_column_mappings)

    assert len(groups) == 1


# ---------------------------------------------------------------------------
# batch_contact_lookup tests
# ---------------------------------------------------------------------------


async def test_batch_contact_lookup_cache_hit(test_session, sample_column_mappings):
    """ENRICH-03: Contact found in DB by email returns cache hit."""
    contact = Contact(email="john@acme.com", first_name="John", last_name="Doe")
    test_session.add(contact)
    await test_session.flush()

    row = _make_row(uuid.uuid4(), {"Email": "john@acme.com"})
    groups = {"email:john@acme.com": [row]}

    found = await batch_contact_lookup(test_session, groups)
    assert "email:john@acme.com" in found
    assert found["email:john@acme.com"].email == "john@acme.com"


async def test_batch_contact_lookup_cache_miss(test_session, sample_column_mappings):
    """ENRICH-03: No matching contact returns empty dict."""
    row = _make_row(uuid.uuid4(), {"Email": "unknown@example.com"})
    groups = {"email:unknown@example.com": [row]}

    found = await batch_contact_lookup(test_session, groups)
    assert len(found) == 0


async def test_batch_contact_lookup_linkedin_fallback(test_session):
    """D-47: Contact found by linkedin_url when no email match."""
    contact = Contact(linkedin_url="linkedin.com/in/johndoe", first_name="John")
    test_session.add(contact)
    await test_session.flush()

    row = _make_row(uuid.uuid4(), {"LinkedIn": "linkedin.com/in/johndoe"})
    groups = {"linkedin:linkedin.com/in/johndoe": [row]}

    found = await batch_contact_lookup(test_session, groups)
    assert "linkedin:linkedin.com/in/johndoe" in found


# ---------------------------------------------------------------------------
# process_job integration tests (with mocked Apollo)
# ---------------------------------------------------------------------------


async def _create_confirmed_job(session, user_id, column_mappings, rows_data):
    """Helper: create a confirmed Job with JobRow records in the DB."""
    job = Job(
        id=uuid.uuid4(),
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
    return job


async def test_contact_created_from_apollo(test_session, sample_column_mappings, regular_user):
    """ENRICH-05: After process_job with mocked Apollo, Contact record created."""
    job = await _create_confirmed_job(
        test_session,
        regular_user.id,
        sample_column_mappings,
        [{"Email": "newperson@test.com", "First Name": "New", "Last Name": "Person", "Company": "TestCo"}],
    )

    # Set up API key in DB
    encrypted = encrypt_api_key("fake-api-key")
    config = ApiConfig(key="apollo_api_key", value=encrypted)
    test_session.add(config)
    await test_session.flush()

    mock_response = ApolloEnrichResponse.model_validate({
        "person": {
            "id": "apollo-new-123",
            "first_name": "New",
            "last_name": "Person",
            "email": "newperson@test.com",
            "organization": {"name": "TestCo"},
        },
    })

    # Create a mock session factory that returns the test session
    async def mock_session_ctx():
        yield test_session

    class MockSessionFactory:
        def __call__(self):
            from contextlib import asynccontextmanager
            return asynccontextmanager(mock_session_ctx)()

    with patch("app.enrichment.service._get_api_key_from_db", new_callable=AsyncMock, return_value="fake-api-key"), \
         patch("app.enrichment.service.ApolloClient") as MockApolloClass:
        mock_client_instance = AsyncMock()
        mock_client_instance.enrich_person = AsyncMock(return_value=mock_response)
        mock_client_instance.close = AsyncMock()
        MockApolloClass.return_value = mock_client_instance

        await process_job(job.id, MockSessionFactory())

    # Verify contact was created
    result = await test_session.execute(
        select(Contact).where(Contact.apollo_id == "apollo-new-123")
    )
    contact = result.scalar_one_or_none()
    assert contact is not None
    assert contact.email == "newperson@test.com"
    assert contact.raw_apollo_response is not None


async def test_not_found_row_status(test_session, sample_column_mappings, regular_user):
    """ENRICH-06: Mock Apollo returning not found sets row.status = 'not_found'."""
    job = await _create_confirmed_job(
        test_session,
        regular_user.id,
        sample_column_mappings,
        [{"Email": "ghost@nowhere.com", "First Name": "Ghost"}],
    )

    encrypted = encrypt_api_key("fake-api-key")
    config = ApiConfig(key="apollo_api_key", value=encrypted)
    test_session.add(config)
    await test_session.flush()

    from app.enrichment.apollo_client import ApolloNotFoundError

    async def mock_session_ctx():
        yield test_session

    class MockSessionFactory:
        def __call__(self):
            from contextlib import asynccontextmanager
            return asynccontextmanager(mock_session_ctx)()

    with patch("app.enrichment.service._get_api_key_from_db", new_callable=AsyncMock, return_value="fake-api-key"), \
         patch("app.enrichment.service.ApolloClient") as MockApolloClass:
        mock_client_instance = AsyncMock()
        mock_client_instance.enrich_person = AsyncMock(side_effect=ApolloNotFoundError("No match"))
        mock_client_instance.close = AsyncMock()
        MockApolloClass.return_value = mock_client_instance

        await process_job(job.id, MockSessionFactory())

    # Verify row status
    result = await test_session.execute(
        select(JobRow).where(JobRow.job_id == job.id)
    )
    rows = result.scalars().all()
    assert len(rows) == 1
    assert rows[0].status == "not_found"


async def test_row_uuid_preserved(test_session, sample_column_mappings, regular_user):
    """ENRICH-01: Row UUID is never changed during processing."""
    job = await _create_confirmed_job(
        test_session,
        regular_user.id,
        sample_column_mappings,
        [{"Email": "stable@test.com", "First Name": "Stable"}],
    )

    # Record original row UUIDs
    result = await test_session.execute(
        select(JobRow).where(JobRow.job_id == job.id)
    )
    original_rows = result.scalars().all()
    original_ids = {r.id for r in original_rows}

    encrypted = encrypt_api_key("fake-api-key")
    config = ApiConfig(key="apollo_api_key", value=encrypted)
    test_session.add(config)
    await test_session.flush()

    mock_response = ApolloEnrichResponse.model_validate({
        "person": {
            "id": "apollo-stable-123",
            "first_name": "Stable",
            "email": "stable@test.com",
        },
    })

    async def mock_session_ctx():
        yield test_session

    class MockSessionFactory:
        def __call__(self):
            from contextlib import asynccontextmanager
            return asynccontextmanager(mock_session_ctx)()

    with patch("app.enrichment.service._get_api_key_from_db", new_callable=AsyncMock, return_value="fake-api-key"), \
         patch("app.enrichment.service.ApolloClient") as MockApolloClass:
        mock_client_instance = AsyncMock()
        mock_client_instance.enrich_person = AsyncMock(return_value=mock_response)
        mock_client_instance.close = AsyncMock()
        MockApolloClass.return_value = mock_client_instance

        await process_job(job.id, MockSessionFactory())

    # Verify UUIDs unchanged
    result = await test_session.execute(
        select(JobRow).where(JobRow.job_id == job.id)
    )
    post_rows = result.scalars().all()
    post_ids = {r.id for r in post_rows}
    assert original_ids == post_ids


async def test_original_file_untouched(test_session, sample_column_mappings, regular_user):
    """ENRICH-09: process_job never opens or reads a .xlsx file."""
    job = await _create_confirmed_job(
        test_session,
        regular_user.id,
        sample_column_mappings,
        [{"Email": "test@test.com", "First Name": "Test"}],
    )

    encrypted = encrypt_api_key("fake-api-key")
    config = ApiConfig(key="apollo_api_key", value=encrypted)
    test_session.add(config)
    await test_session.flush()

    mock_response = ApolloEnrichResponse.model_validate({
        "person": {"id": "apollo-test", "email": "test@test.com"},
    })

    async def mock_session_ctx():
        yield test_session

    class MockSessionFactory:
        def __call__(self):
            from contextlib import asynccontextmanager
            return asynccontextmanager(mock_session_ctx)()

    with patch("app.enrichment.service._get_api_key_from_db", new_callable=AsyncMock, return_value="fake-api-key"), \
         patch("app.enrichment.service.ApolloClient") as MockApolloClass, \
         patch("builtins.open", side_effect=AssertionError("File should not be opened")) as mock_open:
        mock_client_instance = AsyncMock()
        mock_client_instance.enrich_person = AsyncMock(return_value=mock_response)
        mock_client_instance.close = AsyncMock()
        MockApolloClass.return_value = mock_client_instance

        # If process_job tried to open any file, the patched open() would raise
        await process_job(job.id, MockSessionFactory())

    # If we get here, no file was opened - test passes


async def test_job_metrics_updated(test_session, sample_column_mappings, regular_user):
    """ENRICH-10: After process_job, job metrics (processed_rows, cache_hits, api_calls) are set."""
    job = await _create_confirmed_job(
        test_session,
        regular_user.id,
        sample_column_mappings,
        [
            {"Email": "person1@test.com", "First Name": "Person1"},
            {"Email": "person2@test.com", "First Name": "Person2"},
        ],
    )

    encrypted = encrypt_api_key("fake-api-key")
    config = ApiConfig(key="apollo_api_key", value=encrypted)
    test_session.add(config)
    await test_session.flush()

    mock_response1 = ApolloEnrichResponse.model_validate({
        "person": {"id": "apollo-p1", "email": "person1@test.com"},
    })
    mock_response2 = ApolloEnrichResponse.model_validate({
        "person": {"id": "apollo-p2", "email": "person2@test.com"},
    })

    async def mock_session_ctx():
        yield test_session

    class MockSessionFactory:
        def __call__(self):
            from contextlib import asynccontextmanager
            return asynccontextmanager(mock_session_ctx)()

    with patch("app.enrichment.service._get_api_key_from_db", new_callable=AsyncMock, return_value="fake-api-key"), \
         patch("app.enrichment.service.ApolloClient") as MockApolloClass:
        mock_client_instance = AsyncMock()
        mock_client_instance.enrich_person = AsyncMock(side_effect=[mock_response1, mock_response2])
        mock_client_instance.close = AsyncMock()
        MockApolloClass.return_value = mock_client_instance

        await process_job(job.id, MockSessionFactory())

    # Refresh job from DB
    result = await test_session.execute(select(Job).where(Job.id == job.id))
    updated_job = result.scalar_one()
    assert updated_job.processed_rows == 2
    assert updated_job.api_calls == 2
    assert updated_job.cache_hits == 0
