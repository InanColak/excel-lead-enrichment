# Phase 4: Job Output and History - Context

**Gathered:** 2026-04-07
**Status:** Ready for planning

<domain>
## Phase Boundary

Deliver the user-facing endpoints that close the enrichment loop: job status polling with real-time progress, enriched Excel file download, job history listing with pagination, and usage stats aggregation. All endpoints are REST API (no frontend — Swagger UI for now, per project decision). This phase consumes the enrichment results from Phase 3 and the job/row data from Phase 2.

</domain>

<decisions>
## Implementation Decisions

### Excel Output Generation
- **D-54:** Append three columns after all original columns: `enriched_email`, `enriched_phone`, `enrichment_status`. Original columns are preserved exactly as uploaded.
- **D-55:** Rows where webhook timed out show blank phone cell and `enrichment_status` = "email_only". Rows fully enriched show "enriched". Rows Apollo couldn't find show "not_found". Rows with errors show "error". This matches OUTPUT-01 requirement.
- **D-56:** Generate output file using openpyxl (not pandas). Read original file with `read_only=True`, write enriched file with results from DB joined by row UUID. Store generated file path on Job model for re-download.
- **D-57:** Output file stored alongside original upload in the uploads directory, named `{original_filename}_enriched.xlsx`. Job model gets an `output_file_path` field.

### Job Status Polling
- **D-58:** `GET /api/v1/jobs/{job_id}` already exists — extend JobResponse schema to include all Phase 3 metrics: `processed_rows`, `cache_hits`, `api_calls`, `webhook_callbacks_received`, `webhook_timeouts`. No new endpoint needed, just schema expansion.
- **D-59:** Add computed `progress_percent` field to response: `(processed_rows / total_rows * 100)` when status is PROCESSING or AWAITING_WEBHOOKS. Null otherwise.

### Job History
- **D-60:** `GET /api/v1/jobs` — list endpoint with offset-based pagination. Query params: `limit` (default 20, max 100), `offset` (default 0), `status` (optional filter), `created_after` / `created_before` (optional date range). Sorted by `created_at` descending.
- **D-61:** Response includes total count for pagination UI and list of JobResponse objects. Users only see their own jobs (filtered by user_id from JWT).

### Usage Stats
- **D-62:** `GET /api/v1/stats` — aggregates across all jobs for the requesting user. Optional `since` and `until` date range params. Returns: total_jobs, total_api_calls, total_cache_hits, cache_hit_rate_percent, total_webhook_callbacks, total_webhook_timeouts, jobs_by_status breakdown (dict of status → count).
- **D-63:** Stats computed via SQL aggregation queries (SUM, COUNT) on the jobs table filtered by user_id. No materialized views or caching for v1 — query volume is low for an internal tool.

### Output File Lifecycle
- **D-64:** Output file generated at the end of the enrichment pipeline (when job transitions to COMPLETE or PARTIAL). The generation happens in the Celery task, not on download request. Download endpoint serves the pre-generated file.
- **D-65:** Re-download serves the same pre-generated file. No regeneration on each download.

### Claude's Discretion
- Exact SQL query structure for stats aggregation
- Pagination response envelope structure (items + total vs. next_cursor)
- Error handling for download of incomplete/failed jobs
- openpyxl styling (bold headers, column widths) for output file

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Project Definition
- `.planning/PROJECT.md` — Core value, constraints, key decisions (API-only, no frontend)
- `.planning/REQUIREMENTS.md` — OUTPUT-01, OUTPUT-02, OUTPUT-03, AUTH-04 requirement definitions
- `.planning/ROADMAP.md` — Phase 4 goal, success criteria, dependency chain

### Technology Stack
- `CLAUDE.md` §Technology Stack — openpyxl for Excel output, FastAPI for endpoints, SQLAlchemy for queries

### Prior Phase Context
- `.planning/phases/03-enrichment-pipeline/03-CONTEXT.md` — Enrichment decisions (webhook timeout, status values, metrics fields) that affect output format
- `app/jobs/models.py` — Job and JobRow models with all metrics fields
- `app/jobs/schemas.py` — Existing Pydantic schemas to extend
- `app/jobs/routes.py` — Existing job routes to extend
- `app/enrichment/service.py` — Where output file generation should be triggered

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `app/jobs/routes.py`: Existing `GET /jobs/{job_id}` endpoint — extend, don't recreate
- `app/jobs/schemas.py`: `JobResponse` schema — add metrics fields and progress_percent
- `app/jobs/service.py`: Job query functions with user_id filtering
- `app/deps.py`: `get_current_user` and `get_db` dependencies
- `app/config.py`: `upload_dir` setting for file storage path

### Established Patterns
- Router pattern: `APIRouter(tags=[...])` mounted in `app/main.py`
- Service pattern: async service functions called from routes, injected with `db: AsyncSession`
- Schema pattern: Pydantic `BaseModel` with `model_config = {"from_attributes": True}`
- Auth: JWT via `Depends(get_current_user)` on all user-facing endpoints

### Integration Points
- `app/enrichment/service.py` or `app/enrichment/tasks.py`: trigger output file generation after job completes
- `app/main.py`: mount new routes (stats, potentially download)
- `app/jobs/routes.py`: add list and download endpoints to existing jobs router

</code_context>

<specifics>
## Specific Ideas

No specific requirements — open to standard approaches

</specifics>

<deferred>
## Deferred Ideas

None — discussion stayed within phase scope

</deferred>

---

*Phase: 04-job-output-and-history*
*Context gathered: 2026-04-07*
