"""OUTPUT-03: Download endpoint tests."""

import uuid
from pathlib import Path

from app.auth.service import create_access_token, hash_password
from app.auth.models import User
from app.jobs.models import Job, JobStatus


async def test_download_returns_excel_file(async_client, regular_user, user_token, test_session, tmp_path):
    """GET /api/v1/jobs/{job_id}/download returns Excel file with correct content type."""
    # Create a fake output file
    output_dir = tmp_path / "output"
    output_dir.mkdir()
    output_file = output_dir / "enriched.xlsx"
    output_file.write_bytes(b"fake excel content for testing")

    job = Job(
        user_id=regular_user.id,
        filename="test.xlsx",
        file_path="/data/uploads/test/original.xlsx",
        status=JobStatus.COMPLETE.value,
        total_rows=10,
        valid_rows=10,
        error_rows=0,
        output_file_path=str(output_file),
    )
    test_session.add(job)
    await test_session.flush()

    response = await async_client.get(
        f"/api/v1/jobs/{job.id}/download",
        headers={"Authorization": f"Bearer {user_token}"},
    )
    assert response.status_code == 200
    assert "spreadsheetml" in response.headers.get("content-type", "")


async def test_download_404_when_no_output(async_client, regular_user, user_token, test_session):
    """GET /api/v1/jobs/{job_id}/download returns 404 when output file not available."""
    job = Job(
        user_id=regular_user.id,
        filename="test.xlsx",
        file_path="/data/uploads/test/original.xlsx",
        status=JobStatus.PROCESSING.value,
        total_rows=10,
        valid_rows=10,
        error_rows=0,
        # output_file_path is None
    )
    test_session.add(job)
    await test_session.flush()

    response = await async_client.get(
        f"/api/v1/jobs/{job.id}/download",
        headers={"Authorization": f"Bearer {user_token}"},
    )
    assert response.status_code == 404


async def test_download_404_when_file_missing_on_disk(async_client, regular_user, user_token, test_session):
    """GET /api/v1/jobs/{job_id}/download returns 404 when output_file_path set but file doesn't exist."""
    job = Job(
        user_id=regular_user.id,
        filename="test.xlsx",
        file_path="/data/uploads/test/original.xlsx",
        status=JobStatus.COMPLETE.value,
        total_rows=10,
        valid_rows=10,
        error_rows=0,
        output_file_path="/nonexistent/path/enriched.xlsx",
    )
    test_session.add(job)
    await test_session.flush()

    response = await async_client.get(
        f"/api/v1/jobs/{job.id}/download",
        headers={"Authorization": f"Bearer {user_token}"},
    )
    assert response.status_code == 404


async def test_download_user_isolation(async_client, test_session, tmp_path):
    """User A cannot download User B's job."""
    # Create User A
    user_a = User(
        id=uuid.uuid4(),
        email="usera_dl@test.com",
        hashed_password=hash_password("pass"),
        is_admin=False,
        is_active=True,
    )
    test_session.add(user_a)
    await test_session.flush()
    token_a, _ = create_access_token(str(user_a.id), False)

    # Create User B with a job
    user_b = User(
        id=uuid.uuid4(),
        email="userb_dl@test.com",
        hashed_password=hash_password("pass"),
        is_admin=False,
        is_active=True,
    )
    test_session.add(user_b)
    await test_session.flush()

    output_file = tmp_path / "enriched.xlsx"
    output_file.write_bytes(b"fake excel content")

    job = Job(
        user_id=user_b.id,
        filename="test.xlsx",
        file_path="/data/uploads/test/original.xlsx",
        status=JobStatus.COMPLETE.value,
        total_rows=10,
        valid_rows=10,
        error_rows=0,
        output_file_path=str(output_file),
    )
    test_session.add(job)
    await test_session.flush()

    # User A tries to download User B's job
    response = await async_client.get(
        f"/api/v1/jobs/{job.id}/download",
        headers={"Authorization": f"Bearer {token_a}"},
    )
    assert response.status_code == 404
