---
phase: 02-file-ingestion
plan: 01
subsystem: api
tags: [fastapi, openpyxl, sqlalchemy, excel, upload, jsonb]

requires:
  - phase: 01-foundation
    provides: Base/UUIDMixin/TimestampMixin models, User model, auth dependencies, Docker infrastructure

provides:
  - Job and JobRow SQLAlchemy models with UUID PKs and status enums
  - POST /api/v1/jobs/upload endpoint with .xlsx validation and parsing
  - GET /api/v1/jobs/{job_id} endpoint with user ownership check
  - Alembic migration for jobs and job_rows tables
  - File storage pipeline saving originals to /data/uploads/{job_id}/original.xlsx

affects: [02-file-ingestion, 03-enrichment-pipeline, 04-output-download]

tech-stack:
  added: [openpyxl]
  patterns: [file-upload-validation, excel-parsing-read-only, job-row-uuid-tagging]

key-files:
  created:
    - app/jobs/__init__.py
    - app/jobs/models.py
    - app/jobs/schemas.py
    - app/jobs/service.py
    - app/jobs/routes.py
    - alembic/versions/d0e48f167723_add_jobs_and_job_rows_tables.py
  modified:
    - app/config.py
    - app/models/__init__.py
    - app/main.py
    - docker-compose.yml
    - docker-compose.override.yml

key-decisions:
  - "String(50) for status columns instead of SQLAlchemy Enum type for portability"
  - "File content read fully into memory before size check to avoid partial disk writes"
  - "All non-empty rows stored as PENDING at upload time; malformed row detection deferred to column mapping confirmation step"

patterns-established:
  - "Upload validation: extension check, content-type check, size check before disk write"
  - "Excel parsing: openpyxl read_only=True, first sheet only, row count limit enforced during iteration"
  - "Job ownership: service layer verifies user_id match, returns 404 for wrong user (no information leakage)"

requirements-completed: [FILE-01, FILE-02, FILE-05]

duration: 3min
completed: 2026-04-06
---

# Phase 2 Plan 1: File Upload and Parsing Summary

**Job/JobRow models with 9-state status machine, .xlsx upload endpoint with format/size/row validation, openpyxl parsing to JSONB rows, and Docker volume storage**

## Performance

- **Duration:** 3 min
- **Started:** 2026-04-06T15:06:45Z
- **Completed:** 2026-04-06T15:10:06Z
- **Tasks:** 2
- **Files modified:** 11

## Accomplishments
- Job and JobRow models with full status enums (9 job states, 5 row states), UUID PKs, timestamps, and foreign keys to users and contacts
- Upload endpoint that validates .xlsx format, content type, file size (10MB limit), and row count (10,000 limit) before persisting
- Excel parsing with openpyxl read_only mode, storing each non-empty row as JSONB with unique UUID
- Original files preserved at /data/uploads/{job_id}/original.xlsx with Docker named volume

## Task Commits

Each task was committed atomically:

1. **Task 1: Job and JobRow models + Settings + Migration** - `e8fe8a1` (feat)
2. **Task 2: Upload endpoint with validation and Excel parsing** - `aa6be75` (feat)

## Files Created/Modified
- `app/jobs/__init__.py` - Empty module init
- `app/jobs/models.py` - Job, JobRow models with JobStatus/RowStatus enums
- `app/jobs/schemas.py` - JobResponse, JobRowResponse, UploadResponse Pydantic schemas
- `app/jobs/service.py` - Upload validation, file save, Excel parsing, job creation orchestration
- `app/jobs/routes.py` - POST /upload and GET /{job_id} endpoints with auth
- `alembic/versions/d0e48f167723_add_jobs_and_job_rows_tables.py` - Migration for jobs/job_rows tables
- `app/config.py` - Added upload_dir, max_upload_size_mb, max_rows_per_file settings
- `app/models/__init__.py` - Added jobs model registration for Alembic
- `app/main.py` - Registered jobs router at /api/v1/jobs
- `docker-compose.yml` - Added upload_data volume on api and worker services
- `docker-compose.override.yml` - Added dev upload mount on api and worker services

## Decisions Made
- Used String(50) for status columns instead of SQLAlchemy Enum type -- more portable across databases and easier to add new statuses without migration
- Read full file content into memory before size check to prevent partial disk writes on oversized files
- All non-empty rows stored as PENDING at upload time -- malformed row detection happens after column mapping confirmation (Plan 02), since we don't know which columns are identifiers yet
- Allowed application/octet-stream content type alongside the standard xlsx MIME type, since browsers may send either

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered
None

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- Job and JobRow models ready for column detection (Plan 02-02) to add column_mappings
- Upload pipeline stores parsed rows that enrichment (Phase 3) will consume
- Docker volume ensures file persistence across container restarts
- Alembic migration ready to run on container startup

## Self-Check: PASSED

- All 6 created files exist on disk
- Commit e8fe8a1 (Task 1) verified in git log
- Commit aa6be75 (Task 2) verified in git log
- Models import and register correctly (5 tables in Base.metadata)
- Routes /api/v1/jobs/upload and /api/v1/jobs/{job_id} registered in app

---
*Phase: 02-file-ingestion*
*Completed: 2026-04-06*
