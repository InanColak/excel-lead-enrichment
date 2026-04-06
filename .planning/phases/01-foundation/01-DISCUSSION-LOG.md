# Phase 1: Foundation - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-04-06
**Phase:** 1-Foundation
**Areas discussed:** Database schema design, Auth & token strategy, Project structure, Docker & service topology

---

## Database Schema Design

| Option | Description | Selected |
|--------|-------------|----------|
| JSONB column | Store raw Apollo response as JSONB alongside extracted email/phone columns | ✓ |
| Fully normalized columns | Extract every field into its own column | |
| Hybrid approach | Extracted columns for queried fields plus JSONB for full response | |

**User's choice:** JSONB column
**Notes:** User confirmed JSONB is internal only — Excel output should only show email, phone, status.

---

| Option | Description | Selected |
|--------|-------------|----------|
| Email as primary key | Deduplicate contacts by email address | ✓ |
| Composite key (email + company) | Handle same person at multiple companies | |
| LinkedIn URL as primary key | Most stable identifier but not always present | |
| Multi-column match | Match on email, LinkedIn URL, or name+company | |

**User's choice:** Email as primary key
**Notes:** None

---

| Option | Description | Selected |
|--------|-------------|----------|
| Phase 1 only | Create only users, contacts, api_config tables | ✓ |
| Full schema upfront | Create all tables now including jobs/rows/webhooks | |
| Core + stubs | Phase 1 tables plus empty placeholder tables | |

**User's choice:** Phase 1 only
**Notes:** None

---

| Option | Description | Selected |
|--------|-------------|----------|
| UUIDs everywhere | UUID primary keys on all tables | ✓ |
| Auto-increment integers | Traditional integer PKs | |
| Mixed approach | UUIDs for user-facing, integers for internal | |

**User's choice:** UUIDs everywhere
**Notes:** None

---

## Auth & Token Strategy

| Option | Description | Selected |
|--------|-------------|----------|
| Short-lived + refresh token | 30 min access token, 7 day refresh token | ✓ |
| Long-lived access token | Single token valid 7-30 days | |
| Session-based (no JWT) | Server-side sessions in Redis | |

**User's choice:** Short-lived + refresh token
**Notes:** None

---

| Option | Description | Selected |
|--------|-------------|----------|
| CLI seed command | Management command run once during initial deployment | ✓ |
| Auto-create from env vars | Auto-create admin on first startup if no users exist | |
| Open registration endpoint | First user to register becomes admin | |

**User's choice:** CLI seed command
**Notes:** None

---

| Option | Description | Selected |
|--------|-------------|----------|
| Token blocklist in Redis | Add JTIs to Redis blocklist on user removal | ✓ |
| User active flag check | Check is_active flag in DB on every request | |
| Short token + no revocation | Rely on 30-min expiry for natural invalidation | |

**User's choice:** Token blocklist in Redis
**Notes:** None

---

| Option | Description | Selected |
|--------|-------------|----------|
| Simple is_admin flag | Boolean column on user table | ✓ |
| Role table with permissions | Separate roles with granular permissions | |

**User's choice:** Simple is_admin flag
**Notes:** None

---

## Project Structure

| Option | Description | Selected |
|--------|-------------|----------|
| Feature-based modules | Group by domain: app/auth/, app/contacts/, etc. | ✓ |
| Layer-based structure | Group by type: app/models/, app/routes/, etc. | |
| Flat structure | Everything in app/ with prefixed filenames | |

**User's choice:** Feature-based modules
**Notes:** None

---

| Option | Description | Selected |
|--------|-------------|----------|
| pydantic-settings + .env | Single Settings class, .env locally, env vars in Docker | ✓ |
| Multiple config files | Separate config files per environment | |
| Environment variables only | Raw os.getenv() calls | |

**User's choice:** pydantic-settings + .env
**Notes:** None

---

| Option | Description | Selected |
|--------|-------------|----------|
| Mirror app structure | tests/auth/, tests/contacts/, etc. | ✓ |
| By test type | tests/unit/, tests/integration/, tests/e2e/ | |
| You decide | Claude picks the layout | |

**User's choice:** Mirror app structure
**Notes:** None

---

## Docker & Service Topology

| Option | Description | Selected |
|--------|-------------|----------|
| Include Flower | Add Flower as a service from Phase 1 | ✓ |
| Defer to Phase 3 | Add Flower when enrichment pipeline uses Celery | |
| Never include | Skip Flower, use CLI/Redis monitoring | |

**User's choice:** Include Flower
**Notes:** None

---

| Option | Description | Selected |
|--------|-------------|----------|
| Override files | Base docker-compose.yml + docker-compose.override.yml for dev | ✓ |
| Single compose with profiles | One file using Docker Compose profiles | |
| Separate compose files | Fully independent dev and prod files | |

**User's choice:** Override files
**Notes:** None

---

| Option | Description | Selected |
|--------|-------------|----------|
| Auto-migrate on startup | Run alembic upgrade head in API entrypoint | ✓ |
| Manual migration step | Require manual alembic command before use | |
| Init container | Separate one-shot migration container | |

**User's choice:** Auto-migrate on startup
**Notes:** None

---

| Option | Description | Selected |
|--------|-------------|----------|
| Dedicated /health endpoints | API /health checks DB + Redis, Docker healthcheck hits it | ✓ |
| Docker-level checks only | Use Docker's built-in healthcheck commands only | |
| You decide | Claude picks the approach | |

**User's choice:** Dedicated /health endpoints
**Notes:** None

---

## Claude's Discretion

No areas deferred to Claude's discretion.

## Deferred Ideas

None — discussion stayed within phase scope.
