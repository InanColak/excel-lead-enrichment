"""FILE-03 and FILE-04: Mapping detection and override integration tests."""

from pathlib import Path

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


async def test_get_mappings_auto_detect(async_client, user_token, sample_xlsx_file, upload_dir_override):
    """FILE-03: GET /mappings returns auto-detected column types with confidence."""
    job_id = await _upload_and_get_job_id(async_client, user_token, sample_xlsx_file)

    response = await async_client.get(
        f"/api/v1/jobs/{job_id}/mappings",
        headers={"Authorization": f"Bearer {user_token}"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["job_id"] == job_id
    assert len(data["mappings"]) > 0

    # Each mapping should have column, detected_type, confidence
    for mapping in data["mappings"]:
        assert "column" in mapping
        assert "detected_type" in mapping
        assert "confidence" in mapping


async def test_get_mappings_returns_all_columns(async_client, user_token, sample_xlsx_file, upload_dir_override):
    """All columns from the Excel file appear in mappings response."""
    job_id = await _upload_and_get_job_id(async_client, user_token, sample_xlsx_file)

    response = await async_client.get(
        f"/api/v1/jobs/{job_id}/mappings",
        headers={"Authorization": f"Bearer {user_token}"},
    )
    data = response.json()
    columns = [m["column"] for m in data["mappings"]]
    assert "First Name" in columns
    assert "Last Name" in columns
    assert "Email" in columns
    assert "Company" in columns
    assert "LinkedIn" in columns


async def test_get_mappings_cached(async_client, user_token, sample_xlsx_file, upload_dir_override):
    """Second GET /mappings returns same results (cached in column_mappings JSONB)."""
    job_id = await _upload_and_get_job_id(async_client, user_token, sample_xlsx_file)

    # First call triggers detection
    response1 = await async_client.get(
        f"/api/v1/jobs/{job_id}/mappings",
        headers={"Authorization": f"Bearer {user_token}"},
    )
    # Second call returns cached
    response2 = await async_client.get(
        f"/api/v1/jobs/{job_id}/mappings",
        headers={"Authorization": f"Bearer {user_token}"},
    )

    assert response1.json() == response2.json()


async def test_override_single_column(async_client, user_token, sample_xlsx_file, upload_dir_override):
    """FILE-04: PUT /mappings with one override updates only that column."""
    job_id = await _upload_and_get_job_id(async_client, user_token, sample_xlsx_file)

    # First detect
    await async_client.get(
        f"/api/v1/jobs/{job_id}/mappings",
        headers={"Authorization": f"Bearer {user_token}"},
    )

    # Override one column
    response = await async_client.put(
        f"/api/v1/jobs/{job_id}/mappings",
        json={"mappings": [{"column": "First Name", "mapped_type": "full_name"}]},
        headers={"Authorization": f"Bearer {user_token}"},
    )
    assert response.status_code == 200
    data = response.json()

    # Find the overridden column
    overridden = next(m for m in data["mappings"] if m["column"] == "First Name")
    assert overridden["detected_type"] == "full_name"
    assert overridden["confidence"] == "HIGH"  # User override = HIGH


async def test_override_multiple_columns(async_client, user_token, sample_xlsx_file, upload_dir_override):
    """FILE-04: PUT /mappings with multiple overrides updates all specified columns."""
    job_id = await _upload_and_get_job_id(async_client, user_token, sample_xlsx_file)

    # Detect first
    await async_client.get(
        f"/api/v1/jobs/{job_id}/mappings",
        headers={"Authorization": f"Bearer {user_token}"},
    )

    # Override two columns
    response = await async_client.put(
        f"/api/v1/jobs/{job_id}/mappings",
        json={
            "mappings": [
                {"column": "First Name", "mapped_type": "full_name"},
                {"column": "Company", "mapped_type": "domain"},
            ]
        },
        headers={"Authorization": f"Bearer {user_token}"},
    )
    assert response.status_code == 200
    data = response.json()

    types = {m["column"]: m["detected_type"] for m in data["mappings"]}
    assert types["First Name"] == "full_name"
    assert types["Company"] == "domain"


async def test_override_preserves_unspecified(async_client, user_token, sample_xlsx_file, upload_dir_override):
    """FILE-04: PUT /mappings does not change columns not included in the override."""
    job_id = await _upload_and_get_job_id(async_client, user_token, sample_xlsx_file)

    # Detect first
    detect_resp = await async_client.get(
        f"/api/v1/jobs/{job_id}/mappings",
        headers={"Authorization": f"Bearer {user_token}"},
    )
    original = {m["column"]: m["detected_type"] for m in detect_resp.json()["mappings"]}

    # Override only First Name
    override_resp = await async_client.put(
        f"/api/v1/jobs/{job_id}/mappings",
        json={"mappings": [{"column": "First Name", "mapped_type": "full_name"}]},
        headers={"Authorization": f"Bearer {user_token}"},
    )
    updated = {m["column"]: m["detected_type"] for m in override_resp.json()["mappings"]}

    # First Name changed
    assert updated["First Name"] == "full_name"
    # Others unchanged
    assert updated["Email"] == original["Email"]
    assert updated["Company"] == original["Company"]
    assert updated["LinkedIn"] == original["LinkedIn"]


async def test_override_invalid_type_rejected(async_client, user_token, sample_xlsx_file, upload_dir_override):
    """FILE-04: PUT /mappings with invalid mapped_type returns 422."""
    job_id = await _upload_and_get_job_id(async_client, user_token, sample_xlsx_file)

    # Detect first
    await async_client.get(
        f"/api/v1/jobs/{job_id}/mappings",
        headers={"Authorization": f"Bearer {user_token}"},
    )

    response = await async_client.put(
        f"/api/v1/jobs/{job_id}/mappings",
        json={"mappings": [{"column": "Email", "mapped_type": "invalid_type_xyz"}]},
        headers={"Authorization": f"Bearer {user_token}"},
    )
    assert response.status_code == 422


async def test_override_multiple_times(async_client, user_token, sample_xlsx_file, upload_dir_override):
    """FILE-04: User can override mappings multiple times before confirming."""
    job_id = await _upload_and_get_job_id(async_client, user_token, sample_xlsx_file)

    # Detect first
    await async_client.get(
        f"/api/v1/jobs/{job_id}/mappings",
        headers={"Authorization": f"Bearer {user_token}"},
    )

    # First override
    await async_client.put(
        f"/api/v1/jobs/{job_id}/mappings",
        json={"mappings": [{"column": "First Name", "mapped_type": "full_name"}]},
        headers={"Authorization": f"Bearer {user_token}"},
    )

    # Second override (change it back)
    response = await async_client.put(
        f"/api/v1/jobs/{job_id}/mappings",
        json={"mappings": [{"column": "First Name", "mapped_type": "first_name"}]},
        headers={"Authorization": f"Bearer {user_token}"},
    )
    assert response.status_code == 200
    types = {m["column"]: m["detected_type"] for m in response.json()["mappings"]}
    assert types["First Name"] == "first_name"


async def test_mappings_wrong_user_404(async_client, admin_token, user_token, sample_xlsx_file, upload_dir_override):
    """Accessing another user's job mappings returns 404."""
    job_id = await _upload_and_get_job_id(async_client, user_token, sample_xlsx_file)

    response = await async_client.get(
        f"/api/v1/jobs/{job_id}/mappings",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert response.status_code == 404


async def test_mappings_wrong_status_409(async_client, user_token, sample_xlsx_file, upload_dir_override):
    """Accessing mappings on a CONFIRMED job returns 409."""
    job_id = await _upload_and_get_job_id(async_client, user_token, sample_xlsx_file)

    # Detect, then confirm
    await async_client.get(
        f"/api/v1/jobs/{job_id}/mappings",
        headers={"Authorization": f"Bearer {user_token}"},
    )
    await async_client.post(
        f"/api/v1/jobs/{job_id}/confirm",
        headers={"Authorization": f"Bearer {user_token}"},
    )

    # Try to access mappings after confirmation
    response = await async_client.get(
        f"/api/v1/jobs/{job_id}/mappings",
        headers={"Authorization": f"Bearer {user_token}"},
    )
    assert response.status_code == 409
