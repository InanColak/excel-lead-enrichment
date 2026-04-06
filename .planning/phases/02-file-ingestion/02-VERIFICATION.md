---
phase: 02-file-ingestion
verified: 2026-04-06T16:00:00Z
status: human_needed
score: 5/5 must-haves verified
gaps: []
human_verification:
  - test: "Run the full test suite inside Docker: docker compose exec api pytest tests/jobs/ -v"
    expected: "All 50 tests pass (11 upload, 18 detection, 10 mapping, 11 confirm). No failures or errors."
    why_human: "Tests require a live PostgreSQL database. Cannot execute programmatically in this environment."
  - test: "POST /api/v1/jobs/upload with a valid .xlsx file, then GET /api/v1/jobs/{job_id}/mappings, then PUT to override one column, then POST /api/v1/jobs/{job_id}/confirm"
    expected: "Upload returns 201 with job_id and status=pending_confirmation. Mappings returns detected types with confidence. Override returns updated mapping with confidence=HIGH. Confirm returns status=confirmed with updated row counts."
    why_human: "End-to-end flow validation requires a running Docker stack (API + PostgreSQL + Redis)."
  - test: "Upload a .csv file — expect 400. Upload a file >10MB — expect 413. Upload a header-only .xlsx — expect 400."
    expected: "Each invalid upload returns the correct HTTP error code with a descriptive message."
    why_human: "Requires a running API server."
---

# Phase 2: File Ingestion Verification Report

**Phase Goal:** Users can upload Excel files, receive validated parse results with auto-detected column mappings, override those mappings, and confirm before enrichment begins — with every row assigned a unique UUID
**Verified:** 2026-04-06T16:00:00Z
**Status:** human_needed
**Re-verification:** No — initial verification

## Goal Achievement

### Observable Truths (Roadmap Success Criteria)

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | Uploading a valid Excel file returns a job ID, stores the original file unmodified, and sets job status to `PENDING_CONFIRMATION` | VERIFIED | `create_job_from_upload` saves file to `{upload_dir}/{job_id}/original.xlsx`, sets `status=PENDING_CONFIRMATION.value`, returns Job with UUID. Upload endpoint returns `UploadResponse` with `job_id`. |
| 2 | Uploading an invalid file (wrong format, oversized, malformed structure) returns a clear error and no job is created | VERIFIED | `validate_upload` raises 400 for non-.xlsx; `check_file_size` raises 413 for >10MB; `parse_excel_file` raises 400 for header-only files. Job record creation is deferred until after all validation passes. |
| 3 | The API returns auto-detected column mappings with confidence indicators for a successfully parsed file | VERIFIED | `detection.py` implements two-pass strategy (header matching + content sampling regex). `detect_column_types()` returns `[{"column", "detected_type", "confidence"}]` per column. GET `/mappings` endpoint caches results in `job.column_mappings` JSONB. |
| 4 | A user can submit corrected column mappings via API override before enrichment starts | VERIFIED | PUT `/{job_id}/mappings` calls `override_column_mappings()` which merges overrides with existing mappings (unspecified columns preserved), validates `mapped_type` against `COLUMN_TYPES` whitelist, sets confidence to HIGH for overridden columns. Multiple overrides before confirm are supported. |
| 5 | Every parsed row has a unique UUID assigned before any downstream processing; malformed rows are flagged per-row without aborting the job | VERIFIED | `JobRow` inherits `UUIDMixin` (UUID PK generated at creation time). `confirm_job()` scans all rows, sets `status=ERROR` + `error_message` for rows with no contact identifiers, keeps valid rows as `PENDING`. Job transitions to `CONFIRMED` regardless of error count. |

**Score:** 5/5 truths verified

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `app/jobs/models.py` | Job and JobRow SQLAlchemy models with status enums | VERIFIED | `Job` with 9-state `JobStatus` enum, `JobRow` with 5-state `RowStatus` enum. Both inherit `UUIDMixin` + `TimestampMixin`. `job_rows.job_id` has `index=True`. |
| `app/jobs/detection.py` | Column type detection with header matching and content sampling | VERIFIED | Pure-function module. `detect_column_types(headers, sample_rows)` implements two-pass detection for 8 column types with HIGH/MEDIUM/UNKNOWN confidence. `get_contact_identifier_columns()` returns correct 6-type set. |
| `app/jobs/routes.py` | Upload, mapping review/override, and confirm endpoints | VERIFIED | 5 endpoints: POST /upload, GET /{job_id}, GET /{job_id}/mappings, PUT /{job_id}/mappings, POST /{job_id}/confirm. All use `Depends(get_current_user)`. |
| `app/jobs/service.py` | File validation, parsing, mapping, and confirm logic | VERIFIED | `validate_upload`, `check_file_size`, `save_uploaded_file`, `parse_excel_file`, `create_job_from_upload`, `get_column_mappings`, `override_column_mappings`, `confirm_job` — all substantive implementations present. |
| `app/jobs/schemas.py` | Pydantic request/response schemas | VERIFIED | `JobResponse`, `JobRowResponse`, `UploadResponse`, `ColumnMappingEntry`, `ColumnMappingsResponse`, `ColumnMappingOverride`, `ColumnMappingsOverrideRequest`, `ConfirmResponse`. All with `model_config = {"from_attributes": True}` where needed. |
| `tests/jobs/test_upload.py` | Upload endpoint integration tests (FILE-01, FILE-02) | VERIFIED | 11 tests covering valid upload, job_id response, file storage, JobRow creation, csv rejection, txt rejection, empty file rejection, auth requirement, byte-for-byte preservation, ownership isolation. |
| `tests/jobs/test_detection.py` | Column detection unit tests (FILE-03) | VERIFIED | 18 tests covering all 8 header types, content-only detection for email/linkedin/phone, HIGH/MEDIUM/UNKNOWN confidence levels, edge cases (empty headers, empty rows, normalization), contact identifier set. |
| `tests/jobs/test_mappings.py` | Mapping override integration tests (FILE-04) | VERIFIED | 10 tests covering auto-detect, all-columns return, caching, single/multiple override, preservation of unspecified columns, invalid type rejection (422), multiple overrides, wrong user (404), wrong status (409). |
| `tests/jobs/test_confirm.py` | Confirm flow and malformed row tests (FILE-05) | VERIFIED | 11 tests covering status transition, malformed row flagging, error message content, valid rows staying PENDING, partial rows (company-only) not flagged, row count updates, requires-mappings guard, double-confirm (409), wrong user (404), end-to-end flow. |
| `alembic/versions/d0e48f167723_add_jobs_and_job_rows_tables.py` | Migration for jobs and job_rows tables | VERIFIED | Creates `jobs` and `job_rows` tables with all required columns. FKs to `users.id` and `contacts.id`. Index on `job_rows.job_id`. `down_revision = None` is correct — this is the first and only Alembic migration in the project (Phase 1 tables were not migrated via Alembic). |

### Key Link Verification

| From | To | Via | Status | Details |
|------|----|-----|--------|---------|
| `app/jobs/models.py` | `app/auth/models.py` | `ForeignKey("users.id")` on `Job.user_id` | VERIFIED | Line 36: `ForeignKey("users.id")` present |
| `app/jobs/models.py` | `app/contacts/models.py` | `ForeignKey("contacts.id")` on `JobRow.contact_id` | VERIFIED | Line 62: `ForeignKey("contacts.id")` present |
| `app/main.py` | `app/jobs/routes.py` | `include_router` at `/api/v1/jobs` | VERIFIED | Lines 33-35: `from app.jobs.routes import router as jobs_router; app.include_router(jobs_router, prefix="/api/v1/jobs", tags=["jobs"])` |
| `app/models/__init__.py` | `app/jobs/models.py` | Model registration for Alembic | VERIFIED | Line 9: `import app.jobs.models as _jobs_models  # noqa: F401, E402` |
| `app/jobs/routes.py` | `app/jobs/detection.py` | `detect_column_types` called during mapping retrieval | VERIFIED | `service.py` imports `detect_column_types` from `detection.py`; `get_column_mappings` calls it; route calls `get_column_mappings`. |
| `app/jobs/routes.py` | `app/jobs/service.py` | `confirm_job` flags malformed rows | VERIFIED | Route imports and calls `confirm_job(db, job_id, user.id)` directly. |
| `tests/conftest.py` | `app/jobs/models.py` | Job/JobRow fixtures | VERIFIED | Line 19: `from app.jobs.models import Job, JobRow  # noqa: F401` |

### Data-Flow Trace (Level 4)

| Artifact | Data Variable | Source | Produces Real Data | Status |
|----------|---------------|--------|--------------------|--------|
| `app/jobs/routes.py` upload endpoint | `job` | `create_job_from_upload(db, user.id, file)` — reads uploaded bytes, saves to disk, parses with openpyxl, creates `Job` and `JobRow` DB records | Yes — openpyxl parses real xlsx content into `JobRow.raw_data` JSONB | FLOWING |
| `app/jobs/routes.py` mappings GET endpoint | `mappings` | `get_column_mappings(db, job_id, user.id)` — queries `JobRow` records from DB, extracts `raw_data.keys()` as headers, calls `detect_column_types()` on real row dicts | Yes — real DB rows fed to detection engine | FLOWING |
| `app/jobs/routes.py` confirm endpoint | `job` | `confirm_job(db, job_id, user.id)` — queries all `JobRow` records, checks `raw_data` against `identifier_columns`, updates `row.status` and `row.error_message` in DB | Yes — real row data checked, DB records mutated | FLOWING |

### Behavioral Spot-Checks

Step 7b: SKIPPED — tests require a live PostgreSQL database; no runnable API without Docker. Human verification covers this in the section above.

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
|-------------|------------|-------------|--------|----------|
| FILE-01 | 02-01-PLAN.md, 02-03-PLAN.md | User can upload Excel files (.xlsx) via REST API | SATISFIED | POST /upload endpoint exists, accepts UploadFile, returns job_id with PENDING_CONFIRMATION status. Integration tests in `test_upload.py` cover valid upload, response schema, file storage, JobRow creation. |
| FILE-02 | 02-01-PLAN.md, 02-03-PLAN.md | System validates file (format, size, structure) and rejects with clear errors | SATISFIED | `validate_upload` (extension check), `check_file_size` (413 for >10MB), `parse_excel_file` (400 for header-only). Tests cover csv rejection, txt rejection, empty file rejection. |
| FILE-03 | 02-02-PLAN.md, 02-03-PLAN.md | System auto-detects column types from headers and content sampling | SATISFIED | `detection.py` implements two-pass strategy for 8 column types. GET /mappings returns detected types with HIGH/MEDIUM/UNKNOWN confidence. 18 unit tests verify detection logic. |
| FILE-04 | 02-02-PLAN.md, 02-03-PLAN.md | User can review and override column mappings before enrichment starts | SATISFIED | PUT /{job_id}/mappings merges overrides, validates against COLUMN_TYPES whitelist, supports multiple overrides. 10 integration tests verify override flow. |
| FILE-05 | 02-01-PLAN.md, 02-02-PLAN.md, 02-03-PLAN.md | System handles malformed rows gracefully without failing the job | SATISFIED | `confirm_job` flags rows with no contact identifiers as ERROR with descriptive message. Partially complete rows (company-only) remain PENDING. Job transitions to CONFIRMED regardless. 11 confirm tests verify flagging behavior. |

**Note on ENRICH-01 overlap:** REQUIREMENTS.md assigns ENRICH-01 ("unique UUID to each row at parse time") to Phase 3. Phase 2 delivers this ahead of schedule — `JobRow` inherits `UUIDMixin` (UUID PK) and rows are UUID-tagged at upload time in Plan 02-01. This is not a gap; it is early delivery. Phase 3 should not re-implement UUID assignment.

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
|------|------|---------|----------|--------|
| `app/jobs/service.py` | 214 | `get_job_by_id` does not filter by `user_id` in the SQL WHERE clause — it loads by `job_id` only, then checks `job.user_id != user_id` in Python | Info | Functionally correct but slightly less efficient than a DB-level filter. Not a security issue — 404 is returned for wrong user. No impact on goal achievement. |
| `app/jobs/service.py` | 182 | `_headers` variable from `parse_excel_file` is unused (prefixed with `_`) | Info | Headers are re-derived from `raw_data.keys()` in `get_column_mappings`. Column order is preserved since dict insertion order is guaranteed in Python 3.7+. No functional gap. |

No blockers or stub patterns found. All `return` statements return substantive data. No `TODO`/`FIXME`/placeholder comments in implementation files.

### Human Verification Required

#### 1. Full Test Suite Execution

**Test:** Inside the Docker stack, run `docker compose exec api pytest tests/jobs/ -v`
**Expected:** All 50 tests pass — 11 upload tests, 18 detection tests, 10 mapping tests, 11 confirm tests. No failures.
**Why human:** Tests require a live PostgreSQL database (JSONB, UUID types, real FK constraints). SQLite is forbidden per CLAUDE.md. Cannot execute without Docker.

#### 2. End-to-End API Flow

**Test:** With the Docker stack running, perform the full flow:
1. `POST /api/v1/jobs/upload` with a valid `.xlsx` file (authenticated)
2. `GET /api/v1/jobs/{job_id}/mappings`
3. `PUT /api/v1/jobs/{job_id}/mappings` to override one column
4. `POST /api/v1/jobs/{job_id}/confirm`
5. `GET /api/v1/jobs/{job_id}` to verify final state

**Expected:** Step 1 returns 201 with `status=pending_confirmation`. Step 2 returns mappings with confidence levels. Step 3 returns updated mapping with `confidence=HIGH`. Step 4 returns `status=confirmed` and updated row counts. Step 5 confirms `status=confirmed`.
**Why human:** Requires a running Docker stack with API + PostgreSQL + Redis.

#### 3. Validation Error Responses

**Test:** Upload (a) a `.csv` file, (b) a file >10MB, (c) a header-only `.xlsx`
**Expected:** (a) 400 with message containing "xlsx". (b) 413 with size limit message. (c) 400 with "no data rows" message.
**Why human:** Requires a running API server.

### Gaps Summary

No gaps found. All 5 roadmap success criteria are met by substantive, wired implementations. The three human verification items are operational tests (run test suite, call live API) — the code logic supporting them is verified.

---

_Verified: 2026-04-06T16:00:00Z_
_Verifier: Claude (gsd-verifier)_
