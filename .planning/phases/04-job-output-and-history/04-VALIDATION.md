---
phase: 04
slug: job-output-and-history
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-04-07
---

# Phase 04 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 8.x + pytest-asyncio 1.3.0 |
| **Config file** | `pyproject.toml` ([tool.pytest.ini_options] asyncio_mode = "auto") |
| **Quick run command** | `docker compose exec api pytest tests/jobs/ -x -q` |
| **Full suite command** | `docker compose exec api pytest tests/ -v` |
| **Estimated runtime** | ~15 seconds |

---

## Sampling Rate

- **After every task commit:** Run `docker compose exec api pytest tests/jobs/ -x -q`
- **After every plan wave:** Run `docker compose exec api pytest tests/ -v`
- **Before `/gsd-verify-work`:** Full suite must be green
- **Max feedback latency:** 15 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 04-01-01 | 01 | 1 | OUTPUT-01 | T-04-02 | Path traversal blocked (server-generated paths only) | unit | `docker compose exec api pytest tests/jobs/test_output.py -x` | No -- Wave 0 | ⬜ pending |
| 04-01-02 | 01 | 1 | OUTPUT-02 | — | N/A | unit | `docker compose exec api pytest tests/jobs/test_status.py -x` | No -- Wave 0 | ⬜ pending |
| 04-02-01 | 02 | 2 | OUTPUT-03 | T-04-01 | IDOR blocked (user_id filter on all queries) | integration | `docker compose exec api pytest tests/jobs/test_list.py tests/jobs/test_download.py -x` | No -- Wave 0 | ⬜ pending |
| 04-02-02 | 02 | 2 | AUTH-04 | T-04-03 | Pagination abuse blocked (limit capped at 100) | integration | `docker compose exec api pytest tests/jobs/test_stats.py -x` | No -- Wave 0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `tests/jobs/test_output.py` — stubs for OUTPUT-01 (Excel generation logic)
- [ ] `tests/jobs/test_list.py` — stubs for OUTPUT-03 (pagination, filtering)
- [ ] `tests/jobs/test_download.py` — stubs for OUTPUT-01/OUTPUT-03 (FileResponse endpoint)
- [ ] `tests/jobs/test_stats.py` — stubs for AUTH-04 (aggregation, date filtering)
- [ ] Test fixtures: completed Job with JobRows + Contacts for output generation testing

*Existing infrastructure covers framework and conftest — only new test files needed.*

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Excel output opens correctly in Excel/Google Sheets | OUTPUT-01 | Binary file visual verification | Download output file, open in spreadsheet app, verify columns and data alignment |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 15s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
