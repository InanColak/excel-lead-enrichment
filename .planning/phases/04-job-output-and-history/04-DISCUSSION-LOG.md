# Phase 4: Job Output and History - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-04-07
**Phase:** 04-job-output-and-history
**Areas discussed:** Excel output format, Job status polling, Job history listing, Usage stats aggregation
**Mode:** --auto (all decisions auto-selected)

---

## Excel Output Format

| Option | Description | Selected |
|--------|-------------|----------|
| Append enriched columns after originals | email, phone, status appended as last 3 columns | auto |

**User's choice:** [auto] Append email, phone, status columns after all original columns
**Notes:** Timed-out webhook rows get blank phone + "email_only" status per OUTPUT-01

---

## Job Status Polling

| Option | Description | Selected |
|--------|-------------|----------|
| Full metrics in existing endpoint | Extend GET /jobs/{id} with all Phase 3 metrics | auto |

**User's choice:** [auto] Full metrics response with computed progress_percent
**Notes:** No new endpoint needed — extend existing JobResponse schema

---

## Job History Listing

| Option | Description | Selected |
|--------|-------------|----------|
| Offset pagination, 20/page default | limit/offset params, status + date filters, desc order | auto |

**User's choice:** [auto] Offset-based pagination with optional status and date range filters
**Notes:** Users only see own jobs (JWT user_id filter)

---

## Usage Stats Aggregation

| Option | Description | Selected |
|--------|-------------|----------|
| SQL aggregation per user | SUM/COUNT on jobs table, optional date range | auto |

**User's choice:** [auto] Per-user aggregation with total_jobs, api_calls, cache_hits, cache_hit_rate, jobs_by_status
**Notes:** No caching/materialized views for v1 — low query volume

---

## Claude's Discretion

- SQL query structure, pagination envelope, error handling for incomplete downloads, openpyxl styling

## Deferred Ideas

None
