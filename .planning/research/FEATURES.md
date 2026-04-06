# Feature Research

**Domain:** Contact enrichment SaaS (internal, Apollo-powered, Excel-based)
**Researched:** 2026-04-06
**Confidence:** MEDIUM — web research tools unavailable; findings drawn from training knowledge of
the B2B enrichment tooling landscape (Apollo, ZoomInfo, Clearbit, Lusha, Hunter.io, Clay,
Kaspr, Datagma) and cross-referenced against the project's stated requirements. Apollo API
capabilities reflect documented knowledge through August 2025.

---

## Feature Landscape

### Table Stakes (Users Expect These)

These are features that any enrichment tool must have. Users who find one missing will either
stop using the tool or work around it manually — both outcomes are failures.

| Feature | Why Expected | Complexity | Notes |
|---------|--------------|------------|-------|
| File upload (Excel/CSV) | Every enrichment workflow starts with a list. No upload = no product. | Low | Must handle .xlsx and .xls; .csv is secondary for this use case |
| Auto-column detection | Uploaded files are inconsistent. Users won't manually map 10 columns every time. | Medium | Heuristics on header names + value sampling; needs manual override fallback |
| Manual column override | Auto-detect fails on ambiguous headers. Users need to correct mistakes. | Low | Simple dropdown UI after detect; required companion to auto-detect |
| Email enrichment output | The primary deliverable. If this doesn't work reliably, nothing else matters. | Low (API call) | Apollo returns verified/unverified flags — surface both |
| Phone enrichment output | The secondary deliverable alongside email. Direct dials are high value. | Low (API call) | Mobile vs. direct dial distinction matters to sales teams |
| "Not found" status | Users need to know which rows failed so they can manually research them. | Low | Must be explicit in output — blank cell is ambiguous, status column is not |
| Download enriched file | Output must mirror input with enrichment columns appended. Users want familiarity. | Low | Preserve all original columns; append email, phone, status at right |
| Original file preserved | Users panic if their source data is modified. Trust is destroyed instantly. | Low | Store original separately; never mutate uploaded file |
| Job status / progress | Large files take time. Users need to know if the job is running, done, or failed. | Medium | Background processing requires polling or websocket status update |
| Job history | "I ran this last Tuesday — where did it go?" is the most common support question. | Low | Persist jobs + results; re-downloadable without re-processing |
| Deduplication within upload | Users don't know their list has duplicates. Billing a credit twice for same person is unacceptable. | Medium | Deduplicate before API dispatch; track within-job identity |
| Authentication | Internal tool, but unauthorized access to contact data is a liability. | Low | Email/password is sufficient; no SSO needed for internal team |
| Graceful error handling | Bad rows, malformed data, and API failures cannot crash the job. | Medium | Per-row error tracking; job must complete even if some rows fail |
| Excel validation on upload | Users upload wrong files, corrupt files, oversized files. Must fail fast with clear message. | Low | Check extension, size limit, sheet structure before accepting |

---

### Differentiators (Competitive Advantage)

These are features that external enrichment tools charge extra for or don't offer. For an
internal tool, "competitive advantage" means the tool gets adopted enthusiastically rather
than tolerated.

| Feature | Value Proposition | Complexity | Notes |
|---------|-------------------|------------|-------|
| Database-first caching (credit shield) | Returning contacts from local DB costs $0 vs. Apollo credits. Teams with growing lists save real money. | High | Core architectural differentiator; requires dedup logic, staleness policy, and cache-hit tracking |
| Cache hit rate visibility | "We saved 847 credits this month" is a compelling justification for the tool's existence. | Low | Requires tracking hits/misses per job; surfaces ROI directly |
| Force re-enrichment override | Contact data goes stale. Users need a way to bypass the cache for specific jobs. | Low | Per-job flag; not per-row — simpler UX, good enough for v1 |
| Contact database browser | The growing contact DB becomes a standalone asset. Teams can search it independently. | Medium | Search by name, company, email domain; basic filtering |
| Usage stats dashboard | Apollo credits are a shared, finite resource. Teams need to see who's using what. | Medium | Credits used, cache hits, jobs per user, trend over time |
| Per-job breakdown in history | "Why did this job use 300 credits?" requires per-job metrics, not just totals. | Low | Store hit/miss counts per job at completion |
| Admin API key management | One admin configures the Apollo key; team members never see it. Clean separation. | Low | Single env-var or DB config; UI to update without redeployment |
| Team management (add/remove users) | Internal tool grows as team grows. Needing a developer to add a new user is friction. | Low | Admin-only: invite by email, deactivate user, no self-registration |
| Concurrent job isolation | Multiple team members processing simultaneously without corrupting each other's results. | High | Per-job queue, no shared mutable state; requires background job architecture |
| Row-level unique ID tracking | Prevents the nightmare of enriched data landing in wrong rows, especially after retries. | Medium | UUID assigned at parse time; tracked through entire pipeline |
| LinkedIn URL as enrichment input | Apollo can resolve contacts from LinkedIn URLs — users often have these from Sales Navigator. | Low (API support) | Apollo People Enrichment accepts linkedin_url as an identifier |

---

### Anti-Features (Commonly Requested, Often Problematic)

These are things users will ask for. Building them for this tool is the wrong call — either
because the scope bloat outweighs the value, the project has explicitly ruled them out, or
they introduce complexity that undermines the core use case.

| Anti-Feature | Why Avoid | What to Do Instead |
|--------------|-----------|-------------------|
| CRM sync (HubSpot / Salesforce push) | Transforms a simple enrichment tool into an integration platform. Webhook reliability, auth token management, and field mapping become the product. | Download enriched Excel; let users import manually via their CRM's native Excel import |
| OAuth / SSO integration | No meaningful security uplift for a small internal team. Adds provider dependencies and token refresh complexity. | Email/password with bcrypt; session-based auth is sufficient |
| Per-user Apollo API keys | Requires each user to have an Apollo account. Billing splits across individuals. Defeats the shared-credit-pool model. | Single admin-managed key; usage dashboard makes per-user consumption visible without separate billing |
| Multiple enrichment providers (Hunter, Clearbit, etc.) | Multi-provider routing logic is a product in itself. Match quality, fallback chains, and cost per source become a research project. | Apollo only for v1; if Apollo match rate proves insufficient, revisit in v2 with evidence |
| Real-time enrichment (paste-in a contact, get instant results) | Requires a different UX paradigm (form vs. file), different API usage pattern, and separate rate-limit handling. | Batch file upload is the primary workflow; real-time is a separate feature with separate design |
| Enrichment beyond email + phone | Job title, company details, social profiles are nice-to-have but double the output complexity and column management. | Scope to email + phone + "not found" status only; add fields if user research validates demand |
| Scheduled / recurring enrichment jobs | Requires job scheduling, stored file references, and "what changed" diffing. | Users manually re-upload when they have a new list; sufficient for current workflow |
| Public self-registration | Internal tool. Unapproved users accessing contact data is a compliance risk. | Admin-managed invites only; no public signup flow |
| Mobile app | File-based workflows are desktop-native. Download-and-upload is not a mobile use case. | Web-only; responsive enough to work on a tablet if needed |
| In-app contact editing | Turning the output DB into an editable CRM is a different product. | Read-only contact browser; edits happen in the downloaded Excel or via re-enrichment |
| Webhook / API exposure | External consumers require auth design, versioning, and documentation. | Internal UI only in v1 |

---

## Feature Dependencies

```
Authentication
  └── Team Management (requires users to exist)
        └── Admin API Key Config (admin role required)
              └── Apollo API integration (key must exist before any enrichment)

File Upload + Validation
  └── Column Auto-Detection
        └── Manual Column Override
              └── Deduplication within upload
                    └── Row-level UUID tracking
                          └── Background Job Processing
                                ├── Job Status / Progress
                                ├── Per-job credit tracking (hits + misses)
                                └── Database-first cache lookup
                                      ├── Apollo API call (cache miss only)
                                      │     └── Contact DB write (new results)
                                      └── Cache hit counter
                                            └── Usage Stats Dashboard

Job completion
  ├── Download enriched file
  ├── Job History (re-downloadable)
  └── Per-job metrics (credits used, hits, misses)

Contact DB (grows with each enrichment)
  └── Contact Database Browser
        └── Cache hit rate visibility (requires DB + job metrics)
```

**Critical path for any enrichment to work:**
Auth → API Key → Upload → Detection → UUID tracking → Cache lookup → API call → Download

**Secondary path (trust/visibility features):**
Job metrics → Usage dashboard → Cache hit visibility → ROI justification

---

## MVP Definition

### Launch With (v1)

These cover the full enrichment workflow end-to-end. Without any of these, the tool doesn't
deliver its core value.

- File upload with Excel validation (size, format, graceful bad-row handling)
- Auto column detection with manual override
- Row-level UUID tracking through the entire pipeline
- Deduplication within a single upload
- Database-first lookup before any Apollo API call
- Apollo People Enrichment API call for cache misses
- Contact database write on new results
- "Not found" status column in output
- Background processing for large files (1,000+ rows)
- Job status/progress indicator
- Job isolation for concurrent users
- Download enriched Excel (original columns + email + phone + status)
- Original uploaded file preserved
- Job history with re-download
- Simple email/password authentication
- Admin-managed Apollo API key
- Team management (add/remove users)

**Also launch with (high value, low effort):**
- Force re-enrichment per job (cache bypass flag)
- Per-job credit usage tracked (hits, misses, API calls)
- Usage stats dashboard (credits used, cache hit rate, jobs run)

### Add After Validation (v1.x)

Add these once v1 is live and the team is using it. They require v1 data to be useful.

- Contact database browser (search by name, company, email domain)
- Cache hit rate trend over time (requires accumulated job history)
- Per-user usage breakdown in dashboard
- Export contact DB as Excel/CSV snapshot

### Future Consideration (v2+)

Revisit only if user feedback or usage data provides a strong signal.

- Additional enrichment fields (job title, company, LinkedIn URL) — if Apollo match rate
  conversations shift
- Multi-provider fallback (if Apollo miss rate proves unacceptably high with evidence)
- Scheduled / recurring enrichment jobs
- Bulk re-enrichment of stale contacts from the DB

---

## Feature Prioritization Matrix

| Feature | User Impact | Build Effort | Risk if Missing | Priority |
|---------|-------------|--------------|-----------------|----------|
| File upload + validation | Critical | Low | Tool unusable | P0 |
| Column auto-detection | Critical | Medium | Tool unusable | P0 |
| Manual column override | High | Low | Blocking for edge cases | P0 |
| Row-level UUID tracking | Critical | Medium | Data corruption | P0 |
| Deduplication | High | Medium | Credit waste, user frustration | P0 |
| DB-first cache lookup | Critical | High | Credit cost uncontrolled | P0 |
| Apollo API enrichment | Critical | Medium | Tool unusable | P0 |
| Contact DB write | Critical | Low | Cache never grows | P0 |
| Download enriched file | Critical | Low | No output = no value | P0 |
| Original file preserved | High | Low | User trust destroyed | P0 |
| "Not found" status column | High | Low | Output ambiguous | P0 |
| Background processing | High | Medium | Large files time out | P0 |
| Job status/progress | High | Medium | Users abandon job | P0 |
| Job isolation (concurrency) | Critical | High | Data corruption at scale | P0 |
| Authentication | Critical | Low | Security/compliance risk | P0 |
| Admin API key management | High | Low | Blocks all enrichment | P0 |
| Team management | Medium | Low | Friction to onboard users | P0 |
| Job history + re-download | High | Low | Users repeat work | P0 |
| Force re-enrichment override | Medium | Low | Stale data no escape | P1 |
| Usage stats dashboard | Medium | Medium | No ROI visibility | P1 |
| Per-job credit tracking | Medium | Low | Dashboard impossible | P1 |
| Contact database browser | Low | Medium | DB is black box | P2 |
| Cache hit rate trend | Low | Low | Nice to have | P2 |
| Per-user usage breakdown | Low | Low | Nice to have | P2 |
| Export contact DB snapshot | Low | Low | Nice to have | P2 |

**P0** = Required for v1 launch. Tool fails without it.
**P1** = High value, launch with if effort fits. Add immediately after if not.
**P2** = Post-validation. Requires v1 data to be useful anyway.

---

## Notes on Apollo API Capabilities

The following is based on training knowledge through August 2025 — verify against current
Apollo docs before building.

Apollo's People Enrichment endpoint accepts these identifiers (and resolves with partial input):
- First name + last name + company name
- First name + last name + company domain
- LinkedIn URL
- Email address (reverse lookup)

It returns: verified email, phone numbers (mobile/direct), job title, company, seniority,
LinkedIn URL, location, and other firmographic fields.

For this project, the output scope is intentionally constrained to email + phone + status.
The API will return more — the system should store everything returned (or at least the
structured fields) into the contact DB for future extensibility, even if the output Excel
only exposes email + phone today.

**Confidence:** MEDIUM — Apollo API shape is unlikely to have changed fundamentally, but
field names, match rate by identifier type, and rate limits should be verified against current
Apollo API documentation before building the enrichment pipeline.

---

## Sources

- Training knowledge: Apollo.io, ZoomInfo, Clearbit (now HubSpot), Lusha, Clay, Hunter.io,
  Kaspr, Datagma product feature sets as of August 2025 — **MEDIUM confidence**
- Project requirements in `.planning/PROJECT.md` — **HIGH confidence** (authoritative)
- Web research tools (WebSearch, WebFetch) were unavailable during this research session.
  Recommend verifying Apollo People Enrichment API response shape and rate limits against
  current documentation at https://docs.apollo.io before building the enrichment pipeline.
- No external URLs verified during this session due to tool availability constraints.
