"""AUTH-04: Usage stats endpoint tests."""

import uuid

from app.auth.service import create_access_token, hash_password
from app.auth.models import User
from app.jobs.models import Job, JobStatus


async def test_stats_no_jobs_returns_zeros(async_client, regular_user, user_token, test_session):
    """GET /api/v1/stats with no jobs returns all zeros and cache_hit_rate_percent=0.0."""
    response = await async_client.get(
        "/api/v1/stats/",
        headers={"Authorization": f"Bearer {user_token}"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["total_jobs"] == 0
    assert data["total_api_calls"] == 0
    assert data["total_cache_hits"] == 0
    assert data["cache_hit_rate_percent"] == 0.0
    assert data["total_webhook_callbacks"] == 0
    assert data["total_webhook_timeouts"] == 0
    assert data["jobs_by_status"] == {}


async def test_stats_with_jobs(async_client, regular_user, user_token, test_session):
    """GET /api/v1/stats returns correct aggregations for user's jobs."""
    # Create jobs with known metric values
    job1 = Job(
        user_id=regular_user.id,
        filename="test1.xlsx",
        file_path="/data/uploads/test1/original.xlsx",
        status=JobStatus.COMPLETE.value,
        total_rows=100,
        valid_rows=100,
        error_rows=0,
        cache_hits=30,
        api_calls=70,
        webhook_callbacks_received=10,
        webhook_timeouts=2,
    )
    job2 = Job(
        user_id=regular_user.id,
        filename="test2.xlsx",
        file_path="/data/uploads/test2/original.xlsx",
        status=JobStatus.PROCESSING.value,
        total_rows=50,
        valid_rows=50,
        error_rows=0,
        cache_hits=20,
        api_calls=30,
        webhook_callbacks_received=5,
        webhook_timeouts=1,
    )
    test_session.add(job1)
    test_session.add(job2)
    await test_session.flush()

    response = await async_client.get(
        "/api/v1/stats/",
        headers={"Authorization": f"Bearer {user_token}"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["total_jobs"] == 2
    assert data["total_api_calls"] == 100  # 70 + 30
    assert data["total_cache_hits"] == 50  # 30 + 20
    assert data["total_webhook_callbacks"] == 15  # 10 + 5
    assert data["total_webhook_timeouts"] == 3  # 2 + 1


async def test_stats_cache_hit_rate_calculation(async_client, regular_user, user_token, test_session):
    """cache_hit_rate_percent computed correctly: cache_hits / (cache_hits + api_calls) * 100."""
    job = Job(
        user_id=regular_user.id,
        filename="test.xlsx",
        file_path="/data/uploads/test/original.xlsx",
        status=JobStatus.COMPLETE.value,
        total_rows=100,
        valid_rows=100,
        error_rows=0,
        cache_hits=75,
        api_calls=25,
    )
    test_session.add(job)
    await test_session.flush()

    response = await async_client.get(
        "/api/v1/stats/",
        headers={"Authorization": f"Bearer {user_token}"},
    )
    data = response.json()
    # 75 / (75 + 25) * 100 = 75.0
    assert data["cache_hit_rate_percent"] == 75.0


async def test_stats_jobs_by_status(async_client, regular_user, user_token, test_session):
    """jobs_by_status is a dict mapping status string to count."""
    for _ in range(3):
        test_session.add(Job(
            user_id=regular_user.id,
            filename="test.xlsx",
            file_path="/data/uploads/test/original.xlsx",
            status=JobStatus.COMPLETE.value,
            total_rows=10,
            valid_rows=10,
            error_rows=0,
        ))
    for _ in range(2):
        test_session.add(Job(
            user_id=regular_user.id,
            filename="test.xlsx",
            file_path="/data/uploads/test/original.xlsx",
            status=JobStatus.PROCESSING.value,
            total_rows=10,
            valid_rows=10,
            error_rows=0,
        ))
    test_session.add(Job(
        user_id=regular_user.id,
        filename="test.xlsx",
        file_path="/data/uploads/test/original.xlsx",
        status=JobStatus.FAILED.value,
        total_rows=10,
        valid_rows=10,
        error_rows=0,
    ))
    await test_session.flush()

    response = await async_client.get(
        "/api/v1/stats/",
        headers={"Authorization": f"Bearer {user_token}"},
    )
    data = response.json()
    assert data["jobs_by_status"]["complete"] == 3
    assert data["jobs_by_status"]["processing"] == 2
    assert data["jobs_by_status"]["failed"] == 1


async def test_stats_date_range_filter(async_client, regular_user, user_token, test_session):
    """GET /api/v1/stats?since=...&until=... filters by date range."""
    job = Job(
        user_id=regular_user.id,
        filename="test.xlsx",
        file_path="/data/uploads/test/original.xlsx",
        status=JobStatus.COMPLETE.value,
        total_rows=10,
        valid_rows=10,
        error_rows=0,
        cache_hits=5,
        api_calls=5,
    )
    test_session.add(job)
    await test_session.flush()

    # Wide range should include it
    response = await async_client.get(
        "/api/v1/stats/?since=2020-01-01T00:00:00&until=2030-12-31T23:59:59",
        headers={"Authorization": f"Bearer {user_token}"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["total_jobs"] == 1

    # Far future range should exclude it
    response = await async_client.get(
        "/api/v1/stats/?since=2099-01-01T00:00:00",
        headers={"Authorization": f"Bearer {user_token}"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["total_jobs"] == 0


async def test_stats_user_isolation(async_client, test_session):
    """User A's stats do not include User B's jobs."""
    # Create User A
    user_a = User(
        id=uuid.uuid4(),
        email="usera_stats@test.com",
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
        email="userb_stats@test.com",
        hashed_password=hash_password("pass"),
        is_admin=False,
        is_active=True,
    )
    test_session.add(user_b)
    await test_session.flush()

    # Create jobs for User A (api_calls=10)
    test_session.add(Job(
        user_id=user_a.id,
        filename="test.xlsx",
        file_path="/data/uploads/test/original.xlsx",
        status=JobStatus.COMPLETE.value,
        total_rows=10,
        valid_rows=10,
        error_rows=0,
        api_calls=10,
        cache_hits=5,
    ))
    # Create jobs for User B (api_calls=100)
    test_session.add(Job(
        user_id=user_b.id,
        filename="test.xlsx",
        file_path="/data/uploads/test/original.xlsx",
        status=JobStatus.COMPLETE.value,
        total_rows=10,
        valid_rows=10,
        error_rows=0,
        api_calls=100,
        cache_hits=50,
    ))
    await test_session.flush()

    # User A should see only their stats
    response = await async_client.get(
        "/api/v1/stats/",
        headers={"Authorization": f"Bearer {token_a}"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["total_jobs"] == 1
    assert data["total_api_calls"] == 10
    assert data["total_cache_hits"] == 5
