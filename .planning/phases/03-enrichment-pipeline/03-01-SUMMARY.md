---
phase: 03-enrichment-pipeline
plan: 01
subsystem: api, database
tags: [apollo, httpx, tenacity, pydantic, alembic, enrichment]

# Dependency graph
requires:
  - phase: 01-foundation
    provides: "Settings, Contact model, Job model, ApiConfig, decrypt_api_key"
provides:
  - "Apollo API client with retry logic (ApolloClient)"
  - "Exception classes for Apollo error handling (ApolloTransientError, ApolloClientError, ApolloNotFoundError)"
  - "DB-based API key retrieval (_get_api_key_from_db)"
  - "Pydantic schemas for Apollo request, response, and webhook payloads"
  - "Job metrics columns (processed_rows, cache_hits, api_calls, webhook_callbacks_received, webhook_timeouts)"
  - "Contact apollo_id column for webhook correlation"
  - "Partial unique index on contacts.linkedin_url"
  - "Apollo and webhook configuration settings"
affects: [03-enrichment-pipeline]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "tenacity @retry decorator for external API calls with exponential backoff"
    - "httpx.AsyncClient with connection pooling for Apollo API"
    - "DB-encrypted API key retrieval pattern (not env vars)"
    - "Partial unique index for nullable columns"

key-files:
  created:
    - app/enrichment/__init__.py
    - app/enrichment/apollo_client.py
    - app/enrichment/schemas.py
    - alembic/versions/003_add_enrichment_fields.py
  modified:
    - app/config.py
    - app/contacts/models.py
    - app/jobs/models.py

key-decisions:
  - "API key passed to ApolloClient constructor from DB, not from env settings, per Pitfall 4"
  - "ApolloNotFoundError separated from transient/client errors to avoid retrying valid no-match responses"
  - "server_default='0' on migration columns to handle existing rows"

patterns-established:
  - "app/enrichment/ module structure for enrichment pipeline code"
  - "Pydantic BaseModel schemas for external API request/response validation"

requirements-completed: [ENRICH-04, ENRICH-10, ENRICH-11]

# Metrics
duration: 2min
completed: 2026-04-07
---

# Phase 3 Plan 1: Enrichment Foundation Summary

**Apollo API client with tenacity retry (5 attempts, 2s-60s exponential backoff), Pydantic schemas for enrichment/webhook payloads, and Alembic migration adding job metrics + contact correlation columns**

## Performance

- **Duration:** 2 min
- **Started:** 2026-04-07T11:20:21Z
- **Completed:** 2026-04-07T11:22:48Z
- **Tasks:** 2
- **Files modified:** 7

## Accomplishments
- Settings extended with apollo_api_url, apollo_webhook_secret, and webhook_timeout_seconds
- Job model gains 5 metrics columns for enrichment progress tracking (processed_rows, cache_hits, api_calls, webhook_callbacks_received, webhook_timeouts)
- Contact model gains apollo_id for webhook correlation and partial unique index on linkedin_url
- ApolloClient wraps httpx.AsyncClient with tenacity retry matching D-38 parameters exactly
- Three exception classes properly separate retryable (transient) from non-retryable (client/not-found) errors
- Pydantic schemas cover the full Apollo enrichment lifecycle: request, response, and webhook payload

## Task Commits

Each task was committed atomically:

1. **Task 1: Database schema additions and configuration settings** - `b963e68` (feat)
2. **Task 2: Apollo API client module with tenacity retry and Pydantic schemas** - `d772fe0` (feat)

## Files Created/Modified
- `app/config.py` - Added Apollo API URL, webhook secret, and timeout settings
- `app/contacts/models.py` - Added apollo_id column for webhook correlation
- `app/jobs/models.py` - Added 5 enrichment metrics columns
- `alembic/versions/003_add_enrichment_fields.py` - Migration for new columns and partial unique index
- `app/enrichment/__init__.py` - Package init
- `app/enrichment/apollo_client.py` - Apollo API client with httpx + tenacity retry
- `app/enrichment/schemas.py` - Pydantic models for Apollo API interaction

## Decisions Made
- API key passed to ApolloClient constructor from DB (not env settings) per Pitfall 4 and existing decrypt_api_key pattern
- ApolloNotFoundError is a separate exception class so valid no-match responses are never retried
- Migration uses server_default='0' for new NOT NULL integer columns to handle existing rows without data migration

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered
None

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- Enrichment foundation complete: schemas, client, and DB schema ready
- Ready for 03-02 (enrichment service orchestration logic)
- ApolloClient can be instantiated with a decrypted API key and used to call Apollo
- All Pydantic schemas ready for request validation and response parsing

## Self-Check: PASSED

All 7 files verified on disk. Both task commits (b963e68, d772fe0) found in git log.

---
*Phase: 03-enrichment-pipeline*
*Completed: 2026-04-07*
