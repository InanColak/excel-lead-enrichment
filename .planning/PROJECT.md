# LeadEnrich — Apollo-Powered Contact Enrichment Platform

## What This Is

An internal SaaS application that enriches contact data from uploaded Excel files using Apollo's People Enrichment API. Team members upload Excel files containing mixed contact data (names, companies, LinkedIn URLs, partial info), the system auto-detects columns, resolves contacts through a local database first (saving API credits), then calls Apollo for unknowns, and returns enriched Excel files with email addresses and mobile phone numbers appended. All enriched data feeds into a growing contact database that accelerates future lookups.

## Core Value

Every uploaded Excel file comes back with accurate email addresses and phone numbers — without wasting Apollo API credits on data we already have.

## Requirements

### Validated

(None yet — ship to validate)

### Active

- [ ] Upload Excel files with mixed/varying column formats
- [ ] Auto-detect column types (name, company, LinkedIn URL, etc.) with manual override
- [ ] Enrich contacts via Apollo People Enrichment API (email + phone)
- [ ] Local contact database that grows with each enrichment job
- [ ] Database-first lookup before any API call to prevent credit waste
- [ ] Deduplication within a single upload (same person = one API call)
- [ ] Background processing for large files (1,000+ rows)
- [ ] Row-level tracking with unique IDs through the pipeline
- [ ] Job isolation for concurrent multi-user processing
- [ ] Download enriched Excel with original data + email/phone columns appended
- [ ] Job history with full results (re-downloadable)
- [ ] Contact database browser
- [ ] Usage stats dashboard (API credits used, cache hits, jobs run)
- [ ] Simple email/password authentication for the team
- [ ] Admin-managed shared Apollo API key configuration
- [ ] Team management (add/remove users)
- [ ] "Not found" status column for rows Apollo couldn't resolve
- [ ] Force re-enrichment option per job (override database cache)
- [ ] Original uploaded file preserved (never modified)
- [ ] Excel validation on upload (size limits, format checks, graceful bad-row handling)
- [ ] Docker-based deployment

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
| Database-first lookup before API | Prevents duplicate API calls, saves credits, builds reusable contact asset | — Pending |
| Auto-detect + manual override for columns | Handles messy Excel files while giving users control | — Pending |
| Shared Apollo API key (admin-managed) | Simpler for internal team, single billing point | — Pending |
| Row-level unique ID tracking | Prevents data mix-ups in enrichment pipeline | — Pending |
| Job isolation for concurrency | Prevents data corruption when multiple users process simultaneously | — Pending |
| Docker deployment | Portable, consistent environment, deploy anywhere | — Pending |
| API-only, no frontend | This is one of several company apps; a unified dashboard will consume APIs later. Swagger UI for now. | — Pending |
| API gateway pattern for future dashboard | Each app exposes its own REST API; dashboard aggregates. No DB coupling between apps. | — Pending |

## Evolution

This document evolves at phase transitions and milestone boundaries.

**After each phase transition** (via `/gsd-transition`):
1. Requirements invalidated? → Move to Out of Scope with reason
2. Requirements validated? → Move to Validated with phase reference
3. New requirements emerged? → Add to Active
4. Decisions to log? → Add to Key Decisions
5. "What This Is" still accurate? → Update if drifted

**After each milestone** (via `/gsd-complete-milestone`):
1. Full review of all sections
2. Core Value check — still the right priority?
3. Audit Out of Scope — reasons still valid?
4. Update Context with current state

---
*Last updated: 2026-04-06 after initialization*
