# Roadmap: LeadEnrich

## Overview

LeadEnrich is built in four sequential phases. Phase 1 establishes the foundation: Docker infrastructure, database schema with all integrity constraints, auth, and admin controls. Phase 2 builds the file ingestion layer — upload, validation, column detection, and row UUID assignment — which provides the parsed row structure the enrichment pipeline depends on. Phase 3 is the core product: the Celery worker pipeline that executes database-first cache lookups, Apollo API calls, deduplication, and enriched output generation. Critically, Apollo delivers phone numbers asynchronously via webhook callback (not in the immediate API response), so Phase 3 includes a webhook receiver endpoint, per-contact webhook wait logic with timeout handling, and graceful fallback for webhook delivery failures. Phase 4 closes the user-facing loop with job status polling, job history, re-downloads, and the usage stats dashboard. Every v1 requirement is covered across these four phases.

## Phases

**Phase Numbering:**
- Integer phases (1, 2, 3): Planned milestone work
- Decimal phases (2.1, 2.2): Urgent insertions (marked with INSERTED)

Decimal phases appear between their surrounding integers in numeric order.

- [ ] **Phase 1: Foundation** - Docker infrastructure, database schema, auth, admin config, and team management
- [ ] **Phase 2: File Ingestion** - Upload, validation, column detection, manual override, and row UUID assignment
- [ ] **Phase 3: Enrichment Pipeline** - Celery workers, DB-first cache, Apollo API client, async webhook receiver for phone data, deduplication, and enriched output generation
- [ ] **Phase 4: Job Output and History** - Job status polling, job history, re-downloads, and usage stats dashboard

## Phase Details

### Phase 1: Foundation
**Goal**: The application runs in Docker, all users can authenticate, and admins can configure the Apollo API key and manage team members
**Depends on**: Nothing (first phase)
**Requirements**: INFRA-01, INFRA-02, INFRA-03, AUTH-01, AUTH-02, AUTH-03
**Success Criteria** (what must be TRUE):
  1. `docker compose up` starts all services (api, worker, db, redis) and the API responds to health checks
  2. The API's Swagger UI is accessible and documents all available endpoints
  3. A user can obtain a JWT by posting valid email and password credentials
  4. An admin can set the shared Apollo API key via API endpoint without redeployment
  5. An admin can add a new user and that user can immediately log in; an admin can remove a user and that user's token is no longer accepted
**Plans:** 3 plans

Plans:
- [x] 01-01-PLAN.md — Docker infrastructure, FastAPI skeleton, database models, Alembic migrations, health endpoint
- [ ] 01-02-PLAN.md — JWT authentication (login/refresh/logout), admin user management, Apollo API key config, CLI seed
- [x] 01-03-PLAN.md — Integration test suite for all Phase 1 requirements

### Phase 2: File Ingestion
**Goal**: Users can upload Excel files, receive validated parse results with auto-detected column mappings, override those mappings, and confirm before enrichment begins — with every row assigned a unique UUID
**Depends on**: Phase 1
**Requirements**: FILE-01, FILE-02, FILE-03, FILE-04, FILE-05
**Success Criteria** (what must be TRUE):
  1. Uploading a valid Excel file returns a job ID, stores the original file unmodified, and sets job status to `PENDING_CONFIRMATION`
  2. Uploading an invalid file (wrong format, oversized, malformed structure) returns a clear error response and no job is created
  3. The API returns auto-detected column mappings with confidence indicators for a successfully parsed file
  4. A user can submit corrected column mappings via API override before enrichment starts
  5. Every parsed row has a unique UUID assigned before any downstream processing; malformed rows are flagged per-row without aborting the job
**Plans**: TBD

### Phase 3: Enrichment Pipeline
**Goal**: Submitting a confirmed job triggers background processing that enriches every resolvable contact via the local database cache first and Apollo second — handling Apollo's two-stage response (email in the immediate API response, phone number delivered asynchronously via webhook) — writes all results per row by UUID, and produces a downloadable enriched Excel file once both stages are complete
**Depends on**: Phase 2
**Requirements**: ENRICH-01, ENRICH-02, ENRICH-03, ENRICH-04, ENRICH-05, ENRICH-06, ENRICH-07, ENRICH-08, ENRICH-09, ENRICH-10, ENRICH-11, JOB-01
**Success Criteria** (what must be TRUE):
  1. A job with 1,000+ rows processes entirely in the background; the web server returns immediately after job submission
  2. Contacts already in the local database are returned without an Apollo API call (verified by zero increment in API call counter for those rows)
  3. Duplicate contacts within a single upload result in exactly one Apollo API call per unique contact, with results written to all matching rows
  4. Each row's result is written keyed by its UUID — wrong-row assignments are impossible
  5. Two concurrent jobs submitted by different users complete independently with no data mixing between them
  6. Rows Apollo cannot resolve are marked with a "Not Found" status; rows skipped due to missing required identifiers are marked "Skipped"
  7. For contacts Apollo resolves, the email field is populated from the immediate API response; the phone field is populated only after the Apollo webhook delivers it — the pipeline waits for the webhook before marking a contact complete
  8. If Apollo's webhook does not deliver phone data within the configured timeout, the row is marked complete with the email populated and phone left blank (not held indefinitely); the timeout and the absence of phone data are recorded in per-job metrics
  9. The webhook receiver endpoint authenticates incoming Apollo callbacks and rejects unauthenticated or malformed payloads without corrupting job state
**Plans**: TBD
**UI hint**: no

### Phase 4: Job Output and History
**Goal**: Users can poll job progress, download enriched files, retrieve any past job result, and view usage stats showing API credits consumed and cache performance
**Depends on**: Phase 3
**Requirements**: OUTPUT-01, OUTPUT-02, OUTPUT-03, AUTH-04
**Success Criteria** (what must be TRUE):
  1. A user can poll a job status endpoint and receive current progress (rows processed, cache hits, API calls, webhook callbacks received, webhook timeouts, errors) while a job is running
  2. A user can download the enriched Excel file once a job completes — the file contains all original columns plus email, phone, and status columns appended; rows that timed out waiting for webhook phone data show a blank phone cell (not an error)
  3. A user can list all their past jobs and re-download the enriched output from any completed job
  4. A user can query a usage stats endpoint and see total API credits consumed, cache hit rate, and job counts over time
**Plans**: TBD

## Progress

**Execution Order:**
Phases execute in numeric order: 1 → 2 → 3 → 4

| Phase | Plans Complete | Status | Completed |
|-------|----------------|--------|-----------|
| 1. Foundation | 0/3 | Planning complete | - |
| 2. File Ingestion | 0/TBD | Not started | - |
| 3. Enrichment Pipeline | 0/TBD | Not started | - |
| 4. Job Output and History | 0/TBD | Not started | - |
