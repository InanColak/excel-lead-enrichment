# Requirements: LeadEnrich

**Defined:** 2026-04-06
**Core Value:** Every uploaded Excel file comes back with accurate email addresses and phone numbers — without wasting Apollo API credits on data we already have.

## v1 Requirements

Requirements for initial release. Each maps to roadmap phases.

### File Processing

- [ ] **FILE-01**: User can upload Excel files (.xlsx/.xls) via the REST API
- [ ] **FILE-02**: System validates uploaded file on receipt (format, size limit, sheet structure) and rejects invalid files with clear error messages
- [ ] **FILE-03**: System auto-detects column types (first name, last name, company, LinkedIn URL, email) from headers and content sampling
- [ ] **FILE-04**: User can review and override auto-detected column mappings via API before enrichment starts
- [ ] **FILE-05**: System handles bad/malformed rows gracefully without failing the entire job (per-row error tracking)

### Enrichment Pipeline

- [ ] **ENRICH-01**: System assigns a unique UUID to each row at parse time, tracked through the entire pipeline
- [ ] **ENRICH-02**: System deduplicates contacts within a single upload (same person = one API call, result fanned to all matching rows)
- [ ] **ENRICH-03**: System checks local contact database first before making any Apollo API call
- [ ] **ENRICH-04**: System calls Apollo People Enrichment API for contacts not found in local database, returning email and phone number
- [ ] **ENRICH-05**: System stores all Apollo enrichment results in the local contact database for future lookups
- [ ] **ENRICH-06**: System marks rows where Apollo returns no match with a "not found" status column
- [ ] **ENRICH-07**: System processes large files (1,000+ rows) as background jobs with progress tracking
- [ ] **ENRICH-08**: System isolates concurrent jobs so multiple users can process simultaneously without data corruption
- [ ] **ENRICH-09**: System preserves the original uploaded file (never modified)
- [ ] **ENRICH-10**: System tracks per-job metrics (cache hits, cache misses, API calls made, credits consumed)

### Output & History

- [ ] **OUTPUT-01**: User can download enriched Excel file with original columns plus email, phone, and status columns appended
- [ ] **OUTPUT-02**: User can query real-time job status and progress via API endpoint
- [ ] **OUTPUT-03**: User can list job history and re-download results from any past enrichment job via API

### Authentication & Admin

- [ ] **AUTH-01**: User can log in with email and password
- [ ] **AUTH-02**: Admin can configure the shared Apollo API key via API endpoint (without redeployment)
- [ ] **AUTH-03**: Admin can add and remove team members
- [ ] **AUTH-04**: User can query usage stats via API (credits used, cache hit rate, jobs run over time)

### Infrastructure

- [ ] **INFRA-01**: Application runs as a Docker Compose deployment (API, worker, database, queue)
- [ ] **INFRA-02**: API auto-generates interactive Swagger UI documentation for all endpoints
- [ ] **INFRA-03**: API is designed for future integration with a unified company dashboard via API gateway pattern

## v2 Requirements

Deferred to future release. Tracked but not in current roadmap.

### Contact Management

- **CONTACT-01**: User can browse the contact database (search by name, company, email domain)
- **CONTACT-02**: User can export the contact database as an Excel/CSV snapshot
- **CONTACT-03**: User can view cache hit rate trends over time

### Advanced Admin

- **ADMIN-01**: Admin can view per-user usage breakdown in the dashboard
- **ADMIN-02**: User can force re-enrichment on a job (bypass database cache)

### Extended Enrichment

- **EXTEND-01**: System returns additional enrichment fields (job title, company details, LinkedIn URL)
- **EXTEND-02**: System supports multiple enrichment providers with fallback chains

## Out of Scope

Explicitly excluded. Documented to prevent scope creep.

| Feature | Reason |
|---------|--------|
| CRM sync (HubSpot, Salesforce) | Transforms enrichment tool into integration platform; Excel download + manual import is sufficient |
| OAuth / SSO | No security uplift for small internal team; adds provider dependencies |
| Per-user Apollo API keys | Defeats shared credit pool model; usage dashboard provides visibility instead |
| Real-time single-contact enrichment | Different UX paradigm; batch file upload is the primary workflow |
| Scheduled / recurring enrichment | Requires job scheduling and diff logic; manual re-upload is sufficient |
| Mobile app | File-based workflows are desktop-native |
| Public self-registration | Internal tool; admin-managed invites only |
| In-app contact editing | Read-only contact browser; edits happen in downloaded Excel |
| Standalone frontend | No dedicated UI — API-first with Swagger UI; future unified dashboard will consume API |

## Traceability

Which phases cover which requirements. Updated during roadmap creation.

| Requirement | Phase | Status |
|-------------|-------|--------|
| FILE-01 | — | Pending |
| FILE-02 | — | Pending |
| FILE-03 | — | Pending |
| FILE-04 | — | Pending |
| FILE-05 | — | Pending |
| ENRICH-01 | — | Pending |
| ENRICH-02 | — | Pending |
| ENRICH-03 | — | Pending |
| ENRICH-04 | — | Pending |
| ENRICH-05 | — | Pending |
| ENRICH-06 | — | Pending |
| ENRICH-07 | — | Pending |
| ENRICH-08 | — | Pending |
| ENRICH-09 | — | Pending |
| ENRICH-10 | — | Pending |
| OUTPUT-01 | — | Pending |
| OUTPUT-02 | — | Pending |
| OUTPUT-03 | — | Pending |
| AUTH-01 | — | Pending |
| AUTH-02 | — | Pending |
| AUTH-03 | — | Pending |
| AUTH-04 | — | Pending |
| INFRA-01 | — | Pending |
| INFRA-02 | — | Pending |
| INFRA-03 | — | Pending |

**Coverage:**
- v1 requirements: 25 total
- Mapped to phases: 0
- Unmapped: 25

---
*Requirements defined: 2026-04-06*
*Last updated: 2026-04-06 after initial definition*
