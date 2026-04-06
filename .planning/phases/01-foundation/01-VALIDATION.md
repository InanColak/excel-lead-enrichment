---
phase: 1
slug: foundation
status: draft
nyquist_compliant: true
wave_0_complete: true
created: 2026-04-06
---

# Phase 1 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 8.x + pytest-asyncio 1.3.0 |
| **Config file** | `pyproject.toml` [tool.pytest.ini_options] — Wave 0 creates this |
| **Quick run command** | `docker compose exec api pytest tests/ -x --timeout=30` |
| **Full suite command** | `docker compose exec api pytest tests/ -v --timeout=60` |
| **Estimated runtime** | ~30 seconds |

---

## Sampling Rate

- **After every task commit:** Run `docker compose exec api pytest tests/ -x --timeout=30`
- **After every plan wave:** Run `docker compose exec api pytest tests/ -v --timeout=60`
- **Before `/gsd-verify-work`:** Full suite must be green
- **Max feedback latency:** 30 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 1-01-01 | 01 | 1 | INFRA-01 | — | N/A | smoke | `docker compose up -d && curl http://localhost:8000/health` | ❌ W0 | ⬜ pending |
| 1-01-02 | 01 | 1 | INFRA-02 | — | N/A | smoke | `curl -f http://localhost:8000/docs` | ❌ W0 | ⬜ pending |
| 1-01-03 | 01 | 1 | INFRA-03 | — | N/A | unit | `pytest tests/test_routes.py -x` | ❌ W0 | ⬜ pending |
| 1-02-01 | 02 | 2 | AUTH-01 | T-1-01 | JWT secret from env var, bcrypt password hash | integration | `pytest tests/auth/test_login.py -x` | ❌ W0 | ⬜ pending |
| 1-02-02 | 02 | 2 | AUTH-02 | T-1-02 | Apollo API key never logged | integration | `pytest tests/admin/test_config.py -x` | ❌ W0 | ⬜ pending |
| 1-02-03 | 02 | 2 | AUTH-03 | T-1-03 | Revoked token rejected via Redis blocklist | integration | `pytest tests/admin/test_users.py -x` | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `pyproject.toml` — [tool.pytest.ini_options] section with asyncio_mode = "auto"
- [ ] `tests/conftest.py` — async test client fixture, test database setup, Redis mock/fixture
- [ ] `tests/auth/test_login.py` — covers AUTH-01
- [ ] `tests/admin/test_users.py` — covers AUTH-03
- [ ] `tests/admin/test_config.py` — covers AUTH-02
- [ ] `tests/test_health.py` — covers INFRA-01 (API-level), INFRA-02 (route existence)
- [ ] Framework install in Docker image: `uv pip install pytest pytest-asyncio httpx`
n> **Note:** Plan 01-03 (Wave 3) creates all Wave 0 test scaffolding. This is acceptable because Plans 01/02 contain inline `<verify>` commands that validate without pytest, and Plan 03 creates the full test suite before phase verification.

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Docker Compose starts all services | INFRA-01 | Requires full Docker environment | `docker compose up -d`, verify all containers healthy with `docker compose ps` |
| Swagger UI accessible and documents endpoints | INFRA-02 | Visual verification of API docs | Open `http://localhost:8000/docs` in browser, confirm endpoints listed |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 30s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
