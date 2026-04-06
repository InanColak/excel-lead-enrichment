# Phase 3: Enrichment Pipeline - Context

**Gathered:** 2026-04-06
**Status:** Ready for planning

<domain>
## Phase Boundary

Deliver the background enrichment pipeline: when a user confirms a job's column mappings, a Celery task processes all PENDING rows — deduplicating contacts within the upload, checking the local contact database first (saving API credits), calling Apollo's People Enrichment API for unknowns, handling the two-stage response (email immediate, phone via webhook), writing all results keyed by row UUID, tracking per-job metrics, and producing a final job status (COMPLETE, PARTIAL, or FAILED). Includes the webhook receiver endpoint for Apollo phone-data callbacks and a delayed completion checker for webhook timeout handling.

</domain>

<decisions>
## Implementation Decisions

### Apollo API Integration
- **D-38:** Conservative retry strategy: exponential backoff starting at 2s, max 60s, 5 retries per call. Only retries transient errors (429 rate limits, 500 server errors, network timeouts). Successful "not found" responses are NOT retried. Retrying failed network requests does not consume additional Apollo credits.
- **D-39:** No per-job API credit budget cap for v1. Track credits consumed per job in metrics (ENRICH-10) but don't enforce a hard limit. Admin manages credits externally via Apollo dashboard.
- **D-40:** On persistent Apollo failures (after exhausting retries), mark affected rows as NOT_FOUND with error details. Job completes as PARTIAL (some rows enriched, some failed). No infinite retry loops or job pausing.
- **D-41:** Standalone enrichment service module: new `app/enrichment/` with `apollo_client.py` (httpx.AsyncClient + tenacity retry decorators), `service.py` (orchestration logic — dedup, DB lookup, API calls, result writing), and `tasks.py` (Celery task wrappers). Clean separation for testability without Celery.

### Webhook Handling
- **D-42:** Webhook authentication via shared secret in header. Add `APOLLO_WEBHOOK_SECRET` to Settings. Apollo sends the secret in `X-Apollo-Secret` header. Endpoint rejects requests without a matching secret. Returns 200 immediately on valid requests.
- **D-43:** Webhook timeout: 5 minutes. If Apollo's webhook does not deliver phone data within 5 minutes of the API call, the row completes with email only and blank phone. Timeout and absence of phone data recorded in per-job metrics.
- **D-44:** Webhook correlation via Apollo lookup ID. Store the lookup ID from Apollo's API response on the contact record. When webhook arrives, it includes the same ID for 1:1 matching. No ambiguity, no collision risk across concurrent jobs.
- **D-45:** Webhook endpoint at `/api/v1/webhooks/apollo`. Dedicated webhook router under `/api/v1/`. No JWT auth required (uses shared secret instead). Consistent with project's URL prefix pattern.
- **D-46:** Accept late webhooks after timeout. If a webhook arrives after the 5-minute timeout, still update the contact's phone field in the database for future lookups. The original job/row stays marked as complete with email-only status. No credit is wasted — the data was already paid for.

### Deduplication Strategy
- **D-47:** Database-first lookup: email-first, then LinkedIn URL fallback. Primary match on email (already UNIQUE in contacts table). If the row has no email but has a LinkedIn URL, match on that. Name+company is too fuzzy for automated matching — those rows go to Apollo.
- **D-48:** Within-upload deduplication: normalize identifiers (lowercase email, trim whitespace) and group rows by unique contact identity before calling Apollo. One Apollo call per unique contact, results fanned to all matching rows. Saves credits on uploads with duplicates.
- **D-49:** Add partial unique index on `linkedin_url` (WHERE linkedin_url IS NOT NULL) to the Contact model via Alembic migration. Enables LinkedIn-based dedup at the DB level without breaking contacts that lack a LinkedIn URL. Email UNIQUE constraint stays as-is.

### Celery Task Design
- **D-50:** Single orchestrator Celery task per job: `process_enrichment_job(job_id)`. Loads all PENDING rows, deduplicates, performs DB lookups, calls Apollo for unknowns, writes results. One task = one job. Uses async within the task for Apollo API calls.
- **D-51:** Job progress tracked via database row counts. Update Job model fields (`processed_rows`, `cache_hits`, `api_calls`) as rows complete, in batches (every N rows). Frontend polls `GET /jobs/{id}` for status. No extra infrastructure needed.
- **D-52:** Job status logic: PARTIAL if any rows are NOT_FOUND or ERROR but others succeeded. COMPLETE only when all enrichable rows got results (both email and phone or timed out gracefully). FAILED only on catastrophic errors (DB down, unrecoverable). Matches existing JobStatus enum.
- **D-53:** Webhook wait via timer-based check: after all Apollo calls complete, transition job to AWAITING_WEBHOOKS. Schedule a delayed Celery task (5 min) that checks if all webhooks were received. If yes → COMPLETE. If not → mark remaining rows email-only, transition to COMPLETE/PARTIAL.

### Claude's Discretion
- Internal structure of the deduplication grouping logic (hash keys, data structures)
- Exact httpx.AsyncClient configuration (connection pool size, timeouts)
- Celery task configuration (acks_late, reject_on_worker_lost, time_limit)
- Batch size for progress update flushes
- Pydantic schema design for webhook payload validation

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Project Definition
- `.planning/PROJECT.md` — Core value, constraints, key decisions (API-only, no frontend)
- `.planning/REQUIREMENTS.md` — ENRICH-01 through ENRICH-11, JOB-01 requirement definitions
- `.planning/ROADMAP.md` — Phase 3 goal, success criteria, and dependency chain

### Technology Stack
- `CLAUDE.md` §Technology Stack — Full stack spec: httpx for HTTP client, tenacity for retries, Celery + Redis for background jobs, openpyxl for Excel output

### Prior Phase Context
- `.planning/phases/01-foundation/01-CONTEXT.md` — D-01 (JSONB for raw Apollo), D-02 (email UNIQUE), D-04 (UUID PKs), D-09 (module layout), D-15 (health endpoint)
- `.planning/phases/02-file-ingestion/02-CONTEXT.md` — D-18/D-19 (Job/JobRow models), D-24 (confirm flow triggers enrichment), D-31-D-33 (malformed row handling)

### Existing Code Patterns
- `app/models/base.py` — UUIDMixin, TimestampMixin, Base
- `app/contacts/models.py` — Contact model (email UNIQUE, phone, linkedin_url, raw_apollo_response JSONB)
- `app/jobs/models.py` — Job model (status, column_mappings), JobRow model (raw_data, contact_id FK), JobStatus/RowStatus enums
- `app/jobs/service.py` — confirm_job() transitions to CONFIRMED (trigger point for enrichment)
- `app/celery_app.py` — Celery app instance (import for task registration)
- `app/config.py` — Settings class (add Apollo and webhook config here)
- `app/deps.py` — get_db, get_redis, get_current_user dependencies

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `app/celery_app.py`: Celery app instance configured with JSON serialization and Redis broker — import directly for task registration
- `app/contacts/models.py`: Contact model already has all needed fields (email, phone, linkedin_url, raw_apollo_response JSONB) — enrichment writes directly to this model
- `app/jobs/models.py`: JobStatus enum already includes PROCESSING, AWAITING_WEBHOOKS, COMPLETE, PARTIAL, FAILED — no new statuses needed
- `app/jobs/service.py`: confirm_job() is the trigger point — after it sets CONFIRMED, the enrichment task should be dispatched
- `app/deps.py`: get_db, get_redis dependencies reusable in webhook endpoint

### Established Patterns
- Feature module layout: `models.py`, `routes.py`, `schemas.py`, `service.py` — new `app/enrichment/` module follows this
- Router: `APIRouter(tags=[...])` mounted via `app.include_router()` with `/api/v1/` prefix
- Async services accepting `AsyncSession`, returning domain objects
- String(50) for status columns (not SQLAlchemy Enum) — Phase 2 decision, continue this pattern
- pydantic-settings for configuration — add Apollo-specific settings to existing Settings class

### Integration Points
- `confirm_job()` in `app/jobs/service.py` → dispatch Celery task after setting status to CONFIRMED
- JobRow.contact_id FK → populated during enrichment when a contact match is found or created
- Contact model → enrichment writes email/phone/raw_apollo_response, creates new contacts for unknowns
- Job model → needs new fields: `processed_rows`, `cache_hits`, `api_calls` for progress tracking (ENRICH-10)
- Settings → needs: `apollo_api_key` (already exists via admin config), `apollo_api_url`, `apollo_webhook_secret`, `webhook_timeout_seconds`
- Alembic migration → add linkedin_url partial unique index, add Job progress fields

</code_context>

<specifics>
## Specific Ideas

- Apollo credits are consumed at API call time, not webhook delivery time. Retrying failed network requests does not consume extra credits. Conservative backoff is credit-efficient.
- Late webhooks (arriving after the 5-min timeout) should still update the contact's phone field in the database — the data was already paid for, and it enriches the local DB for future lookups.
- The webhook receiver must be a separate router with shared-secret auth (not JWT), since Apollo's server is the caller, not a logged-in user.
- The delayed Celery task for webhook timeout checking creates a clean separation: the main enrichment task handles API calls, the timeout task handles the "did all webhooks arrive?" question.

</specifics>

<deferred>
## Deferred Ideas

None — discussion stayed within phase scope.

</deferred>

---

*Phase: 03-enrichment-pipeline*
*Context gathered: 2026-04-06*
