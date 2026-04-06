# Project Research Summary

**Project:** LeadEnrich — Apollo-Powered Contact Enrichment Platform
**Domain:** Contact enrichment SaaS (Apollo API + Excel processing)
**Researched:** 2026-04-06
**Confidence:** MEDIUM

## Executive Summary

LeadEnrich is a batch contact enrichment tool built for an internal sales/marketing team. It takes Excel files with inconsistent column structures, auto-detects and maps contact fields, runs those contacts through a local database cache first to avoid burning Apollo API credits, and falls back to Apollo's People Enrichment API only for cache misses. The output is the original Excel file with email, phone, and status columns appended. The growing contact database becomes a strategic asset over time — as cache hit rates climb, per-job credit costs fall. Expert implementations of this class of system all share one structural commitment: background job processing via a durable queue (Celery + Redis in this stack) is non-negotiable for any file above ~50 rows, and all enrichment logic lives in the worker, never in the web server request cycle.

The recommended implementation is a Python/FastAPI web server paired with a Celery worker, both sharing a PostgreSQL database and a Redis broker, served to a React + Vite frontend. The architecture separates concerns cleanly: the web server handles uploads, job creation, and status/download serving; workers handle the enrichment pipeline end-to-end. Three architectural commitments must be made before writing a single line of enrichment code — row-level UUID tracking, job-scoped isolation (no shared mutable state between jobs), and original file immutability. These cannot be retrofitted cheaply; they must be designed in from the start.

The primary risks are data integrity failures (wrong emails in wrong rows due to index-based joins instead of UUID-based joins), credit waste (cache normalization gaps and missing intra-job deduplication), and Excel parsing failures from real-world file quirks (merged cells, trailing empty rows, formula cells). All three are preventable with known patterns documented in the research — but each must be addressed in the phase where the relevant component is first built, not as a retrofit. Apollo API specifics (exact rate limits, credit billing model for no-match responses, current endpoint URLs, required request flags) carry MEDIUM/LOW confidence and must be verified against current Apollo documentation before the enrichment client is implemented.

---

## Key Findings

### Recommended Stack (from STACK.md)

The stack is a well-integrated Python-first backend with a lightweight React frontend, all orchestrated via Docker Compose. FastAPI (confirmed at 0.135.3 as of 2026-04-06) provides async-native API handling with automatic validation. Celery 5.4.x over Redis 7.x handles background job processing — this pairing is the only correct choice for 1,000+ row files; FastAPI's built-in `BackgroundTasks` runs in-process and will block under load. PostgreSQL 16 provides relational integrity for deduplication (UNIQUE constraints on contact identifiers) and JSONB storage for raw Apollo responses. SQLAlchemy 2.x async engine is required — the 1.x API is legacy and must not be used. All version confidence is MEDIUM except FastAPI (HIGH, confirmed) and `uv` as package manager (HIGH, 1.0 since mid-2024).

**Core technologies:**
- Python 3.12 + FastAPI 0.135.x: async API server with automatic OpenAPI docs and Pydantic v2 validation
- Celery 5.4.x + Redis 7.x: background job queue and broker — mandatory for large-file processing, provides retry logic and task state persistence
- PostgreSQL 16 + SQLAlchemy 2.x async + Alembic 1.13.x: primary database with async ORM and migration support
- openpyxl 3.1.x: Excel read/write in `read_only` mode for memory-efficient streaming of large files
- httpx 0.27.x + tenacity 8.x: async Apollo API client with declarative exponential-backoff retry
- React 18.x + Vite 5.x: frontend SPA — no SSR needed for an internal tool
- Docker Compose 2.x: single-file deployment orchestration for all services (api, worker, db, redis, flower)

**What not to use:** FastAPI `BackgroundTasks` for enrichment (in-process, no retry), `requests` (sync, blocks async loop), `xlrd`/`xlwt` (no .xlsx write support), SQLite (concurrent write contention), pandas as the primary pipeline tool (memory overhead; use only for column type detection heuristics).

### Expected Features (from FEATURES.md)

The feature research identifies a clear critical path: Auth → API Key Config → Upload → Column Detection/Confirmation → UUID Tracking → Dedup → Cache Lookup → Apollo API → Download. Every feature in that chain is a P0 blocker; removing any one of them means the tool does not deliver its core value. The database-first cache is the primary differentiator — returning enriched contacts from local DB costs zero credits, and the ROI compounds as the contact database grows.

**Must have (table stakes — P0):**
- File upload with Excel validation (size, format, bad-row handling, graceful error reporting)
- Auto column detection with manual override — required companion pair; auto-detect alone is unusable
- Row-level UUID tracking through the entire pipeline — data integrity requirement, not a feature
- Intra-job deduplication before cache lookup — same person = one API call per job
- Database-first lookup (cache-aside pattern) before any Apollo call
- Apollo People Enrichment API call for cache misses, with per-row result storage
- "Not found" / "Skipped" / "Error" status column in output — blank cells are ambiguous
- Background processing + job status/progress polling
- Job isolation for concurrent multi-user processing
- Download enriched Excel (original columns preserved, email/phone/status appended)
- Original file preserved and never modified
- Job history with re-download (minimum 30 days)
- Email/password authentication, admin-managed Apollo API key, team management

**Should have (high value, low effort — launch with if possible):**
- Force re-enrichment per job (cache bypass flag)
- Per-job credit tracking (hits, misses, API calls) — prerequisite for the dashboard
- Usage stats dashboard (credits used, cache hit rate, jobs run)

**Defer (v1.x — post-launch, requires accumulated data):**
- Contact database browser (search by name, company, email domain)
- Cache hit rate trend over time
- Per-user usage breakdown
- Export contact DB snapshot

**Anti-features (do not build):** CRM sync, OAuth/SSO, per-user Apollo keys, multi-provider routing, real-time enrichment, scheduled recurring jobs, in-app contact editing, public self-registration.

### Architecture Approach (from ARCHITECTURE.md)

The architecture is a producer/consumer system with clear boundary enforcement. The web server is a pure producer: it accepts uploads, validates files, detects columns, creates job records, enqueues tasks to Celery/Redis, and serves status/downloads. It never calls Apollo. Workers are pure consumers: they execute the enrichment pipeline (parse → dedupe → cache lookup → API call → DB write → output assembly) and never serve HTTP. PostgreSQL is shared between web server (reads) and workers (reads and writes). A shared Docker volume mounts `/uploads/{job_id}/original.xlsx` (immutable) and `/outputs/{job_id}/enriched.xlsx` (generated by worker at job completion).

**Major components:**
1. Web Server (FastAPI): upload handling, job lifecycle management, auth middleware, download serving, admin and contact browser routes
2. Job Queue (Celery + Redis): durable task storage, worker dispatch, progress tracking, retry logic, concurrency control — sits between web server and workers; web server is producer only
3. Worker Process (Celery worker): the enrichment pipeline — Excel parse, UUID assignment, intra-job dedup, canonical key construction, DB lookup, Apollo API call, result write, output Excel generation
4. Contact Database (PostgreSQL — `contacts` table): growing append-on-new asset; indexed on `linkedin_url`, `email`, `(first_name, last_name, company)`; surrogate UUID primary key, natural keys as UNIQUE indexed columns
5. Job Store (PostgreSQL — `jobs` + `job_rows` tables): job lifecycle state, per-row results keyed by row UUID, credit usage counters
6. File Store (Docker volumes): `/uploads/` immutable originals, `/outputs/` generated enriched files — both mounted to web server and worker containers
7. Apollo API Client (httpx + tenacity): thin, rate-limit-aware HTTP client instantiated per job or per worker; exponential backoff on 429; reads API key from DB at job start
8. Auth Layer (passlib[bcrypt] + python-jose): email/password with JWT (HS256); admin role gates API key config and user management

**Key patterns:** Cache-aside for DB-first lookup; row UUID as the integrity anchor; intra-job dedup by canonical key before queue dispatch; job-scoped state (all worker state in DB by job_id, no module-level mutable objects); output assembled from `job_rows` table, never from the original workbook object.

### Critical Pitfalls (top 5 from PITFALLS.md)

1. **Row identity lost in the pipeline (silent data corruption)** — Assign a UUID to every row at parse time, before any filtering or deduplication. This UUID is the join key for all result writes. Never use array index past the parse step. Retrofitting this after the pipeline is built requires rewriting the entire worker architecture.

2. **Cache key normalization gaps causing credit waste** — Normalize all lookup keys at parse time: lowercase, strip whitespace, strip URL schemes and trailing slashes from LinkedIn URLs. Build the canonical key map before dedup, and dedup before cache lookup. Use `INSERT ... ON CONFLICT` upserts to handle concurrent jobs writing the same new contact idempotently. A 10% normalization gap on a 1,000-row file with 200 duplicates wastes 40+ credits per job.

3. **Shared mutable state between concurrent jobs** — No module-level mutable structures in workers. Every queue item carries its `job_id` as payload. All results are written to the DB keyed by `job_id`, not accumulated in memory. Two simultaneous jobs share only the `contacts` table (write-safe via upsert) — no other shared state.

4. **Excel parsing failures from real-world file quirks** — Strip trailing empty rows before processing. Detect and reject merged header cells. Convert all cell values to strings before downstream processing. Use `data_only=True` in openpyxl to read formula results. Set explicit upload limits (max 10,000 rows or 50MB). Log a parse summary with confidence scores per detected column. Test against a diverse set of real export files (HubSpot, LinkedIn Sales Navigator, manual entry, legacy CRM), not just a clean test file.

5. **Apollo API behavioral assumptions unverified** — Three specific gotchas require verification before building the API client: (a) `reveal_personal_emails: true` and `reveal_phone_number: true` must be set in every request or the API silently omits those fields; (b) credits may be charged on well-formed "not found" responses, not just successful matches — pre-flight row eligibility validation (name + company or LinkedIn URL required) prevents billing for unresolvable rows; (c) Apollo 429 (rate limit) must trigger exponential backoff retry, not job failure or silent "not found" marking. Current rate limit thresholds, endpoint URLs, and billing model for no-match responses carry LOW confidence and must be verified against current Apollo documentation.

---

## Implications for Roadmap

Based on the combined dependency graph from FEATURES.md and the build order from ARCHITECTURE.md, a 5-phase structure is recommended.

### Phase 1: Foundation — Database, Auth, and Project Infrastructure

**Rationale:** Everything else depends on the database schema and auth layer existing. The schema decisions made here (row UUID, surrogate primary keys on contacts, `job_rows` table, UNIQUE constraints) cannot be changed cheaply after data exists. Auth gates all routes. Docker Compose wiring should be established early so the development environment matches production from day one.

**Delivers:** Working Docker Compose environment (api, worker, db, redis, flower); database schema with all tables; Alembic migration baseline; email/password auth with JWT; admin and user role enforcement; team management (add/remove users); admin Apollo API key configuration UI.

**Addresses:** Authentication (P0), admin API key management (P0), team management (P0), Docker deployment constraint.

**Avoids:** Pitfall 8 (deduplication key collision) — surrogate UUID primary key and natural key UNIQUE constraints must be in schema before any data is written. Schema changes after data exists are costly migrations.

**Research flag:** Standard patterns — auth with passlib + python-jose is well-documented; no phase research needed.

---

### Phase 2: File Ingestion and Column Detection

**Rationale:** The enrichment pipeline cannot exist without valid parsed input. The file ingestion layer establishes the row UUID, the column map, and the storage architecture (original file immutability). These decisions must be locked before the worker pipeline is built. Getting the parser right with real-world Excel files is harder than it looks and must be tested against diverse file formats before moving on.

**Delivers:** File upload endpoint with validation (size, format, extension, row limit); openpyxl-based parser with empty-row stripping, merged-cell detection, formula-cell warning, string coercion; column auto-detection via header alias matching with confidence scores; manual column override UI; row UUID assignment at parse time; original file stored to `/uploads/{job_id}/original.xlsx` (immutable); job record created with `PENDING_CONFIRMATION` status; column map confirmation step before processing begins.

**Addresses:** File upload + validation (P0), auto column detection (P0), manual column override (P0), row-level UUID tracking (P0), original file preserved (P0), Excel validation (P0).

**Avoids:** Pitfall 1 (row identity lost) — UUIDs assigned here, before dedup or queuing. Pitfall 4 (Excel parsing failures) — empty rows, merged cells, formulas handled here. Pitfall 7 (original file overwritten) — storage architecture established here.

**Research flag:** Standard patterns for openpyxl and file handling — no phase research needed. Recommend testing with 5+ diverse real export files before marking complete.

---

### Phase 3: Enrichment Pipeline (Core Value Delivery)

**Rationale:** This is the highest-risk phase and the core of the product. It wires together Celery, the DB-first cache, Apollo API integration, intra-job deduplication, and output file generation. All pitfall mitigations that cannot be retrofitted (row UUID join key, no shared mutable state, cache normalization, retry logic) must be implemented here — they cannot be added in a later phase without architectural rewrites. This phase should be treated as requiring the most careful implementation and the most thorough testing before moving on.

**Delivers:** Celery worker infrastructure with job dispatch; intra-job deduplication by normalized canonical key (linkedin_url preferred, else name+company); DB-first cache lookup with normalized key matching; Apollo People Enrichment API client (httpx + tenacity) with exponential backoff on 429, 402/403 admin alert, `reveal_personal_emails` and `reveal_phone_number` flags, LinkedIn URL normalization; pre-flight row eligibility validation (skip unresolvable rows); per-row result write to `job_rows` table keyed by UUID; output Excel assembly from `job_rows` sorted by `row_index` (original order preserved); "Not Found" / "Skipped" / "Error" status column; enriched output stored at `/outputs/{job_id}/enriched.xlsx`; job status updated to COMPLETE.

**Addresses:** Database-first cache (P0), Apollo API enrichment (P0), deduplication (P0), background processing (P0), job isolation (P0), contact DB write (P0), download enriched file (P0), "not found" status (P0), force re-enrichment override (P1).

**Avoids:** Pitfall 1 (row UUID as join key through entire pipeline). Pitfall 2 (cache normalization, intra-job dedup before cache lookup, ON CONFLICT upsert). Pitfall 3 (no shared mutable state — all state in DB by job_id). Pitfall 5 (pre-flight eligibility check before Apollo dispatch). Pitfall 6 (exponential backoff retry, 429 vs 402/403 distinction, checkpoint-based progress).

**Research flag:** Apollo API specifics require verification. Before building the API client: verify current endpoint URL (`/v1/people/match` or successor), current rate limit thresholds per plan, whether no-match responses consume credits, whether `reveal_personal_emails`/`reveal_phone_number` flags are still required in current API version. Low-effort verification against current Apollo docs pays high dividends here.

---

### Phase 4: Job Status, History, and Download

**Rationale:** Phase 3 produces results but provides no way to observe them or retrieve output. This phase closes the user-facing loop: progress polling, job history, re-download, and the usage stats that justify the tool's existence. These are largely read operations against data Phase 3 writes, making them straightforward to implement.

**Delivers:** Job status/progress polling endpoint (status, N/total rows, cache_hits, api_calls, errors); job history list with re-download links (output file served from `/outputs/{job_id}/enriched.xlsx`); per-job credit tracking (hits, misses, API calls stored at job completion); usage stats dashboard (total credits used, cache hit rate, jobs run, trend over time); Flower monitoring UI wired into Docker Compose.

**Addresses:** Job status/progress (P0), job history + re-download (P0), per-job credit tracking (P1), usage stats dashboard (P1), cache hit rate visibility (P1).

**Avoids:** UX pitfall of no progress feedback (users abandon or duplicate-submit long-running jobs). Security pitfall of serving files without ownership check (download endpoint verifies requesting user owns the job_id).

**Research flag:** Standard patterns — polling/SSE is well-documented; no phase research needed.

---

### Phase 5: Contact Database Browser and Polish

**Rationale:** The contact database browser requires accumulated data from Phase 3 to be useful — it is meaningless at launch. Post-launch, it transforms the contact DB from a hidden implementation detail into a visible team asset. This phase also covers any UX polish, edge case hardening, and post-launch items deferred from earlier phases.

**Delivers:** Contact database browser (search by name, company, email domain); per-user usage breakdown in dashboard; cache hit rate trend over time visualization; export contact DB as Excel/CSV snapshot; any deferred UX improvements (column detection confidence display, skipped row explanation in output, estimated credit count before job starts).

**Addresses:** Contact database browser (P2), cache hit rate trend (P2), per-user usage breakdown (P2), export contact DB snapshot (P2).

**Research flag:** Standard patterns — no phase research needed. Timing is after v1 is live and producing real data.

---

### Phase Ordering Rationale

- Phase 1 first because auth and schema are hard dependencies for all other work. Schema decisions about UUID primary keys and natural key UNIQUE constraints must be locked before any data is written.
- Phase 2 before Phase 3 because the worker pipeline cannot be built without knowing what the parsed row structure looks like and where files are stored. Row UUID assignment belongs in the ingestion layer, not the worker.
- Phase 3 is the critical path: it is the core product. All architectural safeguards (UUID join key, no shared state, cache normalization, retry logic) must be built in here — none can be deferred to Phase 4 or later without architectural rewrites.
- Phase 4 is separated from Phase 3 because job history and dashboard require Phase 3 to produce data before they are testable. Separating them keeps Phase 3 focused on correctness of the pipeline.
- Phase 5 is explicitly deferred because the contact browser requires real data to validate its value. Building it before the tool is in use produces a feature no one will evaluate accurately.

### Research Flags

**Requires deeper research before or during Phase 3 implementation:**
- **Apollo API client specifics:** Verify current endpoint URL, rate limit thresholds per plan tier, credit billing model for no-match responses, whether `reveal_personal_emails` and `reveal_phone_number` are still required flags, bulk endpoint availability and pricing. Fetch current docs at https://docs.apollo.io before writing a single line of the API client.

**Standard patterns, no phase research needed:**
- **Phase 1 (Auth/Infrastructure):** passlib + python-jose JWT auth is well-documented and stable.
- **Phase 2 (File Ingestion):** openpyxl behavior is well-documented; column detection via header alias matching is a known pattern.
- **Phase 4 (Status/History/Dashboard):** Polling, SSE, and read-only dashboard patterns are standard.
- **Phase 5 (Contact Browser):** Search and filtering on a PostgreSQL table is standard CRUD.

---

## Confidence Assessment

| Area | Confidence | Notes |
|------|------------|-------|
| Stack | MEDIUM | FastAPI version HIGH (confirmed 0.135.3). All other library versions from training data (cutoff Aug 2025) — validate all versions against PyPI before first install. React 19 may be appropriate; validate ecosystem compatibility before choosing 18 vs 19. |
| Features | MEDIUM | Feature scope derived from training knowledge of Apollo, ZoomInfo, Clearbit, Clay, and related tools, cross-referenced against PROJECT.md requirements (HIGH confidence). Apollo API response shape and capabilities are MEDIUM confidence — verify field names, match rate by identifier type, and rate limits before building the enrichment pipeline. |
| Architecture | MEDIUM-HIGH | Producer/consumer separation, cache-aside pattern, row UUID tracking, file immutability, and job isolation are established patterns with HIGH confidence. Apollo API specifics (endpoint URL, rate limit headers, credit model) are MEDIUM/LOW confidence and require verification. |
| Pitfalls | HIGH | Pitfall patterns are drawn from well-established batch processing, data pipeline, and enrichment system post-mortems. The specific Apollo API behavioral items (credit model for no-match, required request flags) are MEDIUM confidence — stable behaviors unlikely to have changed fundamentally but must be verified. |

**Overall confidence:** MEDIUM — the architectural approach and pitfall mitigations are solid. The primary gap is Apollo API specifics, which require verification against current documentation before Phase 3 implementation begins.

### Gaps to Address

- **Apollo rate limits:** Exact requests-per-minute and requests-per-hour thresholds per plan tier are LOW confidence (training data may be outdated). Verify against current Apollo docs and design the queue-level throttle accordingly.
- **Apollo credit billing for no-match responses:** Whether a well-formed request with no match consumes a credit is MEDIUM confidence. The pre-flight eligibility check mitigates this regardless, but the credit tracking model in the usage dashboard depends on accurate billing behavior.
- **Apollo required request flags:** `reveal_personal_emails` and `reveal_phone_number` flag behavior in the current API version must be confirmed — if they were deprecated or changed to opt-out after August 2025, the API client needs different handling.
- **Apollo endpoint URL:** `/v1/people/match` was the correct endpoint through August 2025; confirm it has not changed or been superseded.
- **Library versions:** All MEDIUM-confidence versions (Celery, openpyxl, SQLAlchemy, Redis, PostgreSQL, React) should be validated against PyPI/official release pages before the first `uv pip install`. Flag React 19 as a candidate for upgrade over 18.x.
- **Excel file diversity:** Parser correctness must be validated against real export files from the team's actual tools (HubSpot, LinkedIn Sales Navigator, manual spreadsheets) — clean test files will not surface real-world quirks.

---

## Sources

### Primary (HIGH confidence)
- FastAPI release notes (version 0.135.3 confirmed 2026-04-06): https://fastapi.tiangolo.com/release-notes/
- FastAPI file upload requirements (python-multipart): https://fastapi.tiangolo.com/tutorial/request-files/
- `.planning/PROJECT.md` (authoritative requirements and constraints)
- `uv` documentation (1.0 released mid-2024, widely adopted): https://docs.astral.sh/uv/

### Secondary (MEDIUM confidence)
- Celery documentation: https://docs.celeryq.dev/en/stable/
- openpyxl documentation: https://openpyxl.readthedocs.io/en/stable/
- SQLAlchemy 2.0 async documentation: https://docs.sqlalchemy.org/en/20/orm/extensions/asyncio.html
- Apollo People Enrichment API (training data, Aug 2025): https://apolloio.github.io/apollo-api-docs/
- tenacity retry library: https://tenacity.readthedocs.io/en/latest/
- Ruff linter: https://docs.astral.sh/ruff/
- Training knowledge of B2B enrichment tooling (Apollo, ZoomInfo, Clearbit, Lusha, Clay, Kaspr, Datagma) — feature landscape and competitive patterns as of August 2025

### Tertiary (LOW confidence — verify before implementation)
- Apollo rate limit thresholds per plan tier — must be verified against current Apollo documentation
- Apollo credit billing model for no-match responses — verify before building usage dashboard logic
- Apollo `reveal_personal_emails` / `reveal_phone_number` flag behavior in current API version — verify before building API client
- React 19 ecosystem compatibility — validate before choosing React 18 vs 19

---
*Research completed: 2026-04-06*
*Ready for roadmap: yes*
