# LeadEnrich — Apollo-Powered Contact Enrichment Platform

## What This Is

An internal SaaS application that enriches contact data from uploaded Excel files using Apollo's People Enrichment API. Team members upload Excel files containing mixed contact data (names, companies, LinkedIn URLs, partial info), the system auto-detects columns, resolves contacts through a local database first (saving API credits), then calls Apollo for unknowns, and returns enriched Excel files with email addresses and mobile phone numbers appended. All enriched data feeds into a growing contact database that accelerates future lookups.

## Core Value

Every uploaded Excel file comes back with accurate email addresses and phone numbers — without wasting Apollo API credits on data we already have.

## Current State

**v1.0 shipped on 2026-04-07.** The full enrichment platform is operational:

- Docker Compose deployment (API + Celery worker + PostgreSQL + Redis + Flower)
- JWT authentication with admin user management
- Excel upload with auto-detection of 8 column types and manual override
- Background enrichment pipeline: DB-first cache, Apollo API with retry, dedup within uploads
- Two-stage enrichment: email via API response, phone via Apollo webhook with timeout fallback
- Job status polling, paginated history, enriched file download, usage stats dashboard
- 150 integration tests, 27 requirements satisfied, 79 code files, 7,434 LOC

**API endpoints available via Swagger UI at** `http://localhost:8000/docs`

## Next Milestone Goals

Candidates for v2 (not yet planned — run `/gsd-new-milestone` to start):

- Contact database browser (search by name, company, email domain)
- Force re-enrichment option per job (bypass cache)
- Per-user usage breakdown for admins
- Contact database export (Excel/CSV snapshot)
- Cache hit rate trends over time

## Requirements

### Validated (v1.0 — archived)

All 27 v1 requirements shipped. See [v1.0 requirements archive](milestones/v1.0-REQUIREMENTS.md).

### Active

- [ ] Contact database browser
- [ ] Force re-enrichment option per job (override database cache)

### Out of Scope

- OAuth/SSO integration — simple login is sufficient for internal team
- Per-user Apollo API keys — shared team key is simpler
- Additional enrichment sources (Hunter, Clearbit, etc.) — Apollo only for v1
- Enrichment beyond email + phone (job title, company details, LinkedIn URL)
- CRM integration (HubSpot, Salesforce push) — download Excel is the output
- Real-time/streaming enrichment — batch processing via file upload
- Mobile app — web only

## Context

- Internal tool for a sales/marketing team
- Excel files have inconsistent column formats — the system must be smart about detection
- Large files (1,000+ rows) are common, requiring background job processing
- Apollo API credits are a real cost concern — the local database serves as both a growing contact asset and a credit-saving mechanism
- Multiple team members may run enrichment jobs simultaneously

## Constraints

- **API**: Apollo People Enrichment API is the sole data source — must handle rate limits, downtime, and credit budgets
- **Data Integrity**: Results must never be written to wrong rows — row-level unique ID tracking is mandatory
- **Concurrency**: Multi-user simultaneous processing must be isolated — no shared mutable state between jobs
- **File Handling**: Original uploads must be preserved; enrichment results stored in DB before generating output
- **Deployment**: Docker-based, must be self-contained and deployable anywhere

## Key Decisions

| Decision | Rationale | Outcome |
|----------|-----------|---------|
| Database-first lookup before API | Prevents duplicate API calls, saves credits, builds reusable contact asset | Shipped v1.0 |
| Auto-detect + manual override for columns | Handles messy Excel files while giving users control | Shipped v1.0 |
| Shared Apollo API key (admin-managed) | Simpler for internal team, single billing point | Shipped v1.0 |
| Row-level unique ID tracking | Prevents data mix-ups in enrichment pipeline | Shipped v1.0 |
| Job isolation for concurrency | Prevents data corruption when multiple users process simultaneously | Shipped v1.0 |
| Docker deployment | Portable, consistent environment, deploy anywhere | Shipped v1.0 |
| API-only, no frontend | This is one of several company apps; a unified dashboard will consume APIs later. Swagger UI for now. | Shipped v1.0 |
| API gateway pattern for future dashboard | Each app exposes its own REST API; dashboard aggregates. No DB coupling between apps. | Shipped v1.0 |
| pwdlib[bcrypt] + PyJWT over passlib + python-jose | Research found more actively maintained alternatives | Shipped v1.0 |
| Apollo webhook for phone data | Apollo delivers phone numbers asynchronously; pipeline has two-stage design with timeout | Shipped v1.0 |

## Evolution

This document evolves at phase transitions and milestone boundaries.

**After each phase transition** (via `/gsd-transition`):
1. Requirements invalidated? -> Move to Out of Scope with reason
2. Requirements validated? -> Move to Validated with phase reference
3. New requirements emerged? -> Add to Active
4. Decisions to log? -> Add to Key Decisions
5. "What This Is" still accurate? -> Update if drifted

**After each milestone** (via `/gsd-complete-milestone`):
1. Full review of all sections
2. Core Value check — still the right priority?
3. Audit Out of Scope — reasons still valid?
4. Update Context with current state

---
*Last updated: 2026-04-07 — v1.0 milestone completed*
