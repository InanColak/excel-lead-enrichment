"""FILE-05: Confirm flow and malformed row integration tests."""

import uuid
from pathlib import Path

from openpyxl import Workbook
from sqlalchemy import select

from app.jobs.models import JobRow
from tests.conftest import make_upload_file


async def _upload_and_get_job_id(async_client, user_token, xlsx_path: Path) -> str:
    """Helper: upload a file and return the job_id."""
    files = [make_upload_file(xlsx_path)]
    response = await async_client.post(
        "/api/v1/jobs/upload",
        files=files,
        headers={"Authorization": f"Bearer {user_token}"},
    )
    assert response.status_code == 201
    return response.json()["job_id"]


async def _detect_mappings(async_client, user_token, job_id: str) -> dict:
    """Helper: trigger column detection and return mappings response."""
    response = await async_client.get(
        f"/api/v1/jobs/{job_id}/mappings",
        headers={"Authorization": f"Bearer {user_token}"},
    )
    assert response.status_code == 200
    return response.json()


async def test_confirm_transitions_status(async_client, user_token, sample_xlsx_file, upload_dir_override):
    """POST /confirm transitions job from PENDING_CONFIRMATION to CONFIRMED."""
    job_id = await _upload_and_get_job_id(async_client, user_token, sample_xlsx_file)
    await _detect_mappings(async_client, user_token, job_id)

    response = await async_client.post(
        f"/api/v1/jobs/{job_id}/confirm",
        headers={"Authorization": f"Bearer {user_token}"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "confirmed"


async def test_confirm_flags_malformed_rows(async_client, user_token, malformed_xlsx_file, upload_dir_override):
    """FILE-05: Rows with no contact identifiers flagged as ERROR after confirm."""
    job_id = await _upload_and_get_job_id(async_client, user_token, malformed_xlsx_file)
    await _detect_mappings(async_client, user_token, job_id)

    response = await async_client.post(
        f"/api/v1/jobs/{job_id}/confirm",
        headers={"Authorization": f"Bearer {user_token}"},
    )
    assert response.status_code == 200
    data = response.json()
    # All 3 rows should be errors (no contact identifiers in Notes/Random)
    assert data["error_rows"] == 3
    assert data["valid_rows"] == 0


async def test_confirm_malformed_row_has_error_message(
    async_client, user_token, malformed_xlsx_file, upload_dir_override, test_session
):
    """FILE-05: Flagged rows have descriptive error_message set."""
    job_id = await _upload_and_get_job_id(async_client, user_token, malformed_xlsx_file)
    await _detect_mappings(async_client, user_token, job_id)

    await async_client.post(
        f"/api/v1/jobs/{job_id}/confirm",
        headers={"Authorization": f"Bearer {user_token}"},
    )

    result = await test_session.execute(
        select(JobRow).where(JobRow.job_id == uuid.UUID(job_id)).order_by(JobRow.row_index)
    )
    rows = result.scalars().all()
    for row in rows:
        assert row.status == "error"
        assert row.error_message is not None
        assert "no contact identifiers" in row.error_message.lower()


async def test_confirm_keeps_valid_rows_pending(
    async_client, user_token, sample_xlsx_file, upload_dir_override, test_session
):
    """FILE-05: Rows with at least one contact identifier remain PENDING."""
    job_id = await _upload_and_get_job_id(async_client, user_token, sample_xlsx_file)
    await _detect_mappings(async_client, user_token, job_id)

    response = await async_client.post(
        f"/api/v1/jobs/{job_id}/confirm",
        headers={"Authorization": f"Bearer {user_token}"},
    )
    data = response.json()
    assert data["valid_rows"] == 5
    assert data["error_rows"] == 0

    # Verify in DB that rows are still PENDING
    result = await test_session.execute(
        select(JobRow).where(JobRow.job_id == uuid.UUID(job_id)).order_by(JobRow.row_index)
    )
    rows = result.scalars().all()
    for row in rows:
        assert row.status == "pending"
        assert row.error_message is None


async def test_confirm_partial_rows_not_flagged(async_client, user_token, upload_dir_override, tmp_path):
    """FILE-05: Row with only company (no name/email) remains PENDING per D-33.

    Company is a contact identifier, so a row with only company data should not be flagged.
    """
    # Create xlsx with a row that has company but no name/email
    wb = Workbook()
    ws = wb.active
    ws.append(["First Name", "Last Name", "Email", "Company"])
    ws.append([None, None, None, "Acme Corp"])  # Only company
    ws.append(["John", "Doe", "john@example.com", "Globex"])  # Full row
    path = tmp_path / "partial.xlsx"
    wb.save(path)

    job_id = await _upload_and_get_job_id(async_client, user_token, path)
    await _detect_mappings(async_client, user_token, job_id)

    response = await async_client.post(
        f"/api/v1/jobs/{job_id}/confirm",
        headers={"Authorization": f"Bearer {user_token}"},
    )
    data = response.json()
    # Both rows should be valid -- company alone counts as identifier
    assert data["valid_rows"] == 2
    assert data["error_rows"] == 0


async def test_confirm_updates_row_counts(async_client, user_token, upload_dir_override, tmp_path):
    """After confirm, job.valid_rows and error_rows reflect the flagging results."""
    # Create a mixed file: some rows with identifiers, some without
    wb = Workbook()
    ws = wb.active
    ws.append(["First Name", "Email", "Notes"])
    ws.append(["John", "john@example.com", "good lead"])  # valid
    ws.append([None, None, "no contact info"])  # malformed
    ws.append(["Jane", "jane@smith.co", "another lead"])  # valid
    path = tmp_path / "mixed.xlsx"
    wb.save(path)

    job_id = await _upload_and_get_job_id(async_client, user_token, path)
    await _detect_mappings(async_client, user_token, job_id)

    response = await async_client.post(
        f"/api/v1/jobs/{job_id}/confirm",
        headers={"Authorization": f"Bearer {user_token}"},
    )
    data = response.json()
    assert data["total_rows"] == 3
    assert data["valid_rows"] == 2
    assert data["error_rows"] == 1


async def test_confirm_requires_mappings(async_client, user_token, sample_xlsx_file, upload_dir_override):
    """Confirming before GET /mappings returns 400 (no column_mappings set)."""
    job_id = await _upload_and_get_job_id(async_client, user_token, sample_xlsx_file)

    # Try to confirm without detecting mappings first
    response = await async_client.post(
        f"/api/v1/jobs/{job_id}/confirm",
        headers={"Authorization": f"Bearer {user_token}"},
    )
    assert response.status_code == 400
    assert "mappings" in response.json()["detail"].lower()


async def test_confirm_wrong_status_409(async_client, user_token, sample_xlsx_file, upload_dir_override):
    """Confirming an already-confirmed job returns 409."""
    job_id = await _upload_and_get_job_id(async_client, user_token, sample_xlsx_file)
    await _detect_mappings(async_client, user_token, job_id)

    # First confirm succeeds
    response1 = await async_client.post(
        f"/api/v1/jobs/{job_id}/confirm",
        headers={"Authorization": f"Bearer {user_token}"},
    )
    assert response1.status_code == 200

    # Second confirm should fail with 409
    response2 = await async_client.post(
        f"/api/v1/jobs/{job_id}/confirm",
        headers={"Authorization": f"Bearer {user_token}"},
    )
    assert response2.status_code == 409


async def test_confirm_wrong_user_404(async_client, admin_token, user_token, sample_xlsx_file, upload_dir_override):
    """Confirming another user's job returns 404."""
    job_id = await _upload_and_get_job_id(async_client, user_token, sample_xlsx_file)
    await _detect_mappings(async_client, user_token, job_id)

    response = await async_client.post(
        f"/api/v1/jobs/{job_id}/confirm",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert response.status_code == 404


async def test_full_flow_upload_detect_override_confirm(
    async_client, user_token, sample_xlsx_file, upload_dir_override
):
    """End-to-end: upload -> get mappings -> override -> confirm -> verify final state."""
    # 1. Upload
    job_id = await _upload_and_get_job_id(async_client, user_token, sample_xlsx_file)

    # 2. Get auto-detected mappings
    mappings_resp = await _detect_mappings(async_client, user_token, job_id)
    assert len(mappings_resp["mappings"]) == 5

    # 3. Override one column
    override_resp = await async_client.put(
        f"/api/v1/jobs/{job_id}/mappings",
        json={"mappings": [{"column": "LinkedIn", "mapped_type": "domain"}]},
        headers={"Authorization": f"Bearer {user_token}"},
    )
    assert override_resp.status_code == 200
    overridden = next(m for m in override_resp.json()["mappings"] if m["column"] == "LinkedIn")
    assert overridden["detected_type"] == "domain"
    assert overridden["confidence"] == "HIGH"

    # 4. Confirm
    confirm_resp = await async_client.post(
        f"/api/v1/jobs/{job_id}/confirm",
        headers={"Authorization": f"Bearer {user_token}"},
    )
    assert confirm_resp.status_code == 200
    data = confirm_resp.json()
    assert data["status"] == "confirmed"
    assert data["valid_rows"] == 5
    assert data["error_rows"] == 0

    # 5. Verify job is now confirmed via GET
    job_resp = await async_client.get(
        f"/api/v1/jobs/{job_id}",
        headers={"Authorization": f"Bearer {user_token}"},
    )
    assert job_resp.status_code == 200
    assert job_resp.json()["status"] == "confirmed"
