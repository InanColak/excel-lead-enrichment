# Pitfalls Research

**Domain:** Contact enrichment SaaS — Apollo API, Excel batch processing, concurrent multi-user jobs
**Researched:** 2026-04-06
**Confidence:** HIGH (domain-specific patterns are well-established; web verification unavailable in this session — flagged where Apollo API behavior is version-sensitive)

---

## Critical Pitfalls

### Pitfall 1: Row Identity Lost in the Pipeline (Data Written to Wrong Rows)

**What goes wrong:**
Rows are parsed from Excel into a list or dictionary. During async processing — especially when tasks fan out across a queue — the positional relationship between the input row and the output enrichment result is lost. The result from contact B gets written into contact A's row because the only "key" passing through the pipeline was array index, which shifts when rows are skipped, filtered, or reordered.

**Why it happens:**
Developers use row index (0, 1, 2...) as the join key between "what was sent to API" and "what came back." Any intermediate step that filters out blank rows, deduplicates, or batches by chunk changes the effective index. The enrichment result is then zipped back to the wrong position.

**Consequences:**
Silent data corruption. User downloads the enriched file, imports to CRM, and Alice's contact record now has Bob's phone number. No error is thrown. The corruption is invisible until a human notices a mismatch weeks later.

**Prevention:**
Assign a stable `row_uuid` (UUID4) to every row at parse time — before any filtering, deduplication, or batching. This UUID travels with the row through every stage: stored in the job DB, sent as metadata to the queue worker, returned with the API result, and used as the join key when writing the output file. Never use positional index as the join key past the initial parse step.

**Warning signs:**
- Pipeline code that does `zip(original_rows, enriched_results)` without an explicit ID check
- Any step that filters rows before the ID is assigned
- Workers that receive only contact fields (name, company) without a row identifier

**Phase to address:** Core pipeline (Phase 2 or equivalent enrichment engine phase) — must be designed in before any queue workers are built.

---

### Pitfall 2: Unnecessary API Credit Consumption (Cache Miss Logic Errors)

**What goes wrong:**
The database-first lookup is implemented but has logic gaps that cause credits to be consumed when they shouldn't be:
- Cache lookup is case-sensitive ("John Smith" vs "john smith")
- Partial match treated as miss (LinkedIn URL stored with trailing slash, queried without)
- Deduplication within a single upload not applied before cache lookup — same person appears 3 times, all 3 go to Apollo
- Cache hit check happens per-row serially; if two workers process the same person concurrently, both can miss cache simultaneously and both call Apollo

**Why it happens:**
Cache lookup is written as a simple exact-match DB query. Normalization of lookup keys (email, LinkedIn URL, name+company combo) is skipped to save development time. The race condition in concurrent jobs is not considered during single-user testing.

**Consequences:**
Apollo credits consumed 2-10x faster than expected. For a 1,000-row file with 200 duplicates, this doubles the cost of every job.

**Prevention:**
1. Normalize all lookup keys at parse time: lowercase, strip whitespace, strip URL schemes/trailing slashes from LinkedIn URLs, strip common suffixes from company names ("Inc", "LLC", "Ltd").
2. Deduplicate within-upload BEFORE cache lookup — build a map of `normalized_key → [row_uuids]`, resolve each unique key once, fan results back to all rows that share it.
3. Use a database-level unique constraint + upsert (INSERT ... ON CONFLICT) rather than check-then-insert, to avoid race conditions between concurrent jobs hitting the same new contact simultaneously.
4. Log every cache hit and miss with the lookup key used — this makes debugging credit waste trivial.

**Warning signs:**
- Cache lookup query uses raw user-supplied string values without normalization
- No deduplication step between parse and cache lookup
- Credit consumption is unexpectedly high in testing relative to unique contacts

**Phase to address:** Database and cache layer (before Apollo integration is wired up).

---

### Pitfall 3: Concurrent Job Data Bleed (Shared Mutable State Between Jobs)

**What goes wrong:**
Two users upload files simultaneously. Jobs share a mutable in-memory structure (a dict, a global list, a module-level cache) that is written to by both workers. Results from Job A get mixed into Job B's output. In the worst case, one job's enriched data partially overwrites another job's rows in the output file.

**Why it happens:**
During development the app is tested with one user. The shared state bug is invisible until load testing or production use with concurrent users. Common offenders: a module-level `results = {}` dict that workers write to by row index, a shared temporary file path, a shared output buffer.

**Consequences:**
User B downloads their file and sees contacts they didn't upload. User A's file is missing rows. If the shared state is the output file itself, data loss occurs for one job.

**Prevention:**
Every job gets a globally unique `job_id` (UUID) at creation. All state (input rows, enrichment results, output file) is keyed by `job_id` and stored in the database, not in memory. Workers receive only the `job_id` and fetch their own state from the DB. No module-level mutable structures. Queue workers are stateless — they read from DB, write to DB, done.

**Warning signs:**
- Any module-level variable that accumulates job results
- Workers that write directly to a shared file path rather than to a job-scoped DB record
- Output generation that reads from memory rather than from the DB at download time

**Phase to address:** Job architecture and queue design (must be designed before the first worker is written).

---

### Pitfall 4: Excel Parsing Failures Silently Corrupt Data

**What goes wrong:**
Excel files from real sales teams are structurally irregular:
- Merged cells in header rows (openpyxl reads the merged cell value only for the top-left cell; others return `None`, causing column misdetection)
- Trailing empty rows inflating row counts (a file that "has 500 contacts" actually has 500 rows of data plus 3,000 empty rows)
- Multiple sheets — parser reads Sheet 1 but data is on Sheet 2
- Dates stored as Excel serial numbers (e.g., `44927`) rather than formatted strings — contact's name column contains a date serial
- Cells formatted as numbers that contain phone numbers with leading zeros stripped by Excel
- Formula cells returning `None` until evaluated (openpyxl read_only mode does not evaluate formulas)
- Unicode in company names causing encoding errors in downstream string operations

**Why it happens:**
The parser is written against a clean test file. Real-world Excel files come from a dozen different tools (HubSpot exports, LinkedIn Sales Navigator, manual entry, legacy CRM exports) each with different quirks.

**Consequences:**
Column auto-detection assigns wrong types (a date column detected as "name"). Rows are written to output with data in wrong columns. Empty trailing rows generate 3,000 unnecessary API calls. Formula cells become null and the contact is marked "not found" when data was present.

**Prevention:**
1. Strip trailing empty rows immediately after parse — define "empty" as all meaningful columns being None or empty string.
2. Detect and reject (or flatten) merged cells before column detection.
3. Read the active sheet by default but expose sheet selection to users for override.
4. Convert all cell values to strings before processing — never pass raw openpyxl cell values downstream.
5. Detect date serials (integers in range 1–200000) and flag them in column detection confidence scoring.
6. Use `data_only=True` in openpyxl to read formula results (requires the file was saved after formulas evaluated; warn user if formula cells are detected).
7. Set an explicit row limit in the upload validator (e.g., reject files with >10,000 rows or >50MB).
8. Log a parse summary: rows found, rows skipped as empty, columns detected with confidence scores.

**Warning signs:**
- Parser test suite uses only one or two clean test files
- No handling for `None` values from openpyxl in the column detection logic
- No empty-row stripping step
- Row count from file header does not match count of non-empty rows

**Phase to address:** File ingestion and parsing (earliest phase — this is the entry point for all data).

---

### Pitfall 5: Apollo API Credit Charged on "Not Found" Responses

**What goes wrong:**
Apollo charges a credit when a request is well-formed and processed — even if the person is not found in their database. Developers assume credits are only charged on successful enrichment. The system sends all contacts to Apollo, including obvious junk rows (blank names, test data, placeholder emails like "test@test.com"), each consuming a credit.

**Why it happens:**
Apollo's billing model is "per lookup attempt," not "per successful result." This is documented but easy to miss. Developers focus on the happy path (contact found, data returned) and don't build pre-flight validation to skip unresolvable rows.

**Consequences:**
Credits consumed on rows that could never be enriched. A file with 200 junk/incomplete rows wastes 200 credits.

**Prevention:**
1. Implement a pre-enrichment validation step that scores each row's "enrichability" — a row with no name, no company, and no LinkedIn URL cannot be enriched and should be skipped with a "SKIPPED: insufficient data" status.
2. Validate LinkedIn URLs before sending — must match `linkedin.com/in/` pattern.
3. Filter placeholder/test emails before sending.
4. Log the exact credit cost per job in the DB for the usage stats dashboard.
5. Display a "rows eligible for enrichment: N" count to users before processing begins, with an explanation of why rows were excluded.

**Warning signs (Apollo-specific):**
- No pre-flight row validation before API dispatch
- Credit counter only incremented on successful API responses (misses "not found" charges)
- No per-job credit cost tracking in DB

**Phase to address:** Enrichment engine, specifically the pre-dispatch validation step.

---

### Pitfall 6: Apollo Rate Limit Handling Causes Job Failures or Duplicate Calls

**What goes wrong:**
Apollo's People Enrichment API has rate limits (requests per minute/hour). When a limit is hit, the API returns a 429 response. A naive implementation either:
(a) Crashes the job, losing all progress made so far — user must re-upload the whole file
(b) Retries immediately in a tight loop, consuming more rate limit budget and potentially hitting billing thresholds
(c) Does not retry at all — the row is silently marked "not found" when it was simply throttled

**Why it happens:**
Rate limit handling is treated as an edge case during development (single small files are tested). It only surfaces under production load with large files or multiple concurrent users.

**Consequences:**
Scenario (a): data loss, user frustration, and wasted credits on a partial job that must be re-run.
Scenario (c): silent false negatives — contacts are reported as "not found" when Apollo has their data.

**Prevention:**
1. Implement exponential backoff with jitter for 429 responses: retry after 2s, 4s, 8s, up to a max of 60s, max 5 retries.
2. Distinguish 429 (throttle — retry) from 402/403 (quota exhausted or auth — do NOT retry, surface error to user).
3. Use a job-level progress checkpoint: after each successful batch of N rows, persist the enrichment results to DB. If the job fails mid-way, restart from the last checkpoint rather than from row 0.
4. Process large files in batches of 50–100 rows with a configurable delay between batches.
5. Surface rate limit errors in the job status UI with a human-readable explanation: "Apollo rate limit reached — job paused, will resume automatically."

**Warning signs:**
- No retry logic in the API client
- Job fails without persisting partial results
- 429 treated as permanent failure

**Phase to address:** Enrichment engine (retry logic and checkpoint must be part of the initial worker design, not bolted on later).

---

### Pitfall 7: Original File Modified or Overwritten

**What goes wrong:**
The code reads the uploaded Excel file, enriches data, and writes results back to the same file object. The original upload is mutated. If the job fails midway, the original file is corrupted. Users cannot recover the input data. Re-downloading the "original" gets the partially-modified file.

**Why it happens:**
Libraries like openpyxl load a workbook as a mutable object. Writing enriched columns directly to that workbook and saving to the same path is the "obvious" approach.

**Consequences:**
Irreversible data loss. Users who keep their only copy of the contact list in the uploaded file lose it. Trust in the system is destroyed immediately.

**Prevention:**
1. Store the raw binary of the uploaded file to a permanent location (filesystem or object storage) before any processing touches it. Never pass the file path to the enrichment pipeline — pass only the stored copy's path or ID.
2. The enrichment output is a NEW file, built by reading enrichment results from the DB and the stored original binary — never by modifying the original workbook object in place.
3. Expose both the original file and the enriched file as separate downloads in the UI.

**Warning signs:**
- Output file is written to the same path as the upload
- Enrichment pipeline receives a mutable workbook object rather than DB row IDs
- No "original file" download link in the UI

**Phase to address:** File ingestion (storage architecture must be decided before any processing pipeline is built).

---

### Pitfall 8: Deduplication Key Collisions Across Jobs

**What goes wrong:**
The local contact database deduplicates by a natural key (e.g., `linkedin_url` or `email`). Two contacts share the same LinkedIn URL (a shared team account, a data entry error, a placeholder URL like `linkedin.com/in/johndoe` used for multiple people). The second contact's enrichment result overwrites the first in the DB. Future jobs for the first contact now return wrong data.

**Why it happens:**
Natural keys in contact data are not as unique as assumed. LinkedIn URLs in particular are often copy-pasted incorrectly or reused.

**Prevention:**
1. Use a surrogate primary key (UUID) for every contact record — never rely on natural keys as the DB primary key.
2. Natural keys (LinkedIn URL, email) are stored as indexed columns with a UNIQUE constraint, but when a conflict occurs, log it rather than silently overwrite.
3. On conflict: prefer the more complete record (more non-null fields), log the conflict for human review, and do NOT silently overwrite a known-good record with a new lookup.

**Warning signs:**
- Contact DB schema uses `linkedin_url` as primary key
- Upsert logic with `ON CONFLICT DO UPDATE SET *` overwrites all fields unconditionally

**Phase to address:** Database schema design (must be in schema before any data is written).

---

## Technical Debt Patterns

| Shortcut | Immediate Benefit | Long-term Cost | When Acceptable |
|----------|-------------------|----------------|-----------------|
| Use row index as join key through pipeline | Simpler code, no UUID generation needed | Silent data corruption at scale or when rows are filtered | Never — row UUID is a one-time 5-minute addition |
| Skip normalization on cache lookup keys | Faster initial implementation | Cache miss rate 10-30% higher than expected, credits wasted | Never for the lookup key; acceptable for display/storage |
| In-memory job state instead of DB-persisted | Faster for small files, no DB queries in hot path | Data loss on worker crash, concurrency bugs | Acceptable only for single-user local development |
| Process all rows including empty/junk | Simpler parse logic, no validation step | Credits consumed on unresolvable rows | Never — validation pays for itself on first 500-row file |
| Write enrichment output to uploaded file in place | One fewer file to manage | Irreversible data loss on failure | Never |
| No retry on 429 | Simpler API client | Silent false negatives, user-visible failures | Never in production |
| Single global Apollo API client with no rate tracking | Easy singleton | Concurrent jobs share rate limit state, one job starves others | Acceptable in MVP if rate limits have not yet been hit |
| Checkpoint-less batch processing | Simpler queue worker | Re-run entire job on any failure; credits re-consumed | Never for files >100 rows |

---

## Integration Gotchas (Apollo API Specific)

| Gotcha | Description | Mitigation |
|--------|-------------|------------|
| Credits charged on "not found" | A well-formed request that finds no match still consumes a credit | Pre-flight row eligibility check before dispatch |
| Credit charged on partial data | If Apollo returns some fields but not email/phone, credit is still consumed | Accept partial results; store what was returned; don't retry unless "force re-enrich" is set |
| `reveal_personal_emails` parameter required | Without this flag, personal (non-work) emails are not returned even if available | Explicitly set `reveal_personal_emails: true` in every request |
| `reveal_phone_number` parameter required | Mobile numbers are gated behind this flag; omitting it returns no phone data | Explicitly set `reveal_phone_number: true` in every request |
| LinkedIn URL format sensitivity | Apollo expects `linkedin.com/in/handle` without scheme or trailing slash in some API versions | Normalize to `linkedin.com/in/handle` (no `https://`, no trailing slash) before sending |
| API key expiry/rotation | Shared team key may expire; no automatic refresh | Surface 401 errors to admins prominently; do not silently fail jobs |
| Bulk endpoint vs single-person endpoint | Apollo has both; bulk is not always the same credit cost per contact | Verify current pricing for bulk vs single before choosing batch strategy |
| Response field instability | Apollo adds/removes response fields across API versions; code that accesses `.email` directly crashes if field is absent | Always use `.get('email')` with a default; never index response fields directly |
| No idempotency key | Calling Apollo twice for the same person charges twice; the API has no deduplication guarantee | Enforce deduplication in your own code before dispatch; never call API if result already in DB |
| Rate limit headers | Apollo returns rate limit info in response headers (X-RateLimit-Remaining etc.) — use them for proactive throttling rather than waiting for 429 | Parse rate limit headers in every response and back off when remaining < 10% |

---

## Performance Traps

| Trap | Symptom | Root Cause | Fix |
|------|---------|------------|-----|
| Serial row processing (no batching) | 1,000-row file takes 30+ minutes | One API call → wait → next API call | Process in batches; use async HTTP or thread pool for parallel requests within rate limit budget |
| Unbounded file size acceptance | Upload of 50,000-row file freezes the server | No file size or row count limit enforced | Validate on upload: reject files >10,000 rows or >50MB with a clear error message |
| Loading entire Excel file into memory | Memory spike on large uploads, worker OOM | openpyxl default mode loads full workbook | Use openpyxl `read_only=True` for parse; stream rows rather than loading all at once |
| N+1 DB queries in cache lookup | Cache lookup takes longer than the API call | One DB query per row instead of bulk lookup | Batch all row keys, single `SELECT ... WHERE key IN (...)` query, build result map |
| Output Excel generated synchronously at download time | Download request times out for large files | Output file rebuilt from DB on every download request | Generate output file once when job completes, store it; download serves the stored file |
| No job queue (synchronous processing in web request) | Web server hangs during enrichment; timeouts for large files | Enrichment called directly in request handler | Background job queue (Celery, RQ, or similar) is mandatory for any file >50 rows |
| Polling UI without server-sent events or websockets | UI hammers server with status requests | Simple "reload every 5 seconds" implementation | Use SSE or websocket for job status updates; or implement long-polling with reasonable intervals (5–10s is fine for this use case) |

---

## Security Mistakes

| Mistake | Risk | Fix |
|---------|------|-----|
| Apollo API key stored in code or .env committed to git | Key exposed in repo history; unauthorized usage, unexpected billing | Store in environment variable; never commit; document key rotation procedure |
| No file type validation beyond extension | Malicious file upload (e.g., .xlsx with embedded macros or XML payloads) | Validate file magic bytes, not just extension; use openpyxl's safe parsing; reject files with macros |
| No file size limit | Denial-of-service via huge file upload consuming memory/CPU | Enforce size limit at web server level AND application level |
| Serving enriched files without authorization check | User B downloads User A's enriched file by guessing the job ID | Job ID must be a random UUID; download endpoint must verify requesting user owns the job |
| Admin API key management with no audit trail | Key rotated without notification; jobs fail silently; no record of who changed it | Log all API key change events with timestamp and acting user |
| Storing contacts with PII in DB without access controls | Any authenticated user can query any contact | For internal tool this may be acceptable; if not, add row-level security |
| No rate limiting on upload endpoint | Authenticated user floods the system with uploads | Rate limit uploads per user (e.g., 5 concurrent jobs max per user) |

---

## UX Pitfalls

| Pitfall | User Experience | Fix |
|---------|-----------------|-----|
| No progress feedback during enrichment | User thinks the job is frozen; refreshes page, creating duplicate job submission | Real-time job status with row progress (X of N rows enriched) |
| Ambiguous "Not Found" status | User can't tell if "not found" means Apollo has no data vs. the row was invalid | Use distinct statuses: "Not Found" (Apollo searched, no result), "Skipped" (insufficient data to search), "Error" (API/system failure) |
| No explanation of skipped rows | User sees 1,000 rows uploaded but 750 enriched; doesn't understand why 250 were skipped | Show per-row status in output file + summary counts in UI |
| Column auto-detection with no user feedback | Wrong column mapping is invisible; user gets wrong data back | Show detected column mapping before processing starts; require confirmation or allow override |
| Output file column order differs from input | User expects original columns followed by enrichment columns; mismatches break their downstream workflow | Guarantee output column order: all original columns in original order, then Email, Phone, Status appended |
| No re-download after job completes | User closes tab, comes back, job is gone | Persist output file; provide job history with re-download for at least 30 days |
| Credit usage not visible until after job | User doesn't know how many credits a job will consume until it's done | Show estimated credit usage (based on eligible rows after cache check) before processing |

---

## "Looks Done But Isn't" Checklist

Before considering a feature complete, verify:

- [ ] Row UUIDs are assigned at parse time and survive every transformation step (filter, dedup, batch, queue)
- [ ] Cache lookup uses normalized keys — test with case variations, URL variations, whitespace variations
- [ ] Within-upload deduplication runs before cache lookup, not after
- [ ] Empty rows are stripped before any processing, not just before API dispatch
- [ ] The original uploaded file is byte-for-byte identical at download time to what was uploaded
- [ ] Output file is a new file, not the modified original
- [ ] Apollo 429 responses trigger retry with backoff, not job failure and not silent "not found"
- [ ] Apollo 402/403 responses surface an admin alert, not a silent job failure
- [ ] `reveal_personal_emails` and `reveal_phone_number` are set in every API request
- [ ] LinkedIn URLs are normalized before cache lookup AND before API dispatch
- [ ] Job download endpoint verifies the requesting user owns the job
- [ ] Apollo API key is not present in any committed file (check git history)
- [ ] A file with merged header cells is parsed without crashing
- [ ] A file with 3,000 trailing empty rows does not generate 3,000 API calls
- [ ] A file with formula cells shows a warning, not silent nulls
- [ ] Two users uploading simultaneously do not see each other's data
- [ ] Job failure midway persists results for completed rows (checkpoint)
- [ ] Usage stats dashboard counts "not found" API calls as credit-consuming, not free
- [ ] Column detection confidence scores are logged for every job

---

## Recovery Strategies

| Failure Scenario | Recovery Strategy | Automated? |
|------------------|-------------------|------------|
| Job fails midway through large file | Checkpoint-based resume: re-enqueue from last persisted row UUID | Yes — worker reads last checkpoint from DB on restart |
| Apollo API key exhausted mid-job | Pause all jobs, surface alert to admin, resume when key is updated | Partially — alert is automated; key update is manual |
| Wrong column mapping applied to job | Allow admin to re-run enrichment on same file with corrected mapping (force re-enrich flag reuses stored file) | No — manual correction and re-run |
| Data written to wrong rows (detected post-download) | If row UUIDs were used: trace back through logs to find mismatch point; re-run job | Partially — diagnosis automated via logs; re-run is manual |
| Duplicate API calls discovered (credits wasted) | Identify normalization gap causing cache miss; add normalization rule; re-check DB for affected contacts | No — manual investigation required |
| Output file corrupted or missing | Regenerate from stored enrichment results in DB + stored original file | Yes — output file is always regeneratable from DB state |
| Concurrent job data bleed detected | If job state is DB-keyed: rollback affected job records; re-run | Partially — rollback possible if audited; re-run manual |
| Excel file with unusual structure rejected by parser | Expose parse error in UI with specific row/column reference; user fixes file and re-uploads | Partially — error reporting automated; file fix is manual |

---

## Pitfall-to-Phase Mapping

| Pitfall | Severity | Phase to Address | Can It Be Added Later? |
|---------|----------|-----------------|------------------------|
| Row UUID identity tracking | CRITICAL | File ingestion + pipeline design (earliest) | No — retrofitting breaks the entire pipeline |
| Job isolation (no shared state) | CRITICAL | Job architecture design (before first worker) | No — retrofitting requires rewriting worker architecture |
| Original file preservation | CRITICAL | File ingestion (storage decision) | No — once modified, data is already lost |
| Within-upload deduplication | HIGH | Cache/lookup layer | With difficulty — requires adding a step before API dispatch |
| Cache key normalization | HIGH | Cache/lookup layer | Yes — add normalization to lookup queries; retroactively normalize DB entries |
| Pre-flight row eligibility check | HIGH | Enrichment engine | Yes — can be added before API dispatch step |
| Excel edge cases (merged cells, empty rows, formulas) | HIGH | File ingestion | Partially — some checks can be added; parser rewrite is costly late |
| Apollo 429 retry/backoff | HIGH | Enrichment engine (API client) | Yes — isolated to API client layer |
| Apollo "credits on not found" awareness | MEDIUM | Enrichment engine + usage stats | Yes — affects dashboard accuracy but not data integrity |
| Apollo field flags (reveal_personal_emails etc.) | MEDIUM | Enrichment engine (API request builder) | Yes — one-line fix but silent until noticed |
| Checkpoint-based job resume | MEDIUM | Queue worker design | Difficult — requires DB schema support designed in early |
| Deduplication key collision in DB | MEDIUM | Database schema | No — schema changes after data exists are risky migrations |
| File size/row limits | MEDIUM | File ingestion | Yes — validation layer, easy to add |
| Output file regenerability from DB | MEDIUM | Output generation | Yes — if enrichment results are stored per-row in DB |
| API key security (not in code) | HIGH | Project setup (Day 1) | Yes — but key rotation after a leak is painful |

---

## Sources

**Confidence note:** Web search and WebFetch were unavailable during this research session. All findings are based on training data through August 2025, covering:

- Apollo.io People Enrichment API documentation and community reports (training data, HIGH confidence for stable behaviors; MEDIUM confidence for specific rate limit thresholds — verify current numbers in Apollo docs before implementation)
- openpyxl library behavior with real-world Excel files (HIGH confidence — well-documented library with stable behavior)
- Batch processing and job queue patterns in Python web applications (HIGH confidence)
- Data integrity patterns for pipeline systems with row-level tracking (HIGH confidence)
- Common SaaS contact enrichment product post-mortems and community discussions (MEDIUM confidence — patterns are consistent across sources)

**Items requiring verification against current Apollo documentation before implementation:**
- Exact rate limit thresholds (requests/minute, requests/hour)
- Whether bulk endpoint pricing differs from single-person endpoint
- Current behavior of `reveal_personal_emails` and `reveal_phone_number` flags (verify they are still required parameters in current API version)
- Whether Apollo charges credits for malformed requests vs. well-formed "not found" responses

Official Apollo API reference: https://apolloio.github.io/apollo-api-docs/
