# Stack Research

**Domain:** Contact enrichment SaaS (Apollo API + Excel processing)
**Researched:** 2026-04-06
**Confidence:** MEDIUM — FastAPI version confirmed via official release notes (0.135.3). All other versions are from training data (cutoff August 2025) cross-referenced against known stable releases. Flag all pinned versions for validation before first install.

---

## Recommended Stack

### Core Technologies

| Technology | Version | Purpose | Why Recommended |
|------------|---------|---------|-----------------|
| Python | 3.12 | Runtime | LTS-aligned, async performance improvements over 3.11, broad library support. 3.13 exists but ecosystem compatibility lags — use 3.12 for stability. |
| FastAPI | 0.115.x | API framework | Async-native, automatic OpenAPI docs, Pydantic v2 validation built in. Confirmed latest is 0.135.3 (2026-04-01) — use `>=0.115,<1.0` to avoid pinning to a specific patch. Pydantic v2 required (>=2.9.0 per 0.135.2 notes). |
| Uvicorn | 0.30.x | ASGI server | Standard production server for FastAPI. Use `uvicorn[standard]` for uvloop + httptools. |
| PostgreSQL | 16 | Primary database | Relational integrity for contact deduplication (UNIQUE constraints on email/phone/LinkedIn URL). JSONB for flexible raw Apollo response storage. pg16 is the current production-stable release. |
| SQLAlchemy | 2.0.x | ORM | SQLAlchemy 2.x async engine (`asyncpg` dialect) matches FastAPI's async model. The 1.x API is legacy — do not use. |
| Alembic | 1.13.x | DB migrations | Pairs with SQLAlchemy 2.x. Async migration support via `run_sync`. Required for any schema change in a deployed Docker environment. |
| Celery | 5.4.x | Background job queue | Industry standard for Python background processing. Handles 1,000+ row Excel jobs without blocking the API. Provides retry logic, task state tracking, and ETA scheduling for Apollo rate-limit backoff. |
| Redis | 7.x | Celery broker + result backend | Fastest broker for Celery. Single service handles both message brokering and job result storage. Redis 7 adds stream-based ACLs. Use `redis:7-alpine` in Docker. |
| React | 18.x | Frontend UI | Hooks-based, large ecosystem, works well for the upload/status/download workflow. Internal tool — no SSR needed. |
| Vite | 5.x | Frontend build tool | Fast dev server and HMR. Replaces Create React App. Standard choice for new React projects in 2025. |
| Docker Compose | 2.x | Deployment orchestration | Single `docker-compose.yml` that wires app, worker, postgres, and redis. Meets the "Docker-based, deployable anywhere" constraint from PROJECT.md. |

### Supporting Libraries

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| asyncpg | 0.29.x | PostgreSQL async driver | Required by SQLAlchemy 2.x async engine. Lower-level than psycopg3 but more mature in the SQLAlchemy ecosystem as of mid-2025. |
| openpyxl | 3.1.x | Excel read/write | Native .xlsx support. Use for reading uploaded files and generating enriched output files. `read_only=True` mode for memory-efficient parsing of large files. |
| pandas | 2.2.x | Column type detection heuristics | Use only for the column auto-detection step (dtype inference, regex pattern matching across columns). Do not use for the main enrichment pipeline — openpyxl is more memory-efficient for row-level streaming. |
| httpx | 0.27.x | Apollo API HTTP client | Async HTTP client. Use `httpx.AsyncClient` with connection pooling and timeout configuration for Apollo API calls. Supports retry via `tenacity`. Never use `requests` (sync only) in an async FastAPI/Celery context. |
| tenacity | 8.x | Retry logic for Apollo API | Declarative retry with exponential backoff. Critical for Apollo rate-limit (429) and transient error handling. Wrap every Apollo API call with a `@retry` decorator. |
| passlib[bcrypt] | 1.7.x | Password hashing | bcrypt is the correct algorithm for password storage. `passlib` provides a stable, well-audited interface. |
| python-jose[cryptography] | 3.3.x | JWT token generation/validation | Industry-standard JWT library for Python. Use HS256 algorithm for internal tool simplicity. |
| pydantic-settings | 2.x | Environment/config management | Reads from `.env` and environment variables with type validation. Replaces manual `os.getenv` calls. Ships separately from Pydantic v2. |
| flower | 2.0.x | Celery task monitoring UI | Web UI for monitoring Celery worker state, task queues, retries, and failures. Run as a separate Docker service in `docker-compose.yml`. Essential for debugging batch jobs. |
| python-multipart | 0.0.9 | File upload support | Required by FastAPI for `UploadFile` (multipart form data). Must be installed — FastAPI does not bundle it. |
| alembic | 1.13.x | Database migration runner | Already listed above; called out here because it must be in the app image (not just dev deps) to run `alembic upgrade head` on container startup. |

### Development Tools

| Tool | Purpose | Notes |
|------|---------|-------|
| uv | Fast Python package manager and virtualenv | Replaces pip + virtualenv. Significantly faster installs. Use `uv pip install` and `uv venv`. Compatible with `requirements.txt` and `pyproject.toml`. |
| pytest + pytest-asyncio | Test runner with async support | Required for testing FastAPI endpoints and Celery tasks that use async code. Use `pytest-asyncio` in `auto` mode. |
| httpx (test client) | API integration testing | `httpx.AsyncClient(app=app)` replaces `TestClient` for async FastAPI tests. |
| Ruff | Linter + formatter | Replaces flake8 + black + isort in a single tool. Extremely fast. Use as pre-commit hook and in CI. |
| pre-commit | Git hook manager | Runs Ruff before every commit. Prevents style drift in a team environment. |
| docker-compose watch | Hot-reload in Docker dev mode | Compose v2.22+ supports `watch` mode — auto-rebuilds or syncs files on change. Eliminates the need for a separate file-watching tool in development. |

---

## Installation

```bash
# Create virtualenv and install core backend dependencies
uv venv .venv
source .venv/bin/activate   # or .venv\Scripts\activate on Windows
uv pip install \
  "fastapi[standard]>=0.115.0" \
  "uvicorn[standard]>=0.30.0" \
  "sqlalchemy[asyncio]>=2.0.0" \
  "alembic>=1.13.0" \
  "asyncpg>=0.29.0" \
  "celery[redis]>=5.4.0" \
  "redis>=5.0.0" \
  "openpyxl>=3.1.0" \
  "pandas>=2.2.0" \
  "httpx>=0.27.0" \
  "tenacity>=8.0.0" \
  "passlib[bcrypt]>=1.7.4" \
  "python-jose[cryptography]>=3.3.0" \
  "pydantic-settings>=2.0.0" \
  "python-multipart>=0.0.9" \
  "flower>=2.0.0"

# Dev/test dependencies
uv pip install \
  "pytest>=8.0.0" \
  "pytest-asyncio>=0.23.0" \
  "ruff>=0.4.0"

# Frontend
npm create vite@latest frontend -- --template react-ts
cd frontend && npm install
```

```yaml
# docker-compose.yml (service overview)
services:
  db:
    image: postgres:16-alpine
  redis:
    image: redis:7-alpine
  api:
    build: .
    depends_on: [db, redis]
  worker:
    build: .
    command: celery -A app.worker worker --loglevel=info --concurrency=4
    depends_on: [db, redis]
  flower:
    build: .
    command: celery -A app.worker flower --port=5555
    depends_on: [redis]
```

---

## Alternatives Considered

| Category | Recommended | Alternative | Why Not |
|----------|-------------|-------------|---------|
| Background jobs | Celery + Redis | FastAPI BackgroundTasks | `BackgroundTasks` runs in the same process — blocks the API worker for 1,000+ row jobs, no retry logic, no task state persistence. Not suitable for this workload. |
| Background jobs | Celery + Redis | ARQ (asyncio job queue) | ARQ is async-native and lighter than Celery, but has a smaller community and fewer production deployments. Celery's retry/monitoring ecosystem (Flower) is more mature. |
| Background jobs | Celery + Redis | RQ (Redis Queue) | Simpler than Celery but lacks periodic task scheduling, chord/group primitives, and robust retry configuration. |
| Excel processing | openpyxl | xlrd/xlwt | xlrd 2.x dropped .xlsx support (reads .xls only). xlwt is unmaintained. openpyxl is the only correct choice for .xlsx. |
| Excel processing | openpyxl | pandas (primary) | pandas loads the entire file into memory. For 1,000+ row files that's acceptable, but openpyxl's `read_only` mode streams row-by-row, which is more predictable for large uploads. Use pandas for detection only. |
| Database | PostgreSQL | SQLite | SQLite cannot handle concurrent writers safely — multiple users running jobs simultaneously would cause write contention. Not suitable. |
| Database | PostgreSQL | MySQL/MariaDB | PostgreSQL's JSONB (for storing raw Apollo API responses) and its superior UNIQUE constraint handling for deduplication are the deciding factors. |
| ORM | SQLAlchemy 2.x | Tortoise-ORM | Tortoise is async-native but smaller ecosystem, fewer SQLAlchemy-compatible tools, less Alembic integration. SQLAlchemy 2.x async is mature enough. |
| HTTP client | httpx | aiohttp | httpx has a cleaner API, better test support (`httpx.MockTransport`), and is the FastAPI-recommended client. aiohttp is fine but httpx is the cleaner choice. |
| Auth | passlib + python-jose | Authlib | Authlib is correct for OAuth flows. For simple email/password JWT auth (PROJECT.md explicitly rules out OAuth/SSO), passlib + python-jose is simpler and has zero unnecessary surface area. |
| Frontend | React + Vite | Next.js | No SSR needed for an internal tool. Next.js adds complexity (server components, edge runtime) that provides no value here. React + Vite is lighter and faster to develop. |
| Frontend | React + Vite | Vue + Vite | Both are valid. React is chosen for broader team familiarity in the sales-tool ecosystem. No technical blocker with Vue. |
| Package manager | uv | pip / poetry | uv is 10-100x faster than pip for installs and fully compatible with `requirements.txt`. Poetry adds lockfile management that uv also provides. uv is the 2025 standard. |

---

## What NOT to Use

| Technology | Why to Avoid |
|------------|-------------|
| FastAPI `BackgroundTasks` for enrichment jobs | Runs in the API server process. A 1,000-row job will hold the worker thread, causing timeouts and blocking other requests. Use Celery. |
| `requests` library | Synchronous. Will block the async event loop when called from FastAPI or Celery async tasks. Use `httpx` exclusively. |
| xlrd / xlwt | xlrd 2.x reads .xls only (not .xlsx). xlwt cannot write .xlsx. Both are effectively unmaintained for modern Excel files. |
| Synchronous SQLAlchemy 1.x style | SQLAlchemy 2.x introduced a new async API and a stricter query interface. Using the legacy 1.x `Session` and `Query` patterns in an async codebase causes subtle bugs and deprecation warnings. |
| SQLite | Write-lock contention under concurrent users. No JSONB. Not suitable for a multi-user production deployment even if small. |
| Celery with RabbitMQ broker | RabbitMQ adds operational complexity (separate AMQP broker to manage). Redis already exists for result storage — using it as the broker too is simpler and sufficient for this workload. |
| `python-multipart` omission | FastAPI silently fails to parse file uploads without this package. It does not auto-install as a dependency of FastAPI. Forgetting it causes a confusing 422 error on upload endpoints. |
| JWT with RS256 (asymmetric keys) | RS256 requires key rotation infrastructure. For an internal team tool with a single server, HS256 (shared secret) is correct and far simpler to operate. |
| Pandas for row-level enrichment pipeline | Pandas DataFrames hold all rows in memory and add a serialization step when passing data to Celery tasks. Use openpyxl to extract row data as plain Python dicts, serialize those to the Celery task, and reassemble the output file with openpyxl. |
| Docker `--privileged` or host networking | Not needed for this stack. Use named Docker networks and explicit port mappings. Reduces attack surface. |

---

## Confidence Notes

| Area | Confidence | Basis |
|------|-----------|-------|
| FastAPI version (0.135.3) | HIGH | Confirmed via official FastAPI release notes page, fetched 2026-04-06 |
| Celery 5.4.x | MEDIUM | Training data (cutoff Aug 2025). Celery 5.4 was released in 2024. Validate with `pip index versions celery` before pinning. |
| openpyxl 3.1.x | MEDIUM | Training data. Stable series since 2023. Validate on PyPI before pinning. |
| SQLAlchemy 2.0.x | MEDIUM | Training data. SQLAlchemy 2.0 released 2023, actively maintained. Validate before pinning. |
| Redis 7.x | MEDIUM | Training data. Redis 7 released 2022, widely deployed. Redis 8 may exist — validate. |
| PostgreSQL 16 | MEDIUM | Training data. pg16 released Sept 2023, pg17 exists as of late 2024 — either works, use 16 for stability. |
| React 18.x | MEDIUM | Training data. React 19 released Dec 2024 — may be appropriate; validate ecosystem compatibility before upgrading. |
| uv as package manager | HIGH | uv reached 1.0 in mid-2024, widely adopted by 2025. Recommendation is well-established. |

---

## Sources

- FastAPI release notes (version confirmed): https://fastapi.tiangolo.com/release-notes/
- FastAPI file upload requirements (python-multipart): https://fastapi.tiangolo.com/tutorial/request-files/
- Celery documentation: https://docs.celeryq.dev/en/stable/
- openpyxl documentation: https://openpyxl.readthedocs.io/en/stable/
- SQLAlchemy 2.0 async documentation: https://docs.sqlalchemy.org/en/20/orm/extensions/asyncio.html
- Apollo People Enrichment API: https://apolloio.github.io/apollo-api-docs/#people-enrichment
- uv documentation: https://docs.astral.sh/uv/
- Ruff linter: https://docs.astral.sh/ruff/
- tenacity retry library: https://tenacity.readthedocs.io/en/latest/

**Note:** All sources except the FastAPI release notes were blocked during this research session. Versions marked MEDIUM confidence should be validated against their respective PyPI pages or official changelogs before the first dependency install.
