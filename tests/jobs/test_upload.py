"""FILE-01 and FILE-02: Upload endpoint integration tests."""

import uuid

from sqlalchemy import select

from app.jobs.models import Job, JobRow
from tests.conftest import make_upload_file


async def test_upload_valid_xlsx(async_client, user_token, sample_xlsx_file, upload_dir_override):
    """FILE-01: Valid .xlsx upload returns job ID with PENDING_CONFIRMATION status."""
    files = [make_upload_file(sample_xlsx_file)]
    response = await async_client.post(
        "/api/v1/jobs/upload",
        files=files,
        headers={"Authorization": f"Bearer {user_token}"},
    )
    assert response.status_code == 201
    data = response.json()
    assert data["status"] == "pending_confirmation"


async def test_upload_returns_job_id(async_client, user_token, sample_xlsx_file, upload_dir_override):
    """FILE-01: Response contains job_id (UUID), filename, status, row counts."""
    files = [make_upload_file(sample_xlsx_file)]
    response = await async_client.post(
        "/api/v1/jobs/upload",
        files=files,
        headers={"Authorization": f"Bearer {user_token}"},
    )
    assert response.status_code == 201
    data = response.json()
    # Verify all expected fields are present
    assert "job_id" in data
    uuid.UUID(data["job_id"])  # validates it's a UUID
    assert "filename" in data
    assert data["filename"] == "contacts.xlsx"
    assert "status" in data
    assert "total_rows" in data
    assert data["total_rows"] == 5
    assert "valid_rows" in data
    assert data["valid_rows"] == 5
    assert "error_rows" in data
    assert data["error_rows"] == 0
    assert "message" in data


async def test_upload_stores_original_file(async_client, user_token, sample_xlsx_file, upload_dir_override):
    """FILE-01: Original file is saved to disk at {upload_dir}/{job_id}/original.xlsx."""
    from pathlib import Path

    files = [make_upload_file(sample_xlsx_file)]
    response = await async_client.post(
        "/api/v1/jobs/upload",
        files=files,
        headers={"Authorization": f"Bearer {user_token}"},
    )
    data = response.json()
    job_id = data["job_id"]
    expected_path = Path(str(upload_dir_override)) / job_id / "original.xlsx"
    assert expected_path.exists(), f"File not saved at {expected_path}"
    assert expected_path.stat().st_size > 0


async def test_upload_creates_job_rows(
    async_client, user_token, sample_xlsx_file, upload_dir_override, test_session
):
    """FILE-01: Each non-empty row gets a JobRow record with UUID and raw_data."""
    files = [make_upload_file(sample_xlsx_file)]
    response = await async_client.post(
        "/api/v1/jobs/upload",
        files=files,
        headers={"Authorization": f"Bearer {user_token}"},
    )
    data = response.json()
    job_id = uuid.UUID(data["job_id"])

    result = await test_session.execute(
        select(JobRow).where(JobRow.job_id == job_id).order_by(JobRow.row_index)
    )
    rows = result.scalars().all()
    assert len(rows) == 5

    # Each row should have a UUID id and raw_data dict
    for i, row in enumerate(rows):
        assert row.id is not None
        assert row.row_index == i
        assert isinstance(row.raw_data, dict)
        assert row.status == "pending"


async def test_upload_rejects_csv(async_client, user_token, csv_file, upload_dir_override):
    """FILE-02: .csv file returns 400 with clear error message."""
    content = csv_file.read_bytes()
    files = [("file", ("data.csv", content, "text/csv"))]
    response = await async_client.post(
        "/api/v1/jobs/upload",
        files=files,
        headers={"Authorization": f"Bearer {user_token}"},
    )
    assert response.status_code == 400
    assert "xlsx" in response.json()["detail"].lower()


async def test_upload_rejects_non_xlsx(async_client, user_token, tmp_path, upload_dir_override):
    """FILE-02: .txt file returns 400."""
    txt_file = tmp_path / "data.txt"
    txt_file.write_text("some text content")
    content = txt_file.read_bytes()
    files = [("file", ("data.txt", content, "text/plain"))]
    response = await async_client.post(
        "/api/v1/jobs/upload",
        files=files,
        headers={"Authorization": f"Bearer {user_token}"},
    )
    assert response.status_code == 400


async def test_upload_rejects_empty_file(async_client, user_token, empty_xlsx_file, upload_dir_override):
    """FILE-02: Empty .xlsx (headers only) returns 400."""
    files = [make_upload_file(empty_xlsx_file)]
    response = await async_client.post(
        "/api/v1/jobs/upload",
        files=files,
        headers={"Authorization": f"Bearer {user_token}"},
    )
    assert response.status_code == 400
    assert "no data rows" in response.json()["detail"].lower()


async def test_upload_requires_auth(async_client, sample_xlsx_file, upload_dir_override):
    """Upload without token returns 401."""
    files = [make_upload_file(sample_xlsx_file)]
    response = await async_client.post(
        "/api/v1/jobs/upload",
        files=files,
    )
    assert response.status_code == 401


async def test_upload_preserves_original(async_client, user_token, sample_xlsx_file, upload_dir_override):
    """FILE-02: Original file content matches uploaded content byte-for-byte."""
    from pathlib import Path

    original_content = sample_xlsx_file.read_bytes()
    files = [make_upload_file(sample_xlsx_file)]
    response = await async_client.post(
        "/api/v1/jobs/upload",
        files=files,
        headers={"Authorization": f"Bearer {user_token}"},
    )
    data = response.json()
    job_id = data["job_id"]
    saved_path = Path(str(upload_dir_override)) / job_id / "original.xlsx"
    saved_content = saved_path.read_bytes()
    assert saved_content == original_content


async def test_get_job_wrong_user(async_client, admin_token, user_token, sample_xlsx_file, upload_dir_override):
    """User A cannot access User B's job -- returns 404."""
    # Upload as regular user
    files = [make_upload_file(sample_xlsx_file)]
    response = await async_client.post(
        "/api/v1/jobs/upload",
        files=files,
        headers={"Authorization": f"Bearer {user_token}"},
    )
    job_id = response.json()["job_id"]

    # Try to access as admin (different user)
    response = await async_client.get(
        f"/api/v1/jobs/{job_id}",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert response.status_code == 404
