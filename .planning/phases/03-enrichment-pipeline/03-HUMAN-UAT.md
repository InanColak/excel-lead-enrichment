---
status: partial
phase: 03-enrichment-pipeline
source: [03-VERIFICATION.md]
started: 2026-04-07T13:40:00.000Z
updated: 2026-04-07T13:40:00.000Z
---

## Current Test

[awaiting human testing]

## Tests

### 1. Full test suite execution
expected: All 40 tests pass via `docker compose exec api pytest tests/enrichment/ -x`
result: [pending]

### 2. End-to-end enrichment flow
expected: Celery worker processes a confirmed job through full lifecycle — dedup, DB cache lookup, Apollo API calls, result writing per row UUID, status transitions
result: [pending]

### 3. Webhook delivery and phone update
expected: Live POST to /api/v1/webhooks/apollo with valid X-Apollo-Secret header updates contact phone field and increments job webhook_callbacks_received counter
result: [pending]

### 4. Webhook timeout behavior
expected: Celery countdown task fires after webhook_timeout_seconds, marks timed-out rows as EMAIL_ONLY, increments job webhook_timeouts counter
result: [pending]

## Summary

total: 4
passed: 0
issues: 0
pending: 4
skipped: 0
blocked: 0

## Gaps
