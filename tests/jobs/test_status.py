"""OUTPUT-02: Job status polling with extended metrics tests."""

import uuid

from app.auth.service import create_access_token, hash_password
from app.auth.models import User
from app.jobs.models import Job, JobStatus


async def test_status_returns_extended_fields(async_client, regular_user, user_token, test_session):
    """GET /api/v1/jobs/{job_id} returns processed_rows, cache_hits, api_calls, webhook metrics."""
    job = Job(
        user_id=regular_user.id,
        filename="test.xlsx",
        file_path="/data/uploads/test/original.xlsx",
        status=JobStatus.PROCESSING.value,
        total_rows=100,
        valid_rows=90,
        error_rows=10,
        processed_rows=50,
        cache_hits=20,
        api_calls=30,
        webhook_callbacks_received=15,
        webhook_timeouts=2,
    )
    test_session.add(job)
    await test_session.flush()

    response = await async_client.get(
        f"/api/v1/jobs/{job.id}",
        headers={"Authorization": f"Bearer {user_token}"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["processed_rows"] == 50
    assert data["cache_hits"] == 20
    assert data["api_calls"] == 30
    assert data["webhook_callbacks_received"] == 15
    assert data["webhook_timeouts"] == 2


async def test_progress_percent_during_processing(async_client, regular_user, user_token, test_session):
    """progress_percent computed when status is processing and total_rows > 0."""
    job = Job(
        user_id=regular_user.id,
        filename="test.xlsx",
        file_path="/data/uploads/test/original.xlsx",
        status=JobStatus.PROCESSING.value,
        total_rows=100,
        valid_rows=100,
        error_rows=0,
        processed_rows=75,
    )
    test_session.add(job)
    await test_session.flush()

    response = await async_client.get(
        f"/api/v1/jobs/{job.id}",
        headers={"Authorization": f"Bearer {user_token}"},
    )
    data = response.json()
    assert data["progress_percent"] == 75.0


async def test_progress_percent_during_awaiting_webhooks(async_client, regular_user, user_token, test_session):
    """progress_percent computed when status is awaiting_webhooks."""
    job = Job(
        user_id=regular_user.id,
        filename="test.xlsx",
        file_path="/data/uploads/test/original.xlsx",
        status=JobStatus.AWAITING_WEBHOOKS.value,
        total_rows=200,
        valid_rows=200,
        error_rows=0,
        processed_rows=150,
    )
    test_session.add(job)
    await test_session.flush()

    response = await async_client.get(
        f"/api/v1/jobs/{job.id}",
        headers={"Authorization": f"Bearer {user_token}"},
    )
    data = response.json()
    assert data["progress_percent"] == 75.0


async def test_progress_percent_null_when_complete(async_client, regular_user, user_token, test_session):
    """progress_percent is null when status is complete."""
    job = Job(
        user_id=regular_user.id,
        filename="test.xlsx",
        file_path="/data/uploads/test/original.xlsx",
        status=JobStatus.COMPLETE.value,
        total_rows=100,
        valid_rows=100,
        error_rows=0,
        processed_rows=100,
    )
    test_session.add(job)
    await test_session.flush()

    response = await async_client.get(
        f"/api/v1/jobs/{job.id}",
        headers={"Authorization": f"Bearer {user_token}"},
    )
    data = response.json()
    assert data["progress_percent"] is None


async def test_progress_percent_null_when_pending(async_client, regular_user, user_token, test_session):
    """progress_percent is null when status is pending_confirmation."""
    job = Job(
        user_id=regular_user.id,
        filename="test.xlsx",
        file_path="/data/uploads/test/original.xlsx",
        status=JobStatus.PENDING_CONFIRMATION.value,
        total_rows=100,
        valid_rows=100,
        error_rows=0,
    )
    test_session.add(job)
    await test_session.flush()

    response = await async_client.get(
        f"/api/v1/jobs/{job.id}",
        headers={"Authorization": f"Bearer {user_token}"},
    )
    data = response.json()
    assert data["progress_percent"] is None


async def test_has_output_true_when_file_exists(async_client, regular_user, user_token, test_session):
    """has_output is true when output_file_path is set."""
    job = Job(
        user_id=regular_user.id,
        filename="test.xlsx",
        file_path="/data/uploads/test/original.xlsx",
        status=JobStatus.COMPLETE.value,
        total_rows=10,
        valid_rows=10,
        error_rows=0,
        output_file_path="/data/uploads/test/enriched.xlsx",
    )
    test_session.add(job)
    await test_session.flush()

    response = await async_client.get(
        f"/api/v1/jobs/{job.id}",
        headers={"Authorization": f"Bearer {user_token}"},
    )
    data = response.json()
    assert data["has_output"] is True


async def test_has_output_false_when_no_file(async_client, regular_user, user_token, test_session):
    """has_output is false when output_file_path is None."""
    job = Job(
        user_id=regular_user.id,
        filename="test.xlsx",
        file_path="/data/uploads/test/original.xlsx",
        status=JobStatus.PROCESSING.value,
        total_rows=10,
        valid_rows=10,
        error_rows=0,
    )
    test_session.add(job)
    await test_session.flush()

    response = await async_client.get(
        f"/api/v1/jobs/{job.id}",
        headers={"Authorization": f"Bearer {user_token}"},
    )
    data = response.json()
    assert data["has_output"] is False


async def test_output_file_path_not_in_response(async_client, regular_user, user_token, test_session):
    """output_file_path should be excluded from serialization (T-04-07)."""
    job = Job(
        user_id=regular_user.id,
        filename="test.xlsx",
        file_path="/data/uploads/test/original.xlsx",
        status=JobStatus.COMPLETE.value,
        total_rows=10,
        valid_rows=10,
        error_rows=0,
        output_file_path="/data/uploads/test/enriched.xlsx",
    )
    test_session.add(job)
    await test_session.flush()

    response = await async_client.get(
        f"/api/v1/jobs/{job.id}",
        headers={"Authorization": f"Bearer {user_token}"},
    )
    data = response.json()
    assert "output_file_path" not in data
