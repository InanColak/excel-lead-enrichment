import uuid

from fastapi import APIRouter, Depends, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.models import User
from app.deps import get_current_user, get_db
from app.jobs.schemas import (
    ColumnMappingsOverrideRequest,
    ColumnMappingsResponse,
    ConfirmResponse,
    JobResponse,
    UploadResponse,
)
from app.jobs.service import (
    confirm_job,
    create_job_from_upload,
    get_column_mappings,
    get_job_by_id,
    override_column_mappings,
)

router = APIRouter(tags=["jobs"])


@router.post("/upload", response_model=UploadResponse, status_code=201)
async def upload_file(
    file: UploadFile,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Upload an Excel file for enrichment processing."""
    job = await create_job_from_upload(db, user.id, file)
    return UploadResponse(
        job_id=job.id,
        filename=job.filename,
        status=job.status,
        total_rows=job.total_rows,
        valid_rows=job.valid_rows,
        error_rows=job.error_rows,
        message="File uploaded and parsed. Review column mappings before confirming.",
    )


@router.get("/{job_id}", response_model=JobResponse)
async def get_job(
    job_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Retrieve job details by ID. Only accessible by the job owner."""
    job = await get_job_by_id(db, job_id, user.id)
    return job


@router.get("/{job_id}/mappings", response_model=ColumnMappingsResponse)
async def get_mappings(
    job_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get auto-detected column mappings for a job.

    On first call, runs column detection and caches results.
    Only available for jobs in PENDING_CONFIRMATION status.
    """
    mappings = await get_column_mappings(db, job_id, user.id)
    return ColumnMappingsResponse(job_id=job_id, mappings=mappings)


@router.put("/{job_id}/mappings", response_model=ColumnMappingsResponse)
async def update_mappings(
    job_id: uuid.UUID,
    body: ColumnMappingsOverrideRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Override column mappings with user-corrected types.

    Merges overrides with existing mappings. Only specified columns are updated.
    Only available for jobs in PENDING_CONFIRMATION status.
    """
    mappings = await override_column_mappings(db, job_id, user.id, body.mappings)
    return ColumnMappingsResponse(job_id=job_id, mappings=mappings)


@router.post("/{job_id}/confirm", response_model=ConfirmResponse)
async def confirm_job_endpoint(
    job_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Confirm column mappings and transition job to CONFIRMED status.

    Flags rows with no contact identifiers as ERROR.
    Requires column_mappings to be set (call GET /mappings first).
    """
    job = await confirm_job(db, job_id, user.id)
    return ConfirmResponse(
        job_id=job.id,
        status=job.status,
        total_rows=job.total_rows,
        valid_rows=job.valid_rows,
        error_rows=job.error_rows,
        message="Job confirmed. Rows flagged as errors have no contact identifiers.",
    )
