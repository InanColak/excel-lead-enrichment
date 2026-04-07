# Phase 4: Job Output and History - Research

**Researched:** 2026-04-07
**Domain:** Excel output generation, file download API, job listing/pagination, usage stats aggregation
**Confidence:** HIGH

## Summary

Phase 4 closes the enrichment loop by delivering four capabilities: (1) enriched Excel file generation from DB results + original file, (2) file download endpoint, (3) paginated job history listing, and (4) usage stats aggregation. All four are well-understood patterns in the FastAPI + SQLAlchemy + openpyxl stack already established in this project.

The primary complexity is in the Excel output generation -- reading the original file with openpyxl `read_only=True`, joining enrichment results from JobRow + Contact by row UUID, and writing the output file with three appended columns. This must happen inside the Celery task (not on download request) per D-64. The remaining work (job listing, stats, download) is straightforward FastAPI endpoint work with SQL queries.

**Primary recommendation:** Build output file generation as a pure async function in `app/output/service.py` (or `app/jobs/output.py`), called from the Celery task at job finalization. Extend existing jobs router with list, download, and stats endpoints. Use `FileResponse` for downloads. Use SQL `func.sum`/`func.count` for stats aggregation.

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions
- **D-54:** Append three columns after all original columns: `enriched_email`, `enriched_phone`, `enrichment_status`. Original columns preserved exactly.
- **D-55:** Row status mapping: webhook timeout = blank phone + "email_only"; fully enriched = "enriched"; not found = "not_found"; errors = "error".
- **D-56:** Generate output using openpyxl (not pandas). Read original with `read_only=True`, write enriched file with results from DB joined by row UUID. Store path on Job model.
- **D-57:** Output file stored alongside original upload, named `{original_filename}_enriched.xlsx`. Job model gets `output_file_path` field.
- **D-58:** Extend existing `GET /api/v1/jobs/{job_id}` -- expand JobResponse schema with Phase 3 metrics. No new endpoint needed.
- **D-59:** Add computed `progress_percent` field: `(processed_rows / total_rows * 100)` when PROCESSING or AWAITING_WEBHOOKS. Null otherwise.
- **D-60:** `GET /api/v1/jobs` -- offset-based pagination with `limit`, `offset`, `status`, `created_after`, `created_before` params. Sorted by `created_at` descending.
- **D-61:** Response includes total count + list of JobResponse objects. Users only see their own jobs.
- **D-62:** `GET /api/v1/stats` -- aggregates across user's jobs. Optional `since`/`until` params. Returns totals and breakdowns.
- **D-63:** Stats via SQL aggregation (SUM, COUNT). No materialized views for v1.
- **D-64:** Output file generated at end of enrichment pipeline (Celery task), not on download.
- **D-65:** Re-download serves pre-generated file. No regeneration.

### Claude's Discretion
- Exact SQL query structure for stats aggregation
- Pagination response envelope structure (items + total vs. next_cursor)
- Error handling for download of incomplete/failed jobs
- openpyxl styling (bold headers, column widths) for output file

### Deferred Ideas (OUT OF SCOPE)
None -- discussion stayed within phase scope
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| OUTPUT-01 | User can download enriched Excel file with original columns plus email, phone, and status columns appended; rows that timed out show blank phone | openpyxl write patterns, FileResponse download, D-54/D-55/D-56/D-57 |
| OUTPUT-02 | User can query real-time job status and progress via API endpoint | Extend existing JobResponse schema per D-58/D-59 |
| OUTPUT-03 | User can list job history and re-download results from any past job | Pagination patterns per D-60/D-61, FileResponse per D-65 |
| AUTH-04 | User can query usage stats via API (credits used, cache hit rate, jobs run) | SQL aggregation patterns per D-62/D-63 |
</phase_requirements>

## Project Constraints (from CLAUDE.md)

- openpyxl for Excel read/write (not pandas for row-level work)
- FastAPI with async endpoints, Pydantic v2 schemas with `from_attributes`
- SQLAlchemy 2.x async (asyncpg dialect) -- no legacy 1.x patterns
- Celery for background processing -- output generation runs in Celery task
- `httpx` for any HTTP client needs (not relevant for this phase)
- All new endpoints behind JWT auth via `Depends(get_current_user)`
- Tests with pytest-asyncio in auto mode, run inside Docker

## Standard Stack

### Core (Already Installed)
| Library | Version | Purpose | Verified |
|---------|---------|---------|----------|
| openpyxl | 3.1.5 | Excel output file generation | [VERIFIED: pyproject.toml] |
| FastAPI | >=0.115,<1.0 | API endpoints (download, list, stats) | [VERIFIED: pyproject.toml] |
| SQLAlchemy | 2.0.49 | Async queries for stats aggregation | [VERIFIED: pyproject.toml] |
| Alembic | 1.18.4 | Migration for `output_file_path` column | [VERIFIED: pyproject.toml] |

### No New Dependencies Required
This phase uses only libraries already in the project. `FileResponse` is built into FastAPI (from `starlette.responses`). openpyxl is installed. SQL aggregation uses SQLAlchemy `func`. No new packages needed.

## Architecture Patterns

### Recommended Module Structure
```
app/
  jobs/
    routes.py        # EXTEND: add list, download endpoints
    schemas.py       # EXTEND: add metrics to JobResponse, add pagination models, stats models
    service.py       # EXTEND: add list_jobs, get_job_stats service functions
    output.py        # NEW: Excel output generation logic
  main.py            # EXTEND: mount stats route (or add to existing jobs router)
  enrichment/
    tasks.py         # MODIFY: call output generation after job finalization
    service.py       # MODIFY: call output generation when status is COMPLETE/PARTIAL (all cache hits path)
tests/
  jobs/
    test_output.py   # NEW: output generation tests
    test_list.py     # NEW: job listing/pagination tests
    test_download.py # NEW: download endpoint tests
    test_stats.py    # NEW: stats endpoint tests
alembic/
  versions/
    004_add_output_file_path.py  # NEW: migration
```

### Pattern 1: Excel Output Generation (in Celery task context)
**What:** Read original .xlsx, join enrichment results from DB, write new file with appended columns
**When to use:** Called after job transitions to COMPLETE or PARTIAL
**Key insight:** This runs inside Celery (not FastAPI), so it uses the session_factory pattern, not `get_db`.

```python
# Source: openpyxl docs + project patterns [VERIFIED: codebase inspection]
from openpyxl import load_workbook, Workbook
from pathlib import Path

async def generate_output_file(
    job_id: uuid.UUID,
    session_factory: async_sessionmaker
) -> str:
    """Generate enriched Excel output file.

    Per D-56: read original with read_only=True, write enriched with results.
    Per D-54: append enriched_email, enriched_phone, enrichment_status columns.
    Per D-57: save as {original_filename}_enriched.xlsx alongside original.

    Returns the output file path.
    """
    async with session_factory() as db:
        # Load job
        job = ...  # select Job where id == job_id

        # Load all rows with their contacts (join or separate query)
        rows = ...  # select JobRow where job_id, order by row_index

        # Build row_index -> enrichment data map
        enrichment_map = {}
        for row in rows:
            contact = None
            if row.contact_id:
                contact = ...  # load contact
            enrichment_map[row.row_index] = {
                "email": contact.email if contact else None,
                "phone": contact.phone if contact else None,
                "status": _map_row_status(row.status),
            }

        # Read original file
        original_path = job.file_path  # e.g., /data/uploads/{job_id}/original.xlsx
        wb_read = load_workbook(original_path, read_only=True, data_only=True)
        ws_read = wb_read.active

        # Create output workbook
        wb_write = Workbook()
        ws_write = wb_write.active

        # Copy header row + append new column headers
        # Copy data rows + append enrichment data
        # Save to output path

        output_path = _build_output_path(job.filename, job.id)
        wb_write.save(output_path)

        # Update job record
        job.output_file_path = str(output_path)
        await db.commit()

        return str(output_path)
```

### Pattern 2: FileResponse for Download
**What:** Serve pre-generated Excel file via FastAPI
**When to use:** `GET /api/v1/jobs/{job_id}/download`

```python
# Source: FastAPI official docs [CITED: fastapi.tiangolo.com/advanced/custom-response/]
from fastapi.responses import FileResponse

@router.get("/{job_id}/download")
async def download_enriched_file(
    job_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    job = await get_job_by_id(db, job_id, user.id)
    if not job.output_file_path:
        raise HTTPException(status_code=404, detail="Output file not available")

    return FileResponse(
        path=job.output_file_path,
        filename=f"{Path(job.filename).stem}_enriched.xlsx",
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
```

### Pattern 3: Offset-Based Pagination
**What:** List jobs with offset/limit pagination per D-60
**When to use:** `GET /api/v1/jobs`

```python
# Source: SQLAlchemy 2.x docs + project patterns [VERIFIED: codebase]
from sqlalchemy import func, select

async def list_jobs(
    db: AsyncSession,
    user_id: uuid.UUID,
    limit: int = 20,
    offset: int = 0,
    status: str | None = None,
    created_after: datetime | None = None,
    created_before: datetime | None = None,
) -> tuple[list[Job], int]:
    """Return (jobs, total_count) for pagination."""
    query = select(Job).where(Job.user_id == user_id)
    count_query = select(func.count()).select_from(Job).where(Job.user_id == user_id)

    if status:
        query = query.where(Job.status == status)
        count_query = count_query.where(Job.status == status)
    if created_after:
        query = query.where(Job.created_at >= created_after)
        count_query = count_query.where(Job.created_at >= created_after)
    if created_before:
        query = query.where(Job.created_at <= created_before)
        count_query = count_query.where(Job.created_at <= created_before)

    total = (await db.execute(count_query)).scalar()
    jobs = (await db.execute(
        query.order_by(Job.created_at.desc()).offset(offset).limit(limit)
    )).scalars().all()

    return jobs, total
```

### Pattern 4: SQL Aggregation for Stats
**What:** Aggregate job metrics across user's jobs
**When to use:** `GET /api/v1/stats`

```python
# Source: SQLAlchemy 2.x docs [ASSUMED]
from sqlalchemy import func, select, case

async def get_user_stats(
    db: AsyncSession,
    user_id: uuid.UUID,
    since: datetime | None = None,
    until: datetime | None = None,
) -> dict:
    query = select(
        func.count(Job.id).label("total_jobs"),
        func.coalesce(func.sum(Job.api_calls), 0).label("total_api_calls"),
        func.coalesce(func.sum(Job.cache_hits), 0).label("total_cache_hits"),
        func.coalesce(func.sum(Job.webhook_callbacks_received), 0).label("total_webhook_callbacks"),
        func.coalesce(func.sum(Job.webhook_timeouts), 0).label("total_webhook_timeouts"),
    ).where(Job.user_id == user_id)

    if since:
        query = query.where(Job.created_at >= since)
    if until:
        query = query.where(Job.created_at <= until)

    result = await db.execute(query)
    row = result.one()

    # Compute cache_hit_rate
    total_lookups = row.total_api_calls + row.total_cache_hits
    cache_hit_rate = (row.total_cache_hits / total_lookups * 100) if total_lookups > 0 else 0.0

    # Jobs by status breakdown (separate query)
    status_query = select(
        Job.status, func.count(Job.id)
    ).where(Job.user_id == user_id).group_by(Job.status)
    # ... apply date filters ...

    return {
        "total_jobs": row.total_jobs,
        "total_api_calls": row.total_api_calls,
        "total_cache_hits": row.total_cache_hits,
        "cache_hit_rate_percent": round(cache_hit_rate, 1),
        "total_webhook_callbacks": row.total_webhook_callbacks,
        "total_webhook_timeouts": row.total_webhook_timeouts,
        "jobs_by_status": status_breakdown,
    }
```

### Anti-Patterns to Avoid
- **Loading entire Contact table for output generation:** Query only contacts referenced by job rows. Use a JOIN or collect contact_ids from rows and batch-fetch.
- **Generating output on download request:** Per D-64, generate in Celery task. Download endpoint just serves the file.
- **Using pandas to write output Excel:** Per CLAUDE.md, use openpyxl for row-level work. Pandas loads everything into memory.
- **N+1 queries in stats:** Use SQL aggregation, not Python-side loops over individual jobs.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| File download streaming | Custom byte streaming | `FileResponse` from `starlette.responses` | Handles headers, Content-Disposition, async streaming automatically [CITED: fastapi.tiangolo.com/advanced/custom-response/] |
| Pagination envelope | Custom dict construction | Pydantic `PaginatedResponse` model | Type safety, OpenAPI docs generation |
| Excel column width auto-fit | Manual character counting | openpyxl `worksheet.column_dimensions[col].width = N` with a simple max-length heuristic | Good enough for internal tool |

## Common Pitfalls

### Pitfall 1: openpyxl read_only workbook cannot be written to
**What goes wrong:** Trying to modify cells in a workbook opened with `read_only=True` raises an error.
**Why it happens:** read_only mode creates a read-only worksheet that doesn't support cell assignment.
**How to avoid:** Open original file with `read_only=True` for reading, create a NEW `Workbook()` for writing. Copy data row by row.
**Warning signs:** `AttributeError` or `TypeError` when assigning cell values.
[VERIFIED: openpyxl docs pattern]

### Pitfall 2: Row index off-by-one between original file and JobRow.row_index
**What goes wrong:** Enrichment data mapped to wrong rows in the output file.
**Why it happens:** `JobRow.row_index` is 0-based (from `enumerate(data_rows)`), but openpyxl rows are 1-based, and the header row occupies row 1. So JobRow index 0 = openpyxl row 2.
**How to avoid:** When writing output, iterate the original file rows (skipping header), maintain a counter starting at 0 that maps to `JobRow.row_index`. Or read original rows into a list indexed by position.
**Warning signs:** First or last row has wrong enrichment data.
[VERIFIED: codebase inspection of service.py line 186]

### Pitfall 3: File path handling between Docker and host
**What goes wrong:** `output_file_path` stored in DB is a Docker container path (e.g., `/data/uploads/...`) that may not match the host filesystem.
**Why it happens:** The app runs inside Docker where `upload_dir=/data/uploads`. FileResponse needs the container-internal path.
**How to avoid:** Since both the Celery worker and the API server mount the same Docker volume at `/data/uploads`, the path is consistent. Just use the stored path as-is. Do NOT try to resolve to host paths.
**Warning signs:** FileNotFoundError on download.
[VERIFIED: config.py shows upload_dir="/data/uploads"]

### Pitfall 4: Forgetting to call output generation on the all-cache-hits path
**What goes wrong:** Jobs where all contacts were in the local DB (zero API calls) skip the webhook checker and go directly to COMPLETE, but output file never gets generated.
**Why it happens:** Output generation is only added to the webhook completion checker, not to the direct COMPLETE path in `process_job`.
**How to avoid:** Call `generate_output_file` in BOTH paths: (1) at the end of `_check_webhook_completion_async` after setting final status, and (2) at the end of `process_job` when status is set to COMPLETE/PARTIAL/FAILED without going through AWAITING_WEBHOOKS.
**Warning signs:** Jobs with 100% cache hit rate have no downloadable output.
[VERIFIED: enrichment/service.py lines 312-333 show the direct-to-COMPLETE path]

### Pitfall 5: Stats endpoint returning incorrect cache_hit_rate for zero-job users
**What goes wrong:** Division by zero when computing `cache_hits / (cache_hits + api_calls)` for users with no completed jobs.
**Why it happens:** SUM returns 0 for both fields when there are no matching rows.
**How to avoid:** Check `total_lookups > 0` before dividing. Return 0.0 for empty result sets.
**Warning signs:** HTTP 500 on stats endpoint for new users.
[ASSUMED]

### Pitfall 6: Missing Alembic migration for output_file_path
**What goes wrong:** `output_file_path` attribute works in tests (which recreate tables) but fails in deployed Docker (which uses Alembic migrations).
**Why it happens:** Adding a field to the model without a migration means the column doesn't exist in production.
**How to avoid:** Always create an Alembic migration for new model fields. This field should be `String(1000), nullable=True` (null for jobs not yet complete).
**Warning signs:** `UndefinedColumn` PostgreSQL error on deployed instance.
[VERIFIED: existing migration pattern in alembic/versions/]

## Code Examples

### Mapping row status to output status string (D-55)
```python
# Source: D-55 from CONTEXT.md [VERIFIED]
def map_enrichment_status(row_status: str, contact: Contact | None) -> str:
    """Map JobRow status to the enrichment_status column value for Excel output."""
    if row_status == "enriched" and contact and contact.phone:
        return "enriched"
    elif row_status == "enriched" or row_status == "email_only":
        return "email_only"
    elif row_status == "not_found":
        return "not_found"
    elif row_status in ("error", "skipped"):
        return "error"
    else:
        return "pending"  # Shouldn't appear in output, but safe fallback
```

### Pagination response schema
```python
# Source: FastAPI + Pydantic patterns [ASSUMED]
class PaginatedJobsResponse(BaseModel):
    items: list[JobResponse]
    total: int
    limit: int
    offset: int
```

### Extended JobResponse with metrics (D-58/D-59)
```python
# Source: D-58/D-59 from CONTEXT.md + existing schemas [VERIFIED: codebase]
class JobResponse(BaseModel):
    id: uuid.UUID
    filename: str
    status: str
    total_rows: int
    valid_rows: int
    error_rows: int
    processed_rows: int  # NEW
    cache_hits: int  # NEW
    api_calls: int  # NEW
    webhook_callbacks_received: int  # NEW
    webhook_timeouts: int  # NEW
    progress_percent: float | None = None  # NEW - computed
    column_mappings: dict | None = None
    output_file_path: str | None = None  # NEW - for knowing if download is available
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}

    @model_validator(mode="after")
    def compute_progress(self) -> "JobResponse":
        if self.status in ("processing", "awaiting_webhooks") and self.total_rows > 0:
            self.progress_percent = round(self.processed_rows / self.total_rows * 100, 1)
        return self
```

### Stats response schema (D-62)
```python
# Source: D-62 from CONTEXT.md [VERIFIED]
class UsageStatsResponse(BaseModel):
    total_jobs: int
    total_api_calls: int
    total_cache_hits: int
    cache_hit_rate_percent: float
    total_webhook_callbacks: int
    total_webhook_timeouts: int
    jobs_by_status: dict[str, int]
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| `starlette.responses.FileResponse` import | `fastapi.responses.FileResponse` (re-export) | FastAPI 0.95+ | Either works; use `fastapi.responses` for consistency |
| Pydantic v1 `@validator` | Pydantic v2 `@model_validator` | Pydantic 2.0 (2023) | Project already uses v2; use `@model_validator(mode="after")` for computed fields |

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | `func.coalesce` works with SQLAlchemy 2.x async for aggregation queries | Architecture Patterns / Pattern 4 | LOW -- standard SQLAlchemy; would surface in tests |
| A2 | Pydantic `@model_validator(mode="after")` is the correct v2 way to compute `progress_percent` | Code Examples | LOW -- could also use `@computed_field` or `@field_validator`; all work |
| A3 | Division-by-zero risk in stats for zero-job users | Pitfalls / Pitfall 5 | LOW -- straightforward Python guard |

## Open Questions

1. **Should output_file_path be exposed in JobResponse?**
   - What we know: D-65 says re-download serves pre-generated file. Client needs to know if download is available.
   - What's unclear: Should we expose the full path or just a boolean `has_output`?
   - Recommendation: Expose a boolean `has_output: bool` computed from `output_file_path is not None`. Don't expose server filesystem paths to the API client.

2. **Error handling for download of FAILED jobs?**
   - What we know: D-64 says output generated when job transitions to COMPLETE or PARTIAL. FAILED jobs have no output file.
   - What's unclear: CONTEXT.md lists this as Claude's discretion.
   - Recommendation: Return 404 with message "Output file not available. Job status: {status}" for jobs without output.

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest 8.x + pytest-asyncio 1.3.0 |
| Config file | `pyproject.toml` ([tool.pytest.ini_options] asyncio_mode = "auto") |
| Quick run command | `docker compose exec api pytest tests/jobs/ -x -q` |
| Full suite command | `docker compose exec api pytest tests/ -v` |

### Phase Requirements to Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| OUTPUT-01 | Generate enriched Excel with 3 appended columns, correct status values, blank phone for timeouts | unit | `docker compose exec api pytest tests/jobs/test_output.py -x` | No -- Wave 0 |
| OUTPUT-02 | Extended JobResponse includes metrics + progress_percent | unit | `docker compose exec api pytest tests/jobs/test_status.py -x` | No -- Wave 0 |
| OUTPUT-03 | Job listing with pagination, re-download from past jobs | integration | `docker compose exec api pytest tests/jobs/test_list.py tests/jobs/test_download.py -x` | No -- Wave 0 |
| AUTH-04 | Stats endpoint returns correct aggregations, cache hit rate, date filtering | integration | `docker compose exec api pytest tests/jobs/test_stats.py -x` | No -- Wave 0 |

### Sampling Rate
- **Per task commit:** `docker compose exec api pytest tests/jobs/ -x -q`
- **Per wave merge:** `docker compose exec api pytest tests/ -v`
- **Phase gate:** Full suite green before `/gsd-verify-work`

### Wave 0 Gaps
- [ ] `tests/jobs/test_output.py` -- covers OUTPUT-01 (Excel generation logic)
- [ ] `tests/jobs/test_list.py` -- covers OUTPUT-03 (pagination, filtering)
- [ ] `tests/jobs/test_download.py` -- covers OUTPUT-01/OUTPUT-03 (FileResponse endpoint)
- [ ] `tests/jobs/test_stats.py` -- covers AUTH-04 (aggregation, date filtering)
- [ ] Test fixtures: completed Job with JobRows + Contacts for output generation testing

## Security Domain

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | yes | JWT via `Depends(get_current_user)` -- already established |
| V3 Session Management | no | Stateless JWT -- no session state |
| V4 Access Control | yes | Users see only their own jobs (`Job.user_id == user.id`) |
| V5 Input Validation | yes | Pydantic models validate query params (limit, offset, dates) |
| V6 Cryptography | no | No crypto operations in this phase |

### Known Threat Patterns

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| IDOR on job download (accessing another user's file) | Information Disclosure | `get_job_by_id` already verifies `user_id` ownership [VERIFIED: service.py line 217] |
| Path traversal via output_file_path | Tampering | Path is server-generated, never from user input. Do not expose raw path in API response. |
| Pagination abuse (limit=999999) | Denial of Service | Cap `limit` with `Query(le=100)` per D-60 |

## Sources

### Primary (HIGH confidence)
- Codebase inspection: `app/jobs/models.py`, `app/jobs/schemas.py`, `app/jobs/routes.py`, `app/jobs/service.py`, `app/enrichment/tasks.py`, `app/enrichment/service.py`, `app/contacts/models.py` -- current model structure, route patterns, task lifecycle
- `pyproject.toml` -- verified all dependency versions
- Phase 3 CONTEXT.md (D-38 through D-53) -- enrichment lifecycle that feeds into output generation
- Phase 4 CONTEXT.md (D-54 through D-65) -- all locked implementation decisions

### Secondary (MEDIUM confidence)
- [FastAPI FileResponse docs](https://fastapi.tiangolo.com/advanced/custom-response/) -- verified FileResponse usage pattern
- [openpyxl documentation](https://openpyxl.readthedocs.io/en/stable/) -- read_only mode, Workbook creation patterns

### Tertiary (LOW confidence)
- None -- all findings verified against codebase or official docs

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH -- all libraries already installed and in use
- Architecture: HIGH -- extends established project patterns (routes, service, schemas)
- Pitfalls: HIGH -- derived from codebase inspection of actual code paths
- Output generation: HIGH -- openpyxl patterns well-documented, row mapping verified against actual JobRow model

**Research date:** 2026-04-07
**Valid until:** 2026-05-07 (stable -- no fast-moving dependencies)
