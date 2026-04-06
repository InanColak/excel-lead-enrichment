# Phase 1: Foundation - Context

**Gathered:** 2026-04-06
**Status:** Ready for planning

<domain>
## Phase Boundary

Deliver the running application skeleton: Docker infrastructure with all services, PostgreSQL database with Phase 1 schema (users, contacts, api_config), JWT authentication with token refresh and revocation, admin bootstrap, Apollo API key configuration, and team management. This phase produces a working API with Swagger UI that can authenticate users and manage the team — the base everything else builds on.

</domain>

<decisions>
## Implementation Decisions

### Database Schema Design
- **D-01:** Store raw Apollo API responses as a JSONB column alongside extracted email/phone columns. JSONB is internal storage only — the enriched Excel output only shows email, phone, and status columns. JSONB preserves the full response for future field extraction (v2 requirements).
- **D-02:** Email address is the UNIQUE constraint for contact deduplication. Simple and effective for v1.
- **D-03:** Phase 1 creates only the tables it needs: users, contacts, and api_config. Future phases add their own tables via Alembic migrations. No premature schema.
- **D-04:** UUID primary keys on all tables. Consistent across the entire project, aligns with the row-UUID tracking requirement (ENRICH-01).

### Auth & Token Strategy
- **D-05:** Short-lived access tokens (30 min) with long-lived refresh tokens (7 days). Standard JWT security pattern.
- **D-06:** First admin user created via CLI seed command (e.g., `python manage.py create-admin`). Credentials sourced from environment variables. Clean separation from the API.
- **D-07:** Token revocation via Redis blocklist. When an admin removes a user, their active token JTIs are added to a Redis blocklist. Every request checks the blocklist. TTL auto-cleans expired entries.
- **D-08:** Simple `is_admin` boolean flag on the user table. Admin = manage users + API key config. Non-admin = everything else. No role/permission tables needed for v1.

### Project Structure
- **D-09:** Feature-based module layout: `app/auth/`, `app/contacts/`, `app/admin/`, `app/jobs/`. Each module contains its own routes, models, schemas, and services.
- **D-10:** Configuration via pydantic-settings + `.env` file. Single Settings class reads from `.env` locally and environment variables in Docker. Type-validated.
- **D-11:** Test directory mirrors app structure: `tests/auth/`, `tests/contacts/`, `tests/admin/`, etc.

### Docker & Service Topology
- **D-12:** Include Flower (Celery monitoring UI) in docker-compose.yml from Phase 1. Useful for debugging worker status even before enrichment tasks exist.
- **D-13:** Dev/prod split via Docker Compose override files. Base `docker-compose.yml` for production, `docker-compose.override.yml` for dev extras (volume mounts, debug ports, hot reload).
- **D-14:** Auto-migrate on startup. API container entrypoint runs `alembic upgrade head` before starting the server. Zero manual steps after `docker compose up`.
- **D-15:** Dedicated `/health` endpoint on the API that checks DB + Redis connectivity. Docker Compose healthcheck hits this endpoint. Other services use native health checks (`pg_isready`, `redis-cli ping`).

### Claude's Discretion
No areas deferred to Claude's discretion — all gray areas were decided by the user.

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Project Definition
- `.planning/PROJECT.md` — Core value, requirements list, constraints, key decisions
- `.planning/REQUIREMENTS.md` — Full v1 requirement definitions with IDs (AUTH-01 through AUTH-03, INFRA-01 through INFRA-03 for this phase)
- `.planning/ROADMAP.md` — Phase 1 goal, success criteria, and dependency chain

### Technology Stack
- `CLAUDE.md` §Technology Stack — Full stack specification including versions, alternatives considered, and what NOT to use

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- None — this is a greenfield project. Phase 1 establishes all foundational code.

### Established Patterns
- None yet — Phase 1 will establish the patterns (module structure, config management, testing approach) that all subsequent phases follow.

### Integration Points
- None — Phase 1 is the base. Future phases connect to the auth system, database, and Docker infrastructure established here.

</code_context>

<specifics>
## Specific Ideas

- User clarified that JSONB storage is purely internal — the enriched Excel output should only contain email, phone, and status columns. Users should never see raw Apollo response data.

</specifics>

<deferred>
## Deferred Ideas

None — discussion stayed within phase scope.

</deferred>

---

*Phase: 01-foundation*
*Context gathered: 2026-04-06*
