"""OUTPUT-03: Job listing with pagination, filtering, and user isolation tests."""

import uuid
from datetime import datetime, timezone

from app.auth.service import create_access_token, hash_password
from app.auth.models import User
from app.jobs.models import Job, JobStatus


async def _create_jobs(test_session, user_id, count=5, status=JobStatus.COMPLETE.value, base_time=None):
    """Helper to create multiple test jobs."""
    jobs = []
    for i in range(count):
        job = Job(
            user_id=user_id,
            filename=f"test_{i}.xlsx",
            file_path=f"/data/uploads/test_{i}/original.xlsx",
            status=status,
            total_rows=10 + i,
            valid_rows=10 + i,
            error_rows=0,
        )
        test_session.add(job)
        jobs.append(job)
    await test_session.flush()
    return jobs


async def test_list_jobs_returns_paginated(async_client, regular_user, user_token, test_session):
    """GET /api/v1/jobs returns paginated list of user's jobs."""
    await _create_jobs(test_session, regular_user.id, count=3)

    response = await async_client.get(
        "/api/v1/jobs/",
        headers={"Authorization": f"Bearer {user_token}"},
    )
    assert response.status_code == 200
    data = response.json()
    assert "items" in data
    assert "total" in data
    assert "limit" in data
    assert "offset" in data
    assert data["total"] == 3
    assert len(data["items"]) == 3


async def test_list_jobs_pagination_limit_offset(async_client, regular_user, user_token, test_session):
    """GET /api/v1/jobs?limit=2&offset=0 returns first 2 jobs and correct total."""
    await _create_jobs(test_session, regular_user.id, count=5)

    response = await async_client.get(
        "/api/v1/jobs/?limit=2&offset=0",
        headers={"Authorization": f"Bearer {user_token}"},
    )
    assert response.status_code == 200
    data = response.json()
    assert len(data["items"]) == 2
    assert data["total"] == 5
    assert data["limit"] == 2
    assert data["offset"] == 0


async def test_list_jobs_filter_by_status(async_client, regular_user, user_token, test_session):
    """GET /api/v1/jobs?status=complete filters by status."""
    await _create_jobs(test_session, regular_user.id, count=2, status=JobStatus.COMPLETE.value)
    await _create_jobs(test_session, regular_user.id, count=3, status=JobStatus.PROCESSING.value)

    response = await async_client.get(
        "/api/v1/jobs/?status=complete",
        headers={"Authorization": f"Bearer {user_token}"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 2
    assert all(item["status"] == "complete" for item in data["items"])


async def test_list_jobs_filter_by_date_range(async_client, regular_user, user_token, test_session):
    """GET /api/v1/jobs?created_after=...&created_before=... filters by date."""
    await _create_jobs(test_session, regular_user.id, count=3)

    # Query with a date range that should capture all (wide range)
    response = await async_client.get(
        "/api/v1/jobs/?created_after=2020-01-01T00:00:00&created_before=2030-12-31T23:59:59",
        headers={"Authorization": f"Bearer {user_token}"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 3

    # Query with a date range in the far future (should return 0)
    response = await async_client.get(
        "/api/v1/jobs/?created_after=2099-01-01T00:00:00",
        headers={"Authorization": f"Bearer {user_token}"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 0


async def test_list_jobs_limit_capped_at_100(async_client, regular_user, user_token, test_session):
    """limit is capped at 100 per D-60 — values > 100 return 422."""
    response = await async_client.get(
        "/api/v1/jobs/?limit=101",
        headers={"Authorization": f"Bearer {user_token}"},
    )
    assert response.status_code == 422


async def test_list_jobs_user_isolation(async_client, test_session):
    """User A cannot see User B's jobs in list."""
    # Create User A
    user_a = User(
        id=uuid.uuid4(),
        email="usera_list@test.com",
        hashed_password=hash_password("pass"),
        is_admin=False,
        is_active=True,
    )
    test_session.add(user_a)
    await test_session.flush()
    token_a, _ = create_access_token(str(user_a.id), False)

    # Create User B
    user_b = User(
        id=uuid.uuid4(),
        email="userb_list@test.com",
        hashed_password=hash_password("pass"),
        is_admin=False,
        is_active=True,
    )
    test_session.add(user_b)
    await test_session.flush()
    token_b, _ = create_access_token(str(user_b.id), False)

    # Create jobs for User A
    await _create_jobs(test_session, user_a.id, count=3)
    # Create jobs for User B
    await _create_jobs(test_session, user_b.id, count=2)

    # User A should see only their 3 jobs
    response = await async_client.get(
        "/api/v1/jobs/",
        headers={"Authorization": f"Bearer {token_a}"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 3

    # User B should see only their 2 jobs
    response = await async_client.get(
        "/api/v1/jobs/",
        headers={"Authorization": f"Bearer {token_b}"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 2


async def test_list_jobs_sorted_by_created_at_desc(async_client, regular_user, user_token, test_session):
    """Jobs are returned sorted by created_at descending (newest first)."""
    await _create_jobs(test_session, regular_user.id, count=3)

    response = await async_client.get(
        "/api/v1/jobs/",
        headers={"Authorization": f"Bearer {user_token}"},
    )
    assert response.status_code == 200
    data = response.json()
    items = data["items"]
    # Verify descending order by created_at
    for i in range(len(items) - 1):
        assert items[i]["created_at"] >= items[i + 1]["created_at"]
