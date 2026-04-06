# Architecture Research

**Domain:** Contact enrichment SaaS (batch, Apollo-powered)
**Researched:** 2026-04-06
**Confidence:** MEDIUM — derived from training knowledge of equivalent systems (job queue patterns, file-processing pipelines, Apollo API shape). Web verification was unavailable. Apollo API specifics flagged where LOW confidence.

---

## Standard Architecture

### System Overview (ASCII diagram)

```
Browser Client
      |
      | HTTP (REST/JSON)
      v
+---------------------+
|    Web Server       |  Express / FastAPI / similar
|  - Auth middleware  |
|  - File upload      |
|  - Job management   |
|  - Admin dashboard  |
|  - Download/serve   |
+---------------------+
      |          |
      |          | Enqueue job
      |          v
      |   +--------------+
      |   |  Job Queue   |  BullMQ (Redis-backed) / Celery / similar
      |   |  - Job items |
      |   |  - Progress  |
      |   |  - Retries   |
      |   +--------------+
      |          |
      |          | Dequeue & process
      |          v
      |   +--------------+
      |   |   Worker(s)  |  Separate process(es)
      |   |  - Parse row |
      |   |  - DB lookup |
      |   |  - API call  |
      |   |  - Write DB  |
      |   +--------------+
      |        |      |
      |   DB lookup   | Apollo API call (cache miss only)
      |        |      v
      |        |  +-----------+
      |        |  | Apollo    |  External: People Enrichment API
      |        |  | API       |  Rate-limited, credit-gated
      |        |  +-----------+
      |        v
      |  +------------------+
      +->|   Database       |  PostgreSQL
         |  - contacts      |  Growing contact asset
         |  - jobs          |  Job metadata & status
         |  - job_rows      |  Per-row results, keyed by unique ID
         |  - users         |  Auth
         |  - api_usage     |  Credit tracking
         +------------------+
                |
                | File storage (uploads + results)
                v
         +------------------+
         |  File Store      |  Local disk (Docker volume) or S3-compatible
         |  - raw uploads   |  Preserved originals, never modified
         |  - output files  |  Generated enriched Excel
         +------------------+
```

### Component Responsibilities

| Component | Responsibility | Key Boundaries |
|-----------|---------------|----------------|
| **Web Server** | Receive uploads, authenticate users, serve UI API, queue jobs, stream job status, serve downloads | Does NOT do enrichment work. Never calls Apollo directly. |
| **Job Queue** | Durable task storage, worker dispatch, progress tracking, retry logic, concurrency control | Sits between web server and workers. Redis-backed for persistence. |
| **Worker(s)** | Parse Excel rows, execute DB lookups, call Apollo for cache misses, write results to DB, update job progress | Isolated per job. Never shares mutable state across jobs. |
| **Contact Database** | Growing asset of all enriched contacts. First lookup target before any API call. Deduplication source. | Append-on-new, update-on-re-enrich. Indexed on (name+company), linkedin_url, email. |
| **Job Store (DB tables)** | Job lifecycle (created, queued, processing, done, failed), per-row results with unique IDs, re-download metadata | jobs + job_rows tables. Row ID is the integrity anchor. |
| **File Store** | Immutable storage of original uploaded files. Writable storage for generated output files. | Original never overwritten. Output generated on-demand or cached. |
| **Apollo API Client** | Thin HTTP client with rate-limit awareness, retry on 429, credit-usage tracking, timeout handling | Lives inside Worker. Not a shared singleton — instantiated per job or rate-limited via queue throttle. |
| **Auth Layer** | Email/password authentication, session/JWT management, role check (admin vs user) | Middleware applied to all routes. Admin flag gates API key config and user management. |
| **Admin Dashboard** | API key configuration, user management, usage statistics view | Server-rendered or SPA routes gated behind admin role. |

---

## Recommended Project Structure

```
leadenrich/
├── docker-compose.yml          # Web + worker + postgres + redis
├── Dockerfile.web              # Web server image
├── Dockerfile.worker           # Worker image (same code, different entrypoint)
├── .env.example
│
├── src/
│   ├── server/
│   │   ├── index.ts            # Express app entry
│   │   ├── routes/
│   │   │   ├── auth.ts         # login, logout, session
│   │   │   ├── jobs.ts         # upload, status, download, history
│   │   │   ├── contacts.ts     # contact DB browser
│   │   │   └── admin.ts        # users, api key, usage stats
│   │   ├── middleware/
│   │   │   ├── auth.ts         # session check, role guard
│   │   │   └── upload.ts       # multer config, size/format validation
│   │   └── lib/
│   │       └── queue.ts        # BullMQ connection, job enqueue helpers
│   │
│   ├── worker/
│   │   ├── index.ts            # Worker process entry, queue consumer
│   │   ├── pipeline/
│   │   │   ├── parse.ts        # Excel parsing, column detection
│   │   │   ├── dedupe.ts       # Intra-job deduplication
│   │   │   ├── lookup.ts       # DB-first cache lookup
│   │   │   ├── enrich.ts       # Apollo API call + result parsing
│   │   │   └── assemble.ts     # Merge results back to row order
│   │   └── output/
│   │       └── excel.ts        # Generate enriched output file
│   │
│   ├── shared/
│   │   ├── db/
│   │   │   ├── client.ts       # Postgres connection (Prisma/Drizzle)
│   │   │   ├── schema.ts       # Table definitions
│   │   │   └── migrations/     # SQL migration files
│   │   ├── apollo/
│   │   │   └── client.ts       # Apollo HTTP client, rate-limit handling
│   │   └── types/
│   │       └── index.ts        # Shared TypeScript types
│   │
│   └── frontend/               # React/Vue SPA or server-rendered templates
│       ├── pages/
│       │   ├── Login.tsx
│       │   ├── Upload.tsx
│       │   ├── JobStatus.tsx
│       │   ├── JobHistory.tsx
│       │   ├── Contacts.tsx
│       │   └── Admin.tsx
│       └── components/
│
├── uploads/                    # Docker volume mount — original files
└── outputs/                    # Docker volume mount — generated files
```

**Key structural decision:** Worker and web server share `src/shared/` (DB client, Apollo client, types) but run as separate Docker services. Same codebase, different entrypoints. This avoids code duplication without creating a monorepo.

---

## Architectural Patterns

### Pattern 1: Database-First Cache (Cache-Aside)

The contact database acts as a read-through cache against the Apollo API. For each row:

1. Build a lookup key from available identifiers (linkedin_url preferred, else name+company)
2. Query `contacts` table
3. Cache hit: return stored email/phone, increment cache_hit counter
4. Cache miss: call Apollo, write result to `contacts`, return result

```
lookup(row) {
  const key = row.linkedin_url ?? `${row.first_name}|${row.last_name}|${row.company}`
  const cached = await db.contacts.findByKey(key)
  if (cached) return { ...cached, source: 'cache' }

  const result = await apolloClient.enrichPerson(row)
  await db.contacts.upsert(result)
  return { ...result, source: 'api' }
}
```

**Why this order:** LinkedIn URL is deterministic (one person = one URL). Name+company is fuzzy. Prefer deterministic keys for cache hits to avoid false positives.

### Pattern 2: Row-Level Unique ID Tracking

Every input row gets a UUID assigned at parse time. This ID flows through the entire pipeline and is the FK in `job_rows`. Prevents position-shift bugs if rows are reordered during processing.

```
// At parse time
rows = parseExcel(file).map((row, i) => ({
  ...row,
  row_id: uuid(),
  row_index: i,   // preserve original display order
}))

// At result write time
await db.job_rows.insert({
  job_id,
  row_id: row.row_id,
  row_index: row.row_index,
  status: 'found' | 'not_found' | 'error',
  email: result?.email,
  phone: result?.phone,
})

// At output assembly time
const results = await db.job_rows.findByJobId(job_id)
results.sort((a, b) => a.row_index - b.row_index)  // reconstruct original order
```

### Pattern 3: Intra-Job Deduplication Before Queue

Before enqueuing individual rows to Apollo, deduplicate within the upload. Same LinkedIn URL or same name+company = one API call, result fanned back to all matching rows.

```
// Group rows by canonical key
const groups = Map<string, Row[]>()
for (const row of rows) {
  const key = canonicalKey(row)
  groups.get(key)?.push(row) ?? groups.set(key, [row])
}

// Enqueue one item per unique person
const uniquePersons = [...groups.entries()].map(([key, rows]) => ({
  key,
  representative: rows[0],   // used for API call
  row_ids: rows.map(r => r.row_id),  // all rows that get the result
}))
```

### Pattern 4: Job Queue with Concurrency Throttle

Use BullMQ (Node.js) with per-queue concurrency limits and rate-limit middleware for the Apollo client. Each enrichment job is a parent job; each unique person within it is a child job (BullMQ's job flows, or a simpler flat queue with job_id metadata).

**Simpler approach for this scale:** Single flat queue, workers process one row-batch per job, job_id is metadata on each queue item. No need for BullMQ flows unless jobs are large enough to benefit from partial progress resumability.

```
// Enqueue
await enrichQueue.add('enrich-person', {
  job_id,
  person: uniquePerson,
}, {
  attempts: 3,
  backoff: { type: 'exponential', delay: 2000 },
})

// Worker
enrichQueue.process('enrich-person', MAX_CONCURRENCY, async (job) => {
  const { job_id, person } = job.data
  // ... lookup, enrich, write
  await updateJobProgress(job_id)
})
```

### Pattern 5: Column Auto-Detection via Heuristics

Parse column headers with a scoring/matching approach. Headers are lowercased, stripped of spaces/underscores, then matched against a known-alias map.

```
const COLUMN_ALIASES = {
  linkedin_url: ['linkedin', 'linkedinurl', 'profileurl', 'li', 'linkedinprofile'],
  first_name:   ['firstname', 'first', 'fname', 'givenname'],
  last_name:    ['lastname', 'last', 'lname', 'surname', 'familyname'],
  full_name:    ['name', 'fullname', 'contactname'],
  company:      ['company', 'organization', 'org', 'employer', 'companyname'],
  email:        ['email', 'emailaddress', 'mail'],
}

function detectColumn(header: string): ColumnType | null {
  const normalized = header.toLowerCase().replace(/[\s_\-\.]/g, '')
  for (const [type, aliases] of Object.entries(COLUMN_ALIASES)) {
    if (aliases.includes(normalized)) return type as ColumnType
  }
  return null
}
```

Manual override: store detected mapping in `jobs.column_map` (JSON column), allow UI to patch it before processing begins. Processing is gated until column map is confirmed.

---

## Data Flow

### Request Flow (Enrichment Pipeline)

```
1. UPLOAD
   User → POST /jobs/upload (multipart)
     → Validate file (size, .xlsx/.xls/.csv extension)
     → Store original to /uploads/{job_id}/original.xlsx
     → Parse headers only (not rows yet)
     → Auto-detect columns → store column_map
     → Create job record: status=PENDING_CONFIRMATION
     → Return: job_id, detected column_map, preview rows

2. CONFIRM
   User → POST /jobs/{job_id}/confirm (with column_map override if needed)
     → Parse all rows, assign row_id UUIDs
     → Intra-job deduplication → unique person list
     → Insert job_rows (status=PENDING for each)
     → Enqueue enrichment tasks to job queue
     → Update job: status=QUEUED
     → Return: job_id, row_count, unique_person_count

3. PROCESS (Worker — async)
   For each unique person item from queue:
     a. DB lookup by canonical key
        → HIT:  write result to all matching job_rows (source=cache)
        → MISS: call Apollo People Enrichment API
                → Success: write to contacts table + all matching job_rows (source=api)
                → Not found: write job_rows with status=NOT_FOUND
                → Error/429: retry with backoff (max 3 attempts)
     b. Update job progress counter
     c. When all items done: generate output Excel, update job status=COMPLETE

4. POLL / STATUS
   User → GET /jobs/{job_id}/status
     → Return: status, progress (N/total), cache_hits, api_calls, errors

5. DOWNLOAD
   User → GET /jobs/{job_id}/download
     → Serve /outputs/{job_id}/enriched.xlsx
     → File = original columns + email column + phone column + status column
```

### Key Data Flows

**File integrity flow:**
```
upload → /uploads/{job_id}/original.xlsx (immutable)
                                         ↓
                              parse into memory only
                                         ↓
                              results written to job_rows table
                                         ↓
                              output assembled from job_rows
                                         ↓
                              /outputs/{job_id}/enriched.xlsx (generated)
```
Original file is never read again after parse. Output is generated from DB, not from modifying the original.

**Credit optimization flow:**
```
row arrives at worker
        ↓
canonical key built (linkedin_url preferred)
        ↓
        ├── DB hit → result from contacts table (0 credits)
        │            ↓
        │     job_row updated (source=cache)
        │
        └── DB miss → Apollo API call (1 credit)
                       ↓
                 upsert contacts table
                       ↓
                 job_row updated (source=api)
```

**Job isolation flow:**
```
Job A (User 1)          Job B (User 2)
    ↓                       ↓
Queue items tagged      Queue items tagged
with job_id=A           with job_id=B
    ↓                       ↓
Worker picks up A       Worker picks up B
writes to job_rows      writes to job_rows
WHERE job_id=A          WHERE job_id=B
    ↓                       ↓
No shared mutable state — only shared: contacts table (append-safe)
```

**Contacts table as shared growing asset:**
The contacts table is write-safe across concurrent jobs because writes are upserts keyed on a stable identifier. Two jobs enriching the same person simultaneously both write the same data — idempotent. No locking needed for this pattern.

---

## Scaling Considerations

| Concern | At 10 users / 100 rows | At 10 users / 1,000 rows | At 50 users / 5,000 rows |
|---------|------------------------|--------------------------|--------------------------|
| File parsing | Synchronous in request is fine | Move to worker (first step) | Worker mandatory, stream parse |
| Queue | Single BullMQ queue, 1 worker | Single queue, 2-3 workers | Multiple worker replicas, Redis cluster |
| Apollo rate limits | Not a concern | Monitor 429s, add backoff | Rate-limit queue to Apollo's stated limit |
| DB connections | Default pool (5-10) fine | Pool sizing matters | PgBouncer connection pooler |
| Output file generation | In-memory fine | In-memory fine for xlsx | Stream write for very large files |
| Contact DB cache hit rate | Low (new system) | Growing (30-60% hit rate) | High (80%+ hit rate for repeat data) |
| Storage | Local volume fine | Local volume fine | S3-compatible if multi-instance workers |

**For this project's stated scale (internal team, 1,000+ rows):** A single worker replica with BullMQ concurrency of 5-10 simultaneous persons handles the load. Redis + PostgreSQL on the same Docker host is fine. No distributed infrastructure needed.

---

## Anti-Patterns

### Anti-Pattern 1: Calling Apollo in the Web Server Request Cycle

**What goes wrong:** User uploads a 500-row file. Server calls Apollo synchronously. Request times out after 30-60 seconds. User gets a 504. No result is saved. The job is lost.

**Why it happens:** It seems simpler — no queue to set up.

**Consequences:** Timeouts for any file over ~50 rows. No ability to track progress. Lost work on server restart. API credits consumed but results not saved.

**Prevention:** All Apollo calls happen in the worker, always. The web server only enqueues and returns immediately with a job_id.

### Anti-Pattern 2: Writing Results Keyed by Row Index Instead of Row ID

**What goes wrong:** Worker processes rows out of order (concurrent processing). Row 3's result is written to position 3 in an array. But another concurrent process already shifted the array. Row 3's email ends up in row 5's output.

**Consequences:** Data integrity violation. Wrong emails delivered to wrong contacts. Potentially serious for sales outreach.

**Prevention:** Assign a UUID to every row at parse time. Every result write references `row_id`, not position. Output is assembled by sorting on `row_index` (original position) after all results are written.

### Anti-Pattern 3: Shared Mutable State Between Concurrent Jobs

**What goes wrong:** Worker holds a `currentJob` singleton object. Two jobs run simultaneously. Job B's data overwrites Job A's `currentJob.results` array.

**Consequences:** Job A's output is corrupted. Users get each other's data.

**Prevention:** No singleton job objects in workers. Each queue item carries all its context as payload. Results are written to DB immediately, not accumulated in memory.

### Anti-Pattern 4: No Intra-Job Deduplication

**What goes wrong:** A 500-row file has 50 rows for "John Smith at Acme Corp". The worker makes 50 Apollo API calls for the same person.

**Consequences:** 49 wasted API credits per duplicate person. Multiplied across large files, this defeats the purpose of the system.

**Prevention:** Deduplicate by canonical key before enqueuing. One API call per unique person per job, result fanned to all matching rows.

### Anti-Pattern 5: Overwriting the Original Upload File

**What goes wrong:** Enrichment pipeline reads the file, appends columns, writes it back to the same path.

**Consequences:** The original is lost. If the job fails midway, the partially-modified file is neither the original nor a valid output. Re-download fails.

**Prevention:** Original is written to `/uploads/{job_id}/original.xlsx` and never touched again. Output is assembled fresh from the `job_rows` table and written to `/outputs/{job_id}/enriched.xlsx`.

### Anti-Pattern 6: Storing the Apollo API Key in the Application Code or Repo

**What goes wrong:** API key is hardcoded or committed.

**Prevention:** Admin stores the key through the admin UI. It is persisted in the database (encrypted at rest or in a dedicated `config` table). Workers read it from DB at job start. Never in env vars committed to source control.

---

## Integration Points

### External Services — Apollo People Enrichment API

**Confidence: MEDIUM** (training knowledge as of Aug 2025; verify current rate limits with Apollo docs)

| Aspect | Expected Behavior | Implication |
|--------|-------------------|-------------|
| Endpoint | `POST /v1/people/match` | Single-person enrichment per call. No batch endpoint in v1. |
| Lookup identifiers | `linkedin_url` (most reliable), `first_name` + `last_name` + `organization_name`, `email` | Build canonical key priority: linkedin_url > name+company > email |
| Response on match | Person object with `email`, `phone_numbers` array, confidence scores | Parse `phone_numbers[0].sanitized_number` for primary mobile |
| Response on no match | 200 with `person: null` or empty person object | Treat as NOT_FOUND status, do not retry |
| Rate limits | Likely 100-300 req/min depending on plan (LOW confidence — verify with Apollo) | Implement token bucket or queue-level throttling |
| Credits | One credit per successful match (NOT per call). No-match = no charge (verify with Apollo — LOW confidence) | Budget tracking: count `source=api AND status=found` rows |
| Auth | API key via `api_key` parameter or `X-Api-Key` header | Store in DB, inject at worker call time |
| Timeout behavior | HTTP call should be given 10-15s timeout before retry | Apollo can be slow under load |
| Retry strategy | 429 = rate limited (backoff + retry). 5xx = retry with backoff. 4xx except 429 = do not retry. | BullMQ's built-in retry with exponential backoff handles this |

**LOW confidence items to verify before building the Apollo client:**
- Exact rate limit numbers per plan tier
- Whether no-match responses consume credits
- Whether `v1/people/match` is the current canonical endpoint (may have changed)
- Bulk/batch endpoint availability (if they added one post-Aug 2025)

### Internal Boundaries

| Boundary | Protocol | Notes |
|----------|----------|-------|
| Web Server → Job Queue | BullMQ client (Redis TCP) | Web server is a producer only. Never a consumer. |
| Worker → Job Queue | BullMQ worker (Redis TCP) | Workers are consumers only. Never serve HTTP. |
| Worker → Database | SQL (Prisma/Drizzle ORM) | Workers need full DB access for contacts + job_rows |
| Web Server → Database | SQL (Prisma/Drizzle ORM) | Web server reads job status, serves contact browser |
| Web Server → File Store | Local filesystem via `fs` | Upload handler writes; download handler reads/streams |
| Worker → File Store | Local filesystem via `fs` | Worker reads original (parse); writes output (assemble) |
| Worker → Apollo API | HTTPS REST | One-way call. Responses never trigger callbacks. |
| Web Server ↔ Browser | REST JSON API + file download | SSE or polling for job progress. No WebSockets needed. |

**Shared infrastructure:**
- PostgreSQL: shared between web server and workers
- Redis: shared between web server (producer) and workers (consumer)
- File volume: shared between web server (upload/download) and worker (parse/assemble) — requires same Docker volume mount

---

## Suggested Build Order (Phase Dependencies)

Based on the dependency graph above:

```
1. Database schema + migrations
   (everything else depends on this)

2. Auth system (users table, session middleware)
   (gates all routes)

3. File upload + storage + Excel parsing + column detection
   (required before jobs can exist)

4. Job queue infrastructure (Redis + BullMQ setup)
   (required before async processing)

5. Worker pipeline: DB lookup + Apollo client
   (core value; depends on 1, 3, 4)

6. Job status + progress tracking + download
   (depends on 5 being able to write results)

7. Contact database browser
   (reads from contacts table populated by 5)

8. Admin dashboard + usage stats
   (reads from jobs + api_usage tables)

9. Docker Compose wiring
   (can be started early but finalized last)
```

**Critical path:** 1 → 2 → 3 → 4 → 5 → 6. Everything else is parallel or follow-on.

---

## Sources

- Apollo API behavior: training knowledge as of August 2025 (MEDIUM confidence). Official docs at https://developer.apollo.io/docs should be verified before implementing the Apollo client, particularly rate limits and current endpoint URLs.
- BullMQ patterns: training knowledge (HIGH confidence for general patterns; verify version-specific APIs against https://docs.bullmq.io).
- Excel parsing patterns (exceljs/xlsx): training knowledge, well-established libraries (HIGH confidence).
- Job queue architecture (producer/consumer separation): established pattern, HIGH confidence.
- Row-level UUID tracking pattern: derived from data integrity requirements in similar batch systems, HIGH confidence in approach.
- File immutability pattern: standard practice in ETL systems, HIGH confidence.
- Cache-aside pattern: textbook pattern, HIGH confidence in concept; application to this domain is reasoned from project requirements.
