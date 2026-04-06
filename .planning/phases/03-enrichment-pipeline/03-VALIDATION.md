---
phase: 3
slug: enrichment-pipeline
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-04-06
---

# Phase 3 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 8.x + pytest-asyncio |
| **Config file** | `pyproject.toml` (tool.pytest section) |
| **Quick run command** | `python -m pytest tests/enrichment/ -x -q` |
| **Full suite command** | `python -m pytest tests/ -x -q` |
| **Estimated runtime** | ~15 seconds |

---

## Sampling Rate

- **After every task commit:** Run `python -m pytest tests/enrichment/ -x -q`
- **After every plan wave:** Run `python -m pytest tests/ -x -q`
- **Before `/gsd-verify-work`:** Full suite must be green
- **Max feedback latency:** 15 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 03-01-01 | 01 | 1 | ENRICH-01 | — | N/A | unit | `pytest tests/enrichment/test_models.py -k uuid` | ❌ W0 | ⬜ pending |
| 03-01-02 | 01 | 1 | ENRICH-03,ENRICH-05 | — | N/A | unit | `pytest tests/enrichment/test_service.py -k db_lookup` | ❌ W0 | ⬜ pending |
| 03-01-03 | 01 | 1 | ENRICH-02 | — | N/A | unit | `pytest tests/enrichment/test_service.py -k dedup` | ❌ W0 | ⬜ pending |
| 03-02-01 | 02 | 2 | ENRICH-04,ENRICH-06 | — | N/A | unit | `pytest tests/enrichment/test_apollo_client.py` | ❌ W0 | ⬜ pending |
| 03-02-02 | 02 | 2 | ENRICH-07,ENRICH-08 | — | N/A | integration | `pytest tests/enrichment/test_tasks.py` | ❌ W0 | ⬜ pending |
| 03-02-03 | 02 | 2 | JOB-01 | — | N/A | integration | `pytest tests/enrichment/test_tasks.py -k status` | ❌ W0 | ⬜ pending |
| 03-03-01 | 03 | 3 | ENRICH-11 | T-03-01 | Webhook secret validated, malformed rejected | unit | `pytest tests/enrichment/test_webhook.py` | ❌ W0 | ⬜ pending |
| 03-03-02 | 03 | 3 | ENRICH-10 | — | N/A | integration | `pytest tests/enrichment/test_metrics.py` | ❌ W0 | ⬜ pending |
| 03-03-03 | 03 | 3 | ENRICH-09 | — | N/A | integration | `pytest tests/enrichment/test_tasks.py -k preserve` | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `tests/enrichment/__init__.py` — test package
- [ ] `tests/enrichment/conftest.py` — shared fixtures (mock Apollo client, test DB session)
- [ ] `tests/enrichment/test_models.py` — stubs for model/migration tests
- [ ] `tests/enrichment/test_service.py` — stubs for dedup and DB lookup tests
- [ ] `tests/enrichment/test_apollo_client.py` — stubs for Apollo API client tests
- [ ] `tests/enrichment/test_tasks.py` — stubs for Celery task integration tests
- [ ] `tests/enrichment/test_webhook.py` — stubs for webhook endpoint tests

*Existing test infrastructure (conftest.py, httpx test client) covers framework setup.*

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Concurrent job isolation | ENRICH-08 | Requires two simultaneous Celery workers | Run two jobs from different users simultaneously, verify no data mixing |
| Late webhook acceptance | D-46 | Requires timing control over webhook delivery | Submit job, wait for timeout, then manually POST webhook, verify contact updated |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 15s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
