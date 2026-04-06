# Phase 3: Enrichment Pipeline - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-04-06
**Phase:** 03-enrichment-pipeline
**Areas discussed:** Apollo API integration, Webhook handling, Deduplication strategy, Celery task design

---

## Apollo API Integration

| Option | Description | Selected |
|--------|-------------|----------|
| Conservative backoff (Recommended) | Exponential backoff starting at 2s, max 60s, 5 retries per call. Pause entire job on repeated 429s. | ✓ |
| Aggressive throughput | Short backoff (0.5s start), 3 retries, continue other rows while one is rate-limited. | |
| You decide | Claude picks the retry strategy. | |

**User's choice:** Conservative backoff
**Notes:** User asked if conservative backoff causes unnecessary credit consumption. Clarified that retries only fire on transient errors (429, 500, network) — not on successful responses. Failed network requests don't reach Apollo's billing layer, so retries don't consume extra credits.

| Option | Description | Selected |
|--------|-------------|----------|
| No cap for v1 (Recommended) | Track credits but don't enforce limits. | ✓ |
| Configurable cap per job | Admin sets max API calls per job. | |

**User's choice:** No cap for v1

| Option | Description | Selected |
|--------|-------------|----------|
| Mark job as PARTIAL (Recommended) | Failed rows marked NOT_FOUND, job completes as PARTIAL. | ✓ |
| Pause and retry later | Pause job, Celery retries after delay. | |

**User's choice:** Mark job as PARTIAL

| Option | Description | Selected |
|--------|-------------|----------|
| Standalone service (Recommended) | New app/enrichment/ module with separate files. | ✓ |
| Embedded in tasks | Apollo HTTP calls directly in Celery task functions. | |

**User's choice:** Standalone service

---

## Webhook Handling

| Option | Description | Selected |
|--------|-------------|----------|
| Shared secret in header (Recommended) | X-Apollo-Secret header, reject without match. | ✓ |
| HMAC signature verification | HMAC-SHA256 signed payload. | |
| You decide | Research Apollo's actual mechanism. | |

**User's choice:** Shared secret in header

| Option | Description | Selected |
|--------|-------------|----------|
| 5 minutes (Recommended) | Short wait, row completes with email only if no webhook. | ✓ |
| 15 minutes | More generous window. | |
| Configurable via Settings | Admin-tunable timeout. | |

**User's choice:** 5 minutes
**Notes:** User asked if credits are still consumed when webhook doesn't arrive within timeout. Clarified that credits are consumed at API call time, not webhook delivery. The timeout only affects how long *our system* waits before marking the row complete.

| Option | Description | Selected |
|--------|-------------|----------|
| Apollo lookup ID (Recommended) | Store lookup ID, webhook includes same ID for 1:1 match. | ✓ |
| Email-based matching | Match on email field in webhook payload. | |

**User's choice:** Apollo lookup ID

| Option | Description | Selected |
|--------|-------------|----------|
| /api/v1/webhooks/apollo (Recommended) | Dedicated webhook router under /api/v1/. | ✓ |
| /webhooks/apollo (outside /api/v1/) | Separate from main API namespace. | |

**User's choice:** /api/v1/webhooks/apollo

| Option | Description | Selected |
|--------|-------------|----------|
| Accept and update (Recommended) | Late webhook updates contact phone in DB for future lookups. | ✓ |
| Ignore late webhooks | Reject callbacks after timeout. | |

**User's choice:** Accept and update

---

## Deduplication Strategy

| Option | Description | Selected |
|--------|-------------|----------|
| Email-first, then LinkedIn (Recommended) | Primary email match, LinkedIn fallback. | ✓ |
| Multi-field scoring | Weighted confidence across multiple fields. | |
| Email only | Match exclusively on email. | |

**User's choice:** Email-first, then LinkedIn

| Option | Description | Selected |
|--------|-------------|----------|
| Normalize and group (Recommended) | Group rows by unique contact before Apollo calls. | ✓ |
| Process sequentially with cache | Row-by-row with per-result caching. | |

**User's choice:** Normalize and group

| Option | Description | Selected |
|--------|-------------|----------|
| Add LinkedIn URL unique index (Recommended) | Partial unique index WHERE linkedin_url IS NOT NULL. | ✓ |
| Keep email-only UNIQUE | No additional constraints. | |

**User's choice:** Add LinkedIn URL unique index

---

## Celery Task Design

| Option | Description | Selected |
|--------|-------------|----------|
| Single orchestrator task (Recommended) | One Celery task per job, loads all rows. | ✓ |
| Chunked sub-tasks | Split into chunks, spawn sub-tasks per chunk. | |
| Task-per-contact | One task per unique contact. | |

**User's choice:** Single orchestrator task

| Option | Description | Selected |
|--------|-------------|----------|
| Database row counts (Recommended) | Update Job model fields as rows complete. | ✓ |
| Redis-based real-time | Push progress to Redis. | |

**User's choice:** Database row counts

| Option | Description | Selected |
|--------|-------------|----------|
| PARTIAL status (Recommended) | PARTIAL if mixed outcomes, COMPLETE if all good. | ✓ |
| Always COMPLETE with error counts | Always COMPLETE, errors in metrics. | |

**User's choice:** PARTIAL status

| Option | Description | Selected |
|--------|-------------|----------|
| Timer-based check (Recommended) | Delayed Celery task checks webhook status after 5 min. | ✓ |
| Webhook-driven completion | Each webhook checks if it was the last one. | |

**User's choice:** Timer-based check

---

## Claude's Discretion

- Internal deduplication grouping logic structure
- httpx.AsyncClient configuration details
- Celery task configuration (acks_late, time_limit, etc.)
- Batch size for progress update flushes
- Pydantic schema design for webhook payload validation

## Deferred Ideas

None — discussion stayed within phase scope.
