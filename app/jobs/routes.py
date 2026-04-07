import uuid
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.models import User
from app.deps import get_current_user, get_db
from app.jobs.schemas import (
    ColumnMappingsOverrideRequest,
    ColumnMappingsResponse,
    ConfirmResponse,
    JobResponse,
    PaginatedJobsResponse,
    UploadResponse,
    UsageStatsResponse,
)
from app.jobs.service import (
    confirm_job,
    create_job_from_upload,
    get_column_mappings,
    get_job_by_id,
    get_user_stats,
    list_jobs,
    override_column_mappings,
)

router = APIRouter(tags=["jobs"])
stats_router = APIRouter(tags=["stats"])


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


# List endpoint BEFORE /{job_id} to avoid path matching conflicts
@router.get("/", response_model=PaginatedJobsResponse)
async def list_jobs_endpoint(
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    status_filter: str | None = Query(default=None, alias="status"),
    created_after: datetime | None = Query(default=None),
    created_before: datetime | None = Query(default=None),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List user's jobs with pagination, status filter, and date range filter."""
    jobs, total = await list_jobs(
        db, user.id, limit, offset, status_filter, created_after, created_before
    )
    return PaginatedJobsResponse(
        items=[JobResponse.model_validate(j) for j in jobs],
        total=total,
        limit=limit,
        offset=offset,
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


@router.get("/{job_id}/download")
async def download_enriched_file(
    job_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Download the enriched Excel file for a completed job."""
    job = await get_job_by_id(db, job_id, user.id)
    if not job.output_file_path:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Output file not available. Job status: {job.status}",
        )
    file_path = Path(job.output_file_path)
    if not file_path.exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Output file not found on server.",
        )
    return FileResponse(
        path=str(file_path),
        filename=f"{Path(job.filename).stem}_enriched.xlsx",
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


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


# Stats endpoint — mounted separately at /api/v1/stats in main.py per D-62
@stats_router.get("/", response_model=UsageStatsResponse)
async def get_stats(
    since: datetime | None = Query(default=None),
    until: datetime | None = Query(default=None),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get usage statistics for the authenticated user."""
    stats = await get_user_stats(db, user.id, since, until)
    return UsageStatsResponse(**stats)
