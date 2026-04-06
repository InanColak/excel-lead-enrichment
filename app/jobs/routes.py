import uuid

from fastapi import APIRouter, Depends, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.models import User
from app.deps import get_current_user, get_db
from app.jobs.schemas import JobResponse, UploadResponse
from app.jobs.service import create_job_from_upload, get_job_by_id

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
