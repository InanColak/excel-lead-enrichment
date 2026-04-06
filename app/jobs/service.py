import uuid
from pathlib import Path

from fastapi import HTTPException, UploadFile, status
from openpyxl import load_workbook
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.jobs.models import Job, JobRow, JobStatus, RowStatus


def validate_upload(file: UploadFile) -> None:
    """Validate uploaded file format and content type.

    Raises HTTPException(400) for invalid format, HTTPException(413) for oversized files.
    """
    # Check file extension
    if file.filename is None or not file.filename.lower().endswith(".xlsx"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Only .xlsx files are accepted. Please convert .xls or .csv files to .xlsx format.",
        )

    # Check content type — allow common Excel MIME types and octet-stream (browser default)
    allowed_types = {
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "application/octet-stream",
    }
    if file.content_type and file.content_type not in allowed_types:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid content type '{file.content_type}'. Expected an Excel .xlsx file.",
        )


async def check_file_size(file: UploadFile) -> bytes:
    """Read the file content and check size against max_upload_size_mb.

    Returns the file content bytes if within limits.
    Raises HTTPException(413) if file exceeds size limit.
    """
    max_bytes = settings.max_upload_size_mb * 1024 * 1024
    content = await file.read()
    if len(content) > max_bytes:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"File size exceeds the {settings.max_upload_size_mb}MB limit.",
        )
    return content


def save_uploaded_file(job_id: uuid.UUID, content: bytes) -> str:
    """Save uploaded file content to disk at {upload_dir}/{job_id}/original.xlsx.

    Returns the file path as a string.
    """
    job_dir = Path(settings.upload_dir) / str(job_id)
    job_dir.mkdir(parents=True, exist_ok=True)
    file_path = job_dir / "original.xlsx"
    file_path.write_bytes(content)
    return str(file_path)


def parse_excel_file(file_path: str) -> tuple[list[str], list[dict]]:
    """Parse an Excel file using openpyxl in read_only mode.

    Reads the first sheet only. Returns (headers, rows) where each row is a dict
    keyed by column header name.

    Raises HTTPException(400) for empty files or files exceeding max rows.
    """
    wb = load_workbook(file_path, read_only=True, data_only=True)
    try:
        ws = wb.active
        if ws is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="The Excel file contains no sheets.",
            )

        rows_iter = ws.iter_rows()

        # Read header row
        try:
            header_row = next(rows_iter)
        except StopIteration:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="The Excel file is empty (no header row found).",
            )

        headers = []
        for cell in header_row:
            val = str(cell.value).strip() if cell.value is not None else ""
            headers.append(val)

        # Check we have at least one non-empty header
        if not any(h for h in headers):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="The Excel file has no valid column headers.",
            )

        # Read data rows
        data_rows: list[dict] = []
        max_rows = settings.max_rows_per_file

        for row in rows_iter:
            # Extract cell values
            values = [cell.value for cell in row]

            # Skip completely empty rows (all cells None or empty string)
            if all(v is None or (isinstance(v, str) and v.strip() == "") for v in values):
                continue

            if len(data_rows) >= max_rows:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"File exceeds the maximum of {max_rows} rows.",
                )

            # Build dict keyed by header
            row_dict = {}
            for i, header in enumerate(headers):
                if i < len(values):
                    val = values[i]
                    # Convert to string for consistent JSONB storage, keep None as None
                    if val is not None:
                        row_dict[header] = str(val) if not isinstance(val, (int, float, bool)) else val
                    else:
                        row_dict[header] = None
                else:
                    row_dict[header] = None

            data_rows.append(row_dict)

        if len(data_rows) == 0:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="The Excel file has no data rows (header only).",
            )

        return headers, data_rows
    finally:
        wb.close()


async def create_job_from_upload(
    db: AsyncSession, user_id: uuid.UUID, file: UploadFile
) -> Job:
    """Orchestrate the full upload flow: validate, save, parse, create records.

    Returns the created Job with status PENDING_CONFIRMATION.
    """
    # 1. Validate format and content type
    validate_upload(file)

    # 2. Read and check file size
    content = await check_file_size(file)

    # 3. Create Job record with status UPLOADING
    job = Job(
        user_id=user_id,
        filename=file.filename or "unknown.xlsx",
        file_path="",  # Will be updated after save
        status=JobStatus.UPLOADING.value,
    )
    db.add(job)
    await db.flush()  # Get the generated UUID

    # 4. Save file to disk
    file_path = save_uploaded_file(job.id, content)
    job.file_path = file_path

    # 5. Parse Excel file
    _headers, data_rows = parse_excel_file(file_path)

    # 6. Create JobRow records for each non-empty row
    valid_count = 0
    for idx, row_data in enumerate(data_rows):
        job_row = JobRow(
            job_id=job.id,
            row_index=idx,
            raw_data=row_data,
            status=RowStatus.PENDING.value,
        )
        db.add(job_row)
        valid_count += 1

    # 7. Update Job with counts and transition to PENDING_CONFIRMATION
    job.status = JobStatus.PENDING_CONFIRMATION.value
    job.total_rows = valid_count
    job.valid_rows = valid_count
    job.error_rows = 0

    await db.flush()

    return job


async def get_job_by_id(
    db: AsyncSession, job_id: uuid.UUID, user_id: uuid.UUID
) -> Job:
    """Load a job by ID, verifying it belongs to the requesting user.

    Raises HTTPException(404) if not found or wrong user.
    """
    result = await db.execute(select(Job).where(Job.id == job_id))
    job = result.scalar_one_or_none()

    if job is None or job.user_id != user_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Job not found.",
        )

    return job
