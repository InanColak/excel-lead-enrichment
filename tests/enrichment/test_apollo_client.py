"""ENRICH-04, D-38: Apollo client unit tests.

Tests cover success, not-found, retry on 429/5xx/timeout, no-retry on 400/401,
and DB-based API key retrieval.
"""

import uuid
from unittest.mock import AsyncMock, patch

import httpx
import pytest
from sqlalchemy import select

from app.admin.models import ApiConfig
from app.admin.service import encrypt_api_key
from app.enrichment.apollo_client import (
    ApolloClient,
    ApolloClientError,
    ApolloNotFoundError,
    ApolloTransientError,
    _get_api_key_from_db,
)
from app.enrichment.schemas import ApolloEnrichResponse


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_httpx_response(status_code: int, json_data: dict | None = None) -> httpx.Response:
    """Build a fake httpx.Response."""
    resp = httpx.Response(
        status_code=status_code,
        json=json_data if json_data is not None else {},
        request=httpx.Request("POST", "https://api.apollo.io/api/v1/people/match"),
    )
    return resp


# ---------------------------------------------------------------------------
# enrich_person tests
# ---------------------------------------------------------------------------


async def test_enrich_person_success(mock_apollo_success_response):
    """ENRICH-04: Successful enrichment returns ApolloEnrichResponse with person data."""
    client = ApolloClient(api_key="test-key")
    mock_resp = _make_httpx_response(200, mock_apollo_success_response)

    with patch.object(client.client, "post", new_callable=AsyncMock, return_value=mock_resp):
        result = await client.enrich_person(
            first_name="John", last_name="Doe", organization_name="Acme Corp"
        )

    assert isinstance(result, ApolloEnrichResponse)
    assert result.person is not None
    assert result.person.email == "john@acme.com"
    assert result.person.id == "apollo-person-123"
    await client.close()


async def test_enrich_person_not_found(mock_apollo_not_found_response):
    """ENRICH-06: Apollo returning no person match raises ApolloNotFoundError."""
    client = ApolloClient(api_key="test-key")
    mock_resp = _make_httpx_response(200, mock_apollo_not_found_response)

    with patch.object(client.client, "post", new_callable=AsyncMock, return_value=mock_resp):
        with pytest.raises(ApolloNotFoundError):
            await client.enrich_person(email="unknown@example.com")

    await client.close()


async def test_enrich_person_rate_limited_retries(mock_apollo_success_response):
    """D-38: 429 responses trigger retries, eventually succeeding."""
    client = ApolloClient(api_key="test-key")

    call_count = 0

    async def mock_post(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count <= 3:
            return _make_httpx_response(429)
        return _make_httpx_response(200, mock_apollo_success_response)

    with patch.object(client.client, "post", side_effect=mock_post):
        # Override retry wait to make test fast
        original_retry = client.enrich_person.retry
        client.enrich_person.retry.wait = lambda *a, **kw: 0  # type: ignore[attr-defined]
        try:
            result = await client.enrich_person(first_name="John", last_name="Doe")
        finally:
            client.enrich_person.retry.wait = original_retry.wait  # type: ignore[attr-defined]

    assert call_count == 4
    assert result.person is not None
    await client.close()


async def test_enrich_person_server_error_retries(mock_apollo_success_response):
    """D-38: 500 responses trigger retries, eventually succeeding."""
    client = ApolloClient(api_key="test-key")

    call_count = 0

    async def mock_post(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return _make_httpx_response(500)
        return _make_httpx_response(200, mock_apollo_success_response)

    with patch.object(client.client, "post", side_effect=mock_post):
        client.enrich_person.retry.wait = lambda *a, **kw: 0  # type: ignore[attr-defined]
        result = await client.enrich_person(first_name="John")

    assert call_count == 2
    assert result.person is not None
    await client.close()


async def test_enrich_person_bad_request_no_retry():
    """D-38: 400 raises ApolloClientError immediately (no retry)."""
    client = ApolloClient(api_key="test-key")
    mock_resp = _make_httpx_response(400, {"error": "bad request"})

    call_count = 0
    original_post = client.client.post

    async def mock_post(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        return mock_resp

    with patch.object(client.client, "post", side_effect=mock_post):
        with pytest.raises(ApolloClientError, match="400"):
            await client.enrich_person(email="test@example.com")

    assert call_count == 1  # No retries
    await client.close()


async def test_enrich_person_unauthorized_no_retry():
    """D-38: 401 raises ApolloClientError immediately (no retry)."""
    client = ApolloClient(api_key="bad-key")
    mock_resp = _make_httpx_response(401)

    call_count = 0

    async def mock_post(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        return mock_resp

    with patch.object(client.client, "post", side_effect=mock_post):
        with pytest.raises(ApolloClientError, match="401"):
            await client.enrich_person(email="test@example.com")

    assert call_count == 1  # No retries
    await client.close()


async def test_enrich_person_timeout_retries(mock_apollo_success_response):
    """D-38: Timeout exceptions trigger retries, eventually succeeding."""
    client = ApolloClient(api_key="test-key")

    call_count = 0

    async def mock_post(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise httpx.TimeoutException("Connection timed out")
        return _make_httpx_response(200, mock_apollo_success_response)

    with patch.object(client.client, "post", side_effect=mock_post):
        client.enrich_person.retry.wait = lambda *a, **kw: 0  # type: ignore[attr-defined]
        result = await client.enrich_person(first_name="John")

    assert call_count == 2
    assert result.person is not None
    await client.close()


# ---------------------------------------------------------------------------
# _get_api_key_from_db tests
# ---------------------------------------------------------------------------


async def test_get_api_key_from_db_success(test_session):
    """Pitfall 4: API key is retrieved from DB and decrypted correctly."""
    encrypted = encrypt_api_key("test-apollo-key-12345")
    config = ApiConfig(key="apollo_api_key", value=encrypted)
    test_session.add(config)
    await test_session.flush()

    result = await _get_api_key_from_db(test_session)
    assert result == "test-apollo-key-12345"


async def test_get_api_key_from_db_not_configured(test_session):
    """No API key configured raises ApolloClientError."""
    with pytest.raises(ApolloClientError, match="not configured"):
        await _get_api_key_from_db(test_session)
