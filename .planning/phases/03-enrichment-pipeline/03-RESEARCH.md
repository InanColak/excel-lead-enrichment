# Phase 3: Enrichment Pipeline - Research

**Researched:** 2026-04-06
**Domain:** Background job processing, Apollo API integration, webhook handling, contact deduplication
**Confidence:** HIGH

## Summary

Phase 3 implements the core enrichment pipeline: when a job is confirmed, a Celery background task deduplicates contacts, checks the local database, calls Apollo's People Enrichment API for unknowns, receives phone data via webhook, and tracks per-job metrics. The architecture is well-constrained by 16 locked decisions (D-38 through D-53) that define retry strategy, webhook handling, deduplication, and Celery task design.

The Apollo People Enrichment API (`POST https://api.apollo.io/api/v1/people/match`) returns email in the synchronous response and delivers phone numbers asynchronously via webhook when `reveal_phone_number=true` and a `webhook_url` is provided. The webhook payload includes a `request_id` for correlation. Apollo's rate limit is 600 calls/hour for single enrichment. The key technical challenge is bridging Celery's synchronous task model with httpx's async HTTP client (solved via `asyncio.run()` inside the task), and managing the webhook timeout window via a delayed Celery task.

**Primary recommendation:** Build a clean `app/enrichment/` module with three files -- `apollo_client.py` (httpx + tenacity), `service.py` (orchestration logic), and `tasks.py` (Celery wrappers) -- plus a webhook router at `/api/v1/webhooks/apollo`. Use `asyncio.run()` inside Celery tasks to run async httpx calls. Use Celery's `apply_async(countdown=300)` for the webhook timeout checker task.

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions
- **D-38:** Conservative retry strategy: exponential backoff starting at 2s, max 60s, 5 retries per call. Only retries transient errors (429 rate limits, 500 server errors, network timeouts). Successful "not found" responses are NOT retried. Retrying failed network requests does not consume additional Apollo credits.
- **D-39:** No per-job API credit budget cap for v1. Track credits consumed per job in metrics (ENRICH-10) but don't enforce a hard limit. Admin manages credits externally via Apollo dashboard.
- **D-40:** On persistent Apollo failures (after exhausting retries), mark affected rows as NOT_FOUND with error details. Job completes as PARTIAL (some rows enriched, some failed). No infinite retry loops or job pausing.
- **D-41:** Standalone enrichment service module: new `app/enrichment/` with `apollo_client.py` (httpx.AsyncClient + tenacity retry decorators), `service.py` (orchestration logic), and `tasks.py` (Celery task wrappers). Clean separation for testability without Celery.
- **D-42:** Webhook authentication via shared secret in header. Add `APOLLO_WEBHOOK_SECRET` to Settings. Apollo sends the secret in `X-Apollo-Secret` header. Endpoint rejects requests without a matching secret. Returns 200 immediately on valid requests.
- **D-43:** Webhook timeout: 5 minutes. If Apollo's webhook does not deliver phone data within 5 minutes of the API call, the row completes with email only and blank phone. Timeout and absence of phone data recorded in per-job metrics.
- **D-44:** Webhook correlation via Apollo lookup ID. Store the lookup ID from Apollo's API response on the contact record. When webhook arrives, it includes the same ID for 1:1 matching. No ambiguity, no collision risk across concurrent jobs.
- **D-45:** Webhook endpoint at `/api/v1/webhooks/apollo`. Dedicated webhook router under `/api/v1/`. No JWT auth required (uses shared secret instead). Consistent with project's URL prefix pattern.
- **D-46:** Accept late webhooks after timeout. If a webhook arrives after the 5-minute timeout, still update the contact's phone field in the database for future lookups. The original job/row stays marked as complete with email-only status. No credit is wasted -- the data was already paid for.
- **D-47:** Database-first lookup: email-first, then LinkedIn URL fallback. Primary match on email (already UNIQUE in contacts table). If the row has no email but has a LinkedIn URL, match on that. Name+company is too fuzzy for automated matching -- those rows go to Apollo.
- **D-48:** Within-upload deduplication: normalize identifiers (lowercase email, trim whitespace) and group rows by unique contact identity before calling Apollo. One Apollo call per unique contact, results fanned to all matching rows. Saves credits on uploads with duplicates.
- **D-49:** Add partial unique index on `linkedin_url` (WHERE linkedin_url IS NOT NULL) to the Contact model via Alembic migration. Enables LinkedIn-based dedup at the DB level without breaking contacts that lack a LinkedIn URL. Email UNIQUE constraint stays as-is.
- **D-50:** Single orchestrator Celery task per job: `process_enrichment_job(job_id)`. Loads all PENDING rows, deduplicates, performs DB lookups, calls Apollo for unknowns, writes results. One task = one job. Uses async within the task for Apollo API calls.
- **D-51:** Job progress tracked via database row counts. Update Job model fields (`processed_rows`, `cache_hits`, `api_calls`) as rows complete, in batches (every N rows). Frontend polls `GET /jobs/{id}` for status. No extra infrastructure needed.
- **D-52:** Job status logic: PARTIAL if any rows are NOT_FOUND or ERROR but others succeeded. COMPLETE only when all enrichable rows got results (both email and phone or timed out gracefully). FAILED only on catastrophic errors (DB down, unrecoverable). Matches existing JobStatus enum.
- **D-53:** Webhook wait via timer-based check: after all Apollo calls complete, transition job to AWAITING_WEBHOOKS. Schedule a delayed Celery task (5 min) that checks if all webhooks were received. If yes -> COMPLETE. If not -> mark remaining rows email-only, transition to COMPLETE/PARTIAL.

### Claude's Discretion
- Internal structure of the deduplication grouping logic (hash keys, data structures)
- Exact httpx.AsyncClient configuration (connection pool size, timeouts)
- Celery task configuration (acks_late, reject_on_worker_lost, time_limit)
- Batch size for progress update flushes
- Pydantic schema design for webhook payload validation

### Deferred Ideas (OUT OF SCOPE)
None -- discussion stayed within phase scope.
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| ENRICH-01 | System assigns a unique UUID to each row at parse time, tracked through the entire pipeline | Already implemented: JobRow has UUID PK via UUIDMixin. Enrichment reads rows by UUID. |
| ENRICH-02 | System deduplicates contacts within a single upload (same person = one API call, result fanned to all matching rows) | D-48 defines normalization (lowercase email, trim whitespace) + grouping. Research provides dedup grouping pattern. |
| ENRICH-03 | System checks local contact database first before making any Apollo API call | D-47 defines email-first, LinkedIn fallback lookup strategy. Contact model already has email UNIQUE + linkedin_url fields. |
| ENRICH-04 | System calls Apollo People Enrichment API for contacts not found in local database; email immediate, phone via webhook | Apollo API research confirms endpoint, request/response format, webhook delivery pattern. D-38 defines retry. |
| ENRICH-05 | System stores all Apollo enrichment results in the local contact database for future lookups | Contact model has email, phone, raw_apollo_response JSONB fields ready. D-46 handles late webhook updates. |
| ENRICH-06 | System marks rows where Apollo returns no match with a "not found" status column | RowStatus.NOT_FOUND already exists. D-40 defines behavior on persistent failures. |
| ENRICH-07 | System processes large files (1,000+ rows) as background jobs with progress tracking | D-50 defines single Celery orchestrator task. D-51 defines DB-based progress tracking. |
| ENRICH-08 | System isolates concurrent jobs so multiple users can process simultaneously without data corruption | Each job gets its own Celery task with separate DB session. Row-level UUID keying prevents cross-job data mixing. |
| ENRICH-09 | System preserves the original uploaded file (never modified) | Already handled: original saved at `{upload_dir}/{job_id}/original.xlsx`. Enrichment reads from DB, not file. |
| ENRICH-10 | System tracks per-job metrics (cache hits, cache misses, API calls, credits, webhook callbacks, webhook timeouts) | D-39/D-51 define metrics fields. Job model needs new columns: processed_rows, cache_hits, api_calls, webhook_callbacks_received, webhook_timeouts. |
| ENRICH-11 | System exposes webhook receiver endpoint with auth, correlation, timeout handling | D-42/D-43/D-44/D-45/D-46 define webhook endpoint behavior. Apollo API research confirms `request_id` correlation. |
| JOB-01 | System assigns unique job ID tracking full lifecycle (PENDING_CONFIRMATION -> PROCESSING -> AWAITING_WEBHOOKS -> COMPLETE/PARTIAL/FAILED) | JobStatus enum already has all states. D-52/D-53 define transition logic. confirm_job() is the trigger point. |
</phase_requirements>

## Standard Stack

### Core (already installed)
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| httpx | 0.28.1 | Apollo API HTTP client | Already in pyproject.toml. Async client with connection pooling. [VERIFIED: pyproject.toml] |
| tenacity | 9.1.4 | Retry logic with exponential backoff | Already in pyproject.toml. Declarative retry for Apollo 429/5xx. [VERIFIED: pyproject.toml] |
| celery | 5.6.3 | Background job processing | Already in pyproject.toml. Single orchestrator task per job (D-50). [VERIFIED: pyproject.toml] |
| redis | 7.4.0 | Celery broker + result backend | Already in pyproject.toml. Redis 7-alpine in docker-compose. [VERIFIED: pyproject.toml] |
| sqlalchemy | 2.0.49 | Async ORM for contact/job DB operations | Already in pyproject.toml. 2.x async engine. [VERIFIED: pyproject.toml] |
| asyncpg | 0.31.0 | PostgreSQL async driver | Already in pyproject.toml. Required by SQLAlchemy async. [VERIFIED: pyproject.toml] |
| alembic | 1.18.4 | DB migration for new columns/indexes | Already in pyproject.toml. Needed for Job metrics fields + linkedin_url index. [VERIFIED: pyproject.toml] |
| pydantic-settings | 2.13.1 | Config management for Apollo settings | Already in pyproject.toml. Extend Settings class. [VERIFIED: pyproject.toml] |

### No New Dependencies Needed
All libraries required for Phase 3 are already installed. No new packages to add.

## Architecture Patterns

### New Module Structure
```
app/
├── enrichment/           # NEW — Phase 3
│   ├── __init__.py
│   ├── apollo_client.py  # httpx.AsyncClient + tenacity retry decorators
│   ├── service.py        # Orchestration: dedup, DB lookup, API calls, result writing
│   ├── tasks.py          # Celery task wrappers (sync shells around async service)
│   ├── routes.py         # Webhook receiver endpoint
│   └── schemas.py        # Pydantic models for webhook payload validation
├── jobs/
│   ├── models.py         # MODIFIED — add progress fields to Job
│   └── service.py        # MODIFIED — dispatch Celery task after confirm_job()
├── contacts/
│   └── models.py         # EXISTING — enrichment writes to this model
└── config.py             # MODIFIED — add Apollo/webhook settings
```

### Pattern 1: Async-in-Celery Bridge
**What:** Celery tasks are synchronous. Apollo API calls use httpx.AsyncClient. Bridge with `asyncio.run()`.
**When to use:** Every Celery task that needs to make async HTTP calls.
**Example:**
```python
# Source: https://github.com/celery/celery/discussions/9058 [CITED]
import asyncio
from app.celery_app import celery_app

@celery_app.task(bind=True, acks_late=True, reject_on_worker_lost=True)
def process_enrichment_job(self, job_id: str):
    """Sync Celery task wrapper. Runs async service logic via asyncio.run()."""
    asyncio.run(_process_enrichment_job_async(job_id))

async def _process_enrichment_job_async(job_id: str):
    """Actual async orchestration logic."""
    # Create fresh async DB session (not from FastAPI deps)
    # ... orchestration logic
```

### Pattern 2: Tenacity Retry for Apollo API
**What:** Wrap every Apollo API call with tenacity for transient error handling.
**When to use:** All calls to `api.apollo.io`.
**Example:**
```python
# Source: https://tenacity.readthedocs.io/en/latest/ [CITED]
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
import httpx

class ApolloClientError(Exception):
    """Non-retryable Apollo error (400, 404, etc.)."""
    pass

class ApolloTransientError(Exception):
    """Retryable Apollo error (429, 5xx, network)."""
    pass

@retry(
    stop=stop_after_attempt(5),
    wait=wait_exponential(multiplier=2, min=2, max=60),
    retry=retry_if_exception_type(ApolloTransientError),
    reraise=True,
)
async def enrich_person(client: httpx.AsyncClient, params: dict) -> dict:
    """Call Apollo People Enrichment API with retry on transient errors."""
    response = await client.post(
        "https://api.apollo.io/api/v1/people/match",
        json=params,
        headers={"x-api-key": api_key},
    )
    if response.status_code == 429:
        raise ApolloTransientError("Rate limited")
    if response.status_code >= 500:
        raise ApolloTransientError(f"Server error: {response.status_code}")
    if response.status_code == 401:
        raise ApolloClientError("Invalid API key")
    response.raise_for_status()
    return response.json()
```

### Pattern 3: Delayed Celery Task for Webhook Timeout
**What:** After all Apollo calls, schedule a check task with `countdown=300` (5 min).
**When to use:** After job transitions to AWAITING_WEBHOOKS.
**Example:**
```python
# Source: https://docs.celeryq.dev/en/latest/userguide/calling.html [CITED]
@celery_app.task(bind=True)
def check_webhook_completion(self, job_id: str):
    """Check if all webhooks arrived. If not, finalize with email-only."""
    asyncio.run(_check_webhook_completion_async(job_id))

# Dispatched after all API calls complete:
check_webhook_completion.apply_async(
    args=[str(job_id)],
    countdown=300,  # 5 minutes
)
```

**Important Celery/Redis caveat:** The default Redis visibility timeout is 1 hour. A 5-minute countdown is well within this limit, so no configuration change is needed. [CITED: https://docs.celeryq.dev/en/latest/userguide/calling.html]

### Pattern 4: Webhook Receiver with Shared Secret Auth
**What:** FastAPI endpoint that validates `X-Apollo-Secret` header, returns 200 immediately, processes payload.
**When to use:** The `/api/v1/webhooks/apollo` endpoint.
**Example:**
```python
from fastapi import APIRouter, Header, HTTPException, status

router = APIRouter(tags=["webhooks"])

@router.post("/webhooks/apollo", status_code=200)
async def receive_apollo_webhook(
    payload: ApolloWebhookPayload,
    x_apollo_secret: str = Header(...),
    db: AsyncSession = Depends(get_db),
):
    if x_apollo_secret != settings.apollo_webhook_secret:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)
    # Process webhook: find contact by apollo_id, update phone
    # Return 200 immediately
    return {"status": "ok"}
```

### Pattern 5: Deduplication Grouping
**What:** Normalize identifiers and group rows by unique contact identity before API calls.
**When to use:** Before the Apollo API call loop in the orchestrator.
**Example:**
```python
from collections import defaultdict

def build_dedup_groups(rows: list[JobRow], column_mappings: list[dict]) -> dict[str, list[JobRow]]:
    """Group rows by normalized contact identity. One API call per group."""
    groups: dict[str, list[JobRow]] = defaultdict(list)
    for row in rows:
        # Extract identifiers using column_mappings
        email = extract_field(row.raw_data, column_mappings, "email")
        linkedin = extract_field(row.raw_data, column_mappings, "linkedin_url")
        # Normalize
        if email:
            key = f"email:{email.strip().lower()}"
        elif linkedin:
            key = f"linkedin:{linkedin.strip().lower()}"
        else:
            key = f"row:{row.id}"  # No dedup possible, treat as unique
        groups[key].append(row)
    return groups
```

### Anti-Patterns to Avoid
- **Running httpx directly in Celery without asyncio.run():** Will fail -- Celery tasks are sync, httpx.AsyncClient needs an event loop. [VERIFIED: celery/celery#9058]
- **Using `requests` instead of `httpx`:** Synchronous, blocks event loop, CLAUDE.md explicitly forbids it. [VERIFIED: CLAUDE.md]
- **Creating a new SQLAlchemy engine per API call:** Expensive. Create one engine per task invocation, use a session for the batch. [ASSUMED]
- **Storing webhook state in Redis instead of PostgreSQL:** Violates the decision to use DB-based tracking (D-51). PostgreSQL provides durability and transactional consistency. [VERIFIED: CONTEXT.md D-51]
- **Using Celery groups/chords for per-row tasks:** D-50 explicitly specifies one orchestrator task per job. Per-row tasks would create thousands of tasks, overwhelming the broker. [VERIFIED: CONTEXT.md D-50]

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| HTTP retry with backoff | Custom retry loop | tenacity `@retry` decorator | Handles jitter, backoff curves, exception filtering, logging. D-38 specifies the exact params. |
| Async HTTP client | requests or urllib3 | httpx.AsyncClient | Connection pooling, async/await, timeout config, mock transport for tests. |
| Background job queue | threading/multiprocessing | Celery with Redis | Task persistence, retry, monitoring (Flower), delayed scheduling. |
| DB migrations | Raw SQL ALTER TABLE | Alembic | Version tracking, rollback, team collaboration. |
| Config from env vars | `os.getenv()` | pydantic-settings | Type validation, `.env` file support, default values. |
| UUID generation | Custom ID schemes | SQLAlchemy UUIDMixin | Already established pattern in codebase. Consistent PKs across all models. |

## Common Pitfalls

### Pitfall 1: Celery Task Accessing FastAPI Request-Scoped Dependencies
**What goes wrong:** Importing `get_db` from `app.deps` and calling it inside a Celery task fails because there's no FastAPI request context.
**Why it happens:** `get_db` is a FastAPI dependency (generator). Celery runs outside FastAPI's ASGI lifecycle.
**How to avoid:** Create a standalone async session factory in the Celery task. Import `async_session` from `app.database` directly and create sessions manually.
**Warning signs:** `RuntimeError: No current context` or `GeneratorExit` errors in Celery worker logs.

### Pitfall 2: Celery JSON Serialization of UUIDs
**What goes wrong:** Passing UUID objects as Celery task arguments fails because JSON serializer doesn't handle UUIDs.
**Why it happens:** Celery is configured with `task_serializer="json"`. UUID is not JSON-serializable.
**How to avoid:** Always pass `str(job_id)` to Celery tasks, convert back to UUID inside the task with `uuid.UUID(job_id)`.
**Warning signs:** `TypeError: Object of type UUID is not JSON serializable` in task dispatch.

### Pitfall 3: Race Condition Between Webhook and Timeout Checker
**What goes wrong:** Webhook arrives at the exact moment the timeout checker runs, causing double-processing or inconsistent state.
**Why it happens:** Two concurrent database updates without proper locking.
**How to avoid:** Use `SELECT ... FOR UPDATE` on the contact/job row when updating phone data from webhook. The timeout checker should also use `FOR UPDATE` and check if phone is already populated before marking as timed-out. D-46 says late webhooks still update the contact DB -- so the webhook handler should always write if phone is empty, regardless of job status.
**Warning signs:** Contacts with phone data but job metrics showing them as timed-out.

### Pitfall 4: Apollo API Key Not Available at Task Time
**What goes wrong:** Celery worker reads API key from Settings at import time, but admin may update it via the ApiConfig table at runtime.
**Why it happens:** pydantic-settings reads `.env` at startup. The admin API key update writes to the `api_config` DB table, not to env vars.
**How to avoid:** The Apollo client should read the API key from the `api_config` table at the start of each job execution, not from Settings.
**Warning signs:** 401 errors from Apollo after admin rotates the key.

### Pitfall 5: Visibility Timeout with Redis Broker
**What goes wrong:** Tasks with `countdown`/`eta` get redelivered to multiple workers if countdown exceeds Redis visibility timeout (default: 1 hour).
**Why it happens:** Redis broker redelivers unacknowledged messages after visibility timeout.
**How to avoid:** The 5-minute countdown (D-43) is well within the 1-hour default. No change needed. But if timeouts are ever increased beyond 1 hour, set `broker_transport_options = {'visibility_timeout': N}`.
**Warning signs:** Duplicate task execution, webhook completion checker running multiple times.

### Pitfall 6: N+1 Queries in Dedup DB Lookup
**What goes wrong:** Checking each contact one-by-one against the database creates O(n) queries for n unique contacts.
**Why it happens:** Naive loop: `for email in emails: SELECT * FROM contacts WHERE email = :email`.
**How to avoid:** Batch lookup: `SELECT * FROM contacts WHERE email IN (:emails)`. Build a lookup dict from results, then iterate rows.
**Warning signs:** Slow processing of large uploads, excessive DB queries in logs.

## Code Examples

### Apollo API Request/Response (Verified)
```python
# Source: https://docs.apollo.io/reference/people-enrichment [CITED]
# POST https://api.apollo.io/api/v1/people/match

# Request:
{
    "first_name": "John",
    "last_name": "Doe",
    "organization_name": "Acme Corp",
    "email": "john@acme.com",
    "linkedin_url": "linkedin.com/in/johndoe",
    "reveal_personal_emails": True,
    "reveal_phone_number": True,
    "webhook_url": "https://your-domain.com/api/v1/webhooks/apollo"
}

# Synchronous Response (200):
{
    "person": {
        "id": "5f2a3b...",          # <-- Apollo person ID for correlation
        "first_name": "John",
        "last_name": "Doe",
        "email": "john@acme.com",
        "email_status": "verified",
        "linkedin_url": "linkedin.com/in/johndoe",
        "title": "VP Sales",
        "organization": {
            "name": "Acme Corp",
            "domain": "acme.com"
        }
    },
    "waterfall": {
        "status": "accepted"        # Phone delivery pending via webhook
    }
}

# Webhook Payload (arrives async, typically minutes later):
# Includes request_id for correlation and phone_numbers array
{
    "request_id": "...",
    "people": [{
        "id": "5f2a3b...",          # Same person ID as sync response
        "waterfall": {
            "phone_numbers": [{
                "raw_number": "+1-555-123-4567",
                "sanitized_number": "+15551234567",
                "confidence_cd": "high",
                "status_cd": "valid_number"
            }]
        }
    }]
}
```

### DB Session Inside Celery Task
```python
# Pattern for creating async DB sessions outside FastAPI context
# Source: existing pattern in app/database.py [VERIFIED: codebase]
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from app.config import settings

def get_task_session_factory() -> async_sessionmaker[AsyncSession]:
    """Create a session factory for use in Celery tasks."""
    engine = create_async_engine(settings.database_url, echo=False)
    return async_sessionmaker(engine, expire_on_commit=False)
```

### Alembic Migration for New Fields
```python
# Migration: add Job progress fields + Contact linkedin_url partial index
# Fields needed on Job model:
#   processed_rows: Integer, default 0
#   cache_hits: Integer, default 0
#   api_calls: Integer, default 0
#   webhook_callbacks_received: Integer, default 0
#   webhook_timeouts: Integer, default 0

# Fields needed on Contact model:
#   apollo_id: String(255), nullable, indexed  (for webhook correlation per D-44)

# Index:
#   partial unique index on contacts.linkedin_url WHERE linkedin_url IS NOT NULL (D-49)
```

### Enrichment Orchestration Flow
```python
# Pseudocode for service.py orchestration (D-50)
async def process_job(job_id: uuid.UUID, session_factory):
    async with session_factory() as db:
        # 1. Load job + all PENDING rows
        job = await load_job(db, job_id)
        rows = await load_pending_rows(db, job_id)

        # 2. Transition job to PROCESSING
        job.status = "processing"
        await db.commit()

        # 3. Build dedup groups from rows using column_mappings
        groups = build_dedup_groups(rows, job.column_mappings)

        # 4. Batch DB lookup for existing contacts
        existing = await batch_contact_lookup(db, groups)

        # 5. For cache hits: link rows to existing contacts, mark ENRICHED
        # 6. For cache misses: call Apollo API (one per unique contact)
        #    - Create/update Contact record with email + apollo_id
        #    - Store raw_apollo_response
        #    - Link all rows in the group to the contact
        # 7. Update progress metrics in batches

        # 8. Transition to AWAITING_WEBHOOKS
        job.status = "awaiting_webhooks"
        await db.commit()

        # 9. Schedule timeout checker
        check_webhook_completion.apply_async(
            args=[str(job_id)], countdown=300
        )
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Apollo phone in sync response | Phone delivered via webhook (waterfall) | 2025 | Must implement webhook receiver endpoint |
| Celery with sync HTTP (requests) | asyncio.run() + httpx in Celery tasks | 2024+ | Enables concurrent API calls within a single task |
| celery-pool-asyncio | asyncio.run() in standard prefork | 2025 | celery-pool-asyncio adds dependency; asyncio.run() is simpler for our use case |

**Deprecated/outdated:**
- `requests` library: Synchronous only. CLAUDE.md explicitly forbids it. Use `httpx`.
- Celery with `sync=True` on httpx: No such option. Use `asyncio.run()`.

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | Apollo webhook payload includes `people[].id` matching the sync response `person.id` for correlation | Architecture Patterns / Code Examples | If correlation field is different, webhook handler can't match contacts. Mitigated by D-44 which says to store the lookup ID -- verify actual field name against live API response during implementation. |
| A2 | Apollo webhook payload includes `phone_numbers` array with `sanitized_number` field | Code Examples | If field names differ, webhook parser breaks. Validate against actual webhook during integration testing. |
| A3 | Apollo webhook sends `X-Apollo-Secret` header for authentication | Architecture Patterns | D-42 specifies this header name. If Apollo uses a different mechanism, webhook auth needs adjustment. Must verify against actual Apollo webhook behavior. |
| A4 | Creating a new SQLAlchemy engine per Celery task invocation is acceptable for this workload | Anti-Patterns | If engine creation is too expensive, move to a module-level engine with lazy initialization. |
| A5 | Apollo rate limit of 600 calls/hour applies to the People Enrichment endpoint | Common Pitfalls | If rate limit is different per plan tier, retry backoff may need adjustment. |

## Open Questions

1. **Apollo Webhook Authentication Mechanism**
   - What we know: D-42 specifies `X-Apollo-Secret` header. Apollo docs don't explicitly document webhook signing/authentication.
   - What's unclear: Whether Apollo actually sends a shared secret header, or uses a different mechanism (e.g., HMAC signature).
   - Recommendation: Implement D-42 as specified (shared secret header). During integration testing, inspect actual webhook headers from Apollo and adjust if needed.

2. **Apollo Webhook Payload Exact Schema**
   - What we know: Payload includes `people` array with `waterfall.phone_numbers`. Research found `raw_number`, `sanitized_number`, `confidence_cd`, `status_cd` fields. [CITED: docs.apollo.io]
   - What's unclear: Complete Pydantic schema for validation. Whether all fields are always present.
   - Recommendation: Define a permissive Pydantic model (most fields Optional). Log full webhook payloads in development for schema refinement.

3. **Apollo Person ID Stability**
   - What we know: Sync response returns `person.id`. Webhook should include the same ID.
   - What's unclear: Whether `person.id` is the correct correlation field or if `request_id` is better.
   - Recommendation: Store both `person.id` (as `apollo_id` on Contact) and the `request_id` if available. Match on either during webhook processing.

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest 8.x + pytest-asyncio 1.3.0 |
| Config file | pyproject.toml `[tool.pytest.ini_options]` with `asyncio_mode = "auto"` |
| Quick run command | `docker compose exec api pytest tests/enrichment/ -x -q` |
| Full suite command | `docker compose exec api pytest tests/ -v` |

### Phase Requirements -> Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| ENRICH-01 | Row UUID tracked through pipeline | unit | `pytest tests/enrichment/test_service.py::test_row_uuid_preserved -x` | Wave 0 |
| ENRICH-02 | Dedup within upload (one API call per unique contact) | unit | `pytest tests/enrichment/test_service.py::test_dedup_groups -x` | Wave 0 |
| ENRICH-03 | DB-first lookup before Apollo call | unit | `pytest tests/enrichment/test_service.py::test_cache_hit_no_api_call -x` | Wave 0 |
| ENRICH-04 | Apollo API call for unknowns, email immediate | unit | `pytest tests/enrichment/test_apollo_client.py::test_enrich_person_success -x` | Wave 0 |
| ENRICH-05 | Results stored in contact DB | unit | `pytest tests/enrichment/test_service.py::test_contact_created_from_apollo -x` | Wave 0 |
| ENRICH-06 | Not-found rows marked NOT_FOUND | unit | `pytest tests/enrichment/test_service.py::test_not_found_row_status -x` | Wave 0 |
| ENRICH-07 | Background processing with progress | integration | `pytest tests/enrichment/test_tasks.py::test_process_job_background -x` | Wave 0 |
| ENRICH-08 | Concurrent job isolation | integration | `pytest tests/enrichment/test_tasks.py::test_concurrent_jobs_isolated -x` | Wave 0 |
| ENRICH-09 | Original file preserved | unit | `pytest tests/enrichment/test_service.py::test_original_file_untouched -x` | Wave 0 |
| ENRICH-10 | Per-job metrics tracked | unit | `pytest tests/enrichment/test_service.py::test_job_metrics_updated -x` | Wave 0 |
| ENRICH-11 | Webhook receiver with auth + correlation + timeout | integration | `pytest tests/enrichment/test_webhook.py -x` | Wave 0 |
| JOB-01 | Full job lifecycle transitions | integration | `pytest tests/enrichment/test_tasks.py::test_job_lifecycle -x` | Wave 0 |

### Sampling Rate
- **Per task commit:** `docker compose exec api pytest tests/enrichment/ -x -q`
- **Per wave merge:** `docker compose exec api pytest tests/ -v`
- **Phase gate:** Full suite green before `/gsd-verify-work`

### Wave 0 Gaps
- [ ] `tests/enrichment/__init__.py` -- package init
- [ ] `tests/enrichment/test_apollo_client.py` -- covers ENRICH-04, mocked httpx
- [ ] `tests/enrichment/test_service.py` -- covers ENRICH-01/02/03/05/06/09/10
- [ ] `tests/enrichment/test_tasks.py` -- covers ENRICH-07/08, JOB-01
- [ ] `tests/enrichment/test_webhook.py` -- covers ENRICH-11
- [ ] `tests/conftest.py` updates -- add fixtures for mock Apollo responses, job with confirmed status

## Security Domain

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | yes (webhook endpoint) | Shared secret header validation (D-42) |
| V3 Session Management | no | N/A -- webhook is stateless |
| V4 Access Control | yes | Job ownership check (existing pattern), webhook has no user context |
| V5 Input Validation | yes | Pydantic schema validation for webhook payload, UUID validation for job_id |
| V6 Cryptography | no | API key stored in DB (existing ApiConfig), no new crypto |

### Known Threat Patterns for This Stack

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| Webhook forgery (fake Apollo callbacks) | Spoofing | Shared secret header validation (D-42). Reject without `X-Apollo-Secret`. |
| Webhook replay attack | Replay/Tampering | Idempotent handler -- if phone already set, skip update. Duplicate webhook payloads are harmless. |
| Job ID enumeration | Information Disclosure | UUIDs (not sequential IDs). Job ownership check on all endpoints. |
| API key exposure in logs | Information Disclosure | Never log API key. Use `repr()` masking in debug output. |
| Unbounded webhook payload | Denial of Service | Pydantic validation with max field lengths. FastAPI default body size limit. |
| Apollo API key theft from DB | Information Disclosure | Existing ApiConfig pattern. Key stored in DB, not in env file on disk. Access controlled by admin-only endpoint. |

## Sources

### Primary (HIGH confidence)
- Apollo People Enrichment API docs: https://docs.apollo.io/reference/people-enrichment -- endpoint URL, request params, response format, rate limits
- Apollo Waterfall Enrichment: https://docs.apollo.io/docs/enrich-phone-and-email-using-data-waterfall -- webhook delivery, request_id correlation
- Apollo Phone Number Retrieval: https://docs.apollo.io/docs/retrieve-mobile-phone-numbers-for-contacts -- webhook payload format (phone_numbers array)
- Celery Calling Tasks docs: https://docs.celeryq.dev/en/latest/userguide/calling.html -- countdown/eta, visibility timeout
- Project codebase: `app/celery_app.py`, `app/config.py`, `app/jobs/models.py`, `app/jobs/service.py`, `app/contacts/models.py`, `app/deps.py`, `pyproject.toml`

### Secondary (MEDIUM confidence)
- Celery async discussion: https://github.com/celery/celery/discussions/9058 -- asyncio.run() pattern in Celery tasks
- Celery/Redis visibility timeout: https://blog.serindu.com/2023/03/09/celery-redis-countdown-eta-oddities/ -- Redis broker caveats with delayed tasks

### Tertiary (LOW confidence)
- Apollo webhook authentication mechanism: Not documented by Apollo. D-42 specifies `X-Apollo-Secret` header -- needs validation against actual Apollo behavior.
- Exact webhook payload schema: Partially documented. Field names like `sanitized_number`, `confidence_cd` found in docs but full schema not available as JSON Schema.

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH -- all packages already in pyproject.toml with pinned versions
- Architecture: HIGH -- constrained by 16 locked decisions, codebase patterns well-established
- Apollo API integration: MEDIUM -- endpoint/response verified from official docs, but webhook auth mechanism and exact payload schema are partially documented
- Pitfalls: HIGH -- common patterns well-documented in Celery and httpx ecosystems

**Research date:** 2026-04-06
**Valid until:** 2026-05-06 (30 days -- Apollo API docs may update webhook format)

## Project Constraints (from CLAUDE.md)

- **httpx only** for HTTP clients -- never `requests` (sync, blocks event loop)
- **Celery + Redis** for background jobs -- not FastAPI BackgroundTasks (blocks API worker)
- **openpyxl** for Excel -- not xlrd/xlwt (deprecated for .xlsx)
- **SQLAlchemy 2.x async** -- not 1.x legacy patterns
- **PostgreSQL** -- not SQLite (no concurrent writes, no JSONB)
- **HS256 JWT** -- not RS256 (internal tool, no key rotation infra)
- **pydantic-settings** for config -- not `os.getenv()`
- **Docker named networks** -- no `--privileged` or host networking
- **uv** for package management
- **Ruff** for linting/formatting
- **pytest + pytest-asyncio** for testing
