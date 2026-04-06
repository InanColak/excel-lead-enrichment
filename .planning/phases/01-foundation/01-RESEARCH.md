# Phase 1: Foundation - Research

**Researched:** 2026-04-06
**Domain:** Docker infrastructure, FastAPI application skeleton, PostgreSQL + SQLAlchemy async, JWT authentication, admin management
**Confidence:** HIGH

## Summary

Phase 1 establishes the full running skeleton: Docker Compose orchestration (API, Celery worker, PostgreSQL, Redis, Flower), async FastAPI application with Swagger UI, SQLAlchemy 2.0 async ORM with Alembic migrations, JWT authentication (access + refresh tokens with Redis-based revocation), admin bootstrap via CLI, Apollo API key configuration endpoint, and team management. This is a greenfield project -- all patterns established here become the template for subsequent phases.

Two critical deviations from CLAUDE.md's library recommendations surfaced during research: (1) `passlib` is unmaintained and broken with bcrypt 5.x -- FastAPI's official docs now recommend `pwdlib` as the replacement; (2) `python-jose` is abandoned (last release 2021) -- FastAPI's official docs now recommend `PyJWT`. Both substitutions are drop-in compatible and represent the current ecosystem standard.

**Primary recommendation:** Follow all CONTEXT.md decisions exactly. Use `pwdlib[bcrypt]` instead of `passlib[bcrypt]` and `PyJWT` instead of `python-jose[cryptography]` -- these are the current FastAPI-recommended libraries that replaced the unmaintained ones listed in CLAUDE.md.

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions
- **D-01:** Store raw Apollo API responses as a JSONB column alongside extracted email/phone columns. JSONB is internal storage only -- the enriched Excel output only shows email, phone, and status columns. JSONB preserves the full response for future field extraction (v2 requirements).
- **D-02:** Email address is the UNIQUE constraint for contact deduplication. Simple and effective for v1.
- **D-03:** Phase 1 creates only the tables it needs: users, contacts, and api_config. Future phases add their own tables via Alembic migrations. No premature schema.
- **D-04:** UUID primary keys on all tables. Consistent across the entire project, aligns with the row-UUID tracking requirement (ENRICH-01).
- **D-05:** Short-lived access tokens (30 min) with long-lived refresh tokens (7 days). Standard JWT security pattern.
- **D-06:** First admin user created via CLI seed command (e.g., `python manage.py create-admin`). Credentials sourced from environment variables. Clean separation from the API.
- **D-07:** Token revocation via Redis blocklist. When an admin removes a user, their active token JTIs are added to a Redis blocklist. Every request checks the blocklist. TTL auto-cleans expired entries.
- **D-08:** Simple `is_admin` boolean flag on the user table. Admin = manage users + API key config. Non-admin = everything else. No role/permission tables needed for v1.
- **D-09:** Feature-based module layout: `app/auth/`, `app/contacts/`, `app/admin/`, `app/jobs/`. Each module contains its own routes, models, schemas, and services.
- **D-10:** Configuration via pydantic-settings + `.env` file. Single Settings class reads from `.env` locally and environment variables in Docker. Type-validated.
- **D-11:** Test directory mirrors app structure: `tests/auth/`, `tests/contacts/`, `tests/admin/`, etc.
- **D-12:** Include Flower (Celery monitoring UI) in docker-compose.yml from Phase 1.
- **D-13:** Dev/prod split via Docker Compose override files. Base `docker-compose.yml` for production, `docker-compose.override.yml` for dev extras.
- **D-14:** Auto-migrate on startup. API container entrypoint runs `alembic upgrade head` before starting the server.
- **D-15:** Dedicated `/health` endpoint on the API that checks DB + Redis connectivity. Docker Compose healthcheck hits this endpoint.

### Claude's Discretion
No areas deferred to Claude's discretion -- all gray areas were decided by the user.

### Deferred Ideas (OUT OF SCOPE)
None -- discussion stayed within phase scope.
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| INFRA-01 | Application runs as a Docker Compose deployment (API, worker, database, queue) | Docker Compose v5.1.0 available locally. D-12 adds Flower as 5th service. D-13 defines dev/prod split. D-14 defines auto-migrate entrypoint. D-15 defines healthcheck. |
| INFRA-02 | API auto-generates interactive Swagger UI documentation for all endpoints | FastAPI generates Swagger UI automatically at `/docs`. No additional configuration needed -- just define route handlers with type-annotated parameters and Pydantic response models. |
| INFRA-03 | API is designed for future integration with a unified company dashboard via API gateway pattern | Use API versioning prefix (`/api/v1/`) and CORS middleware configuration. Structural concern -- no additional libraries needed. |
| AUTH-01 | User can log in with email and password | pwdlib[bcrypt] for password hashing, PyJWT for token generation. D-05 defines token lifetimes. D-08 defines user model shape. |
| AUTH-02 | Admin can configure the shared Apollo API key via API endpoint (without redeployment) | api_config table (D-03) stores key-value pairs. Admin-only endpoint protected by `is_admin` check (D-08). Key stored encrypted or as plaintext with DB access controls. |
| AUTH-03 | Admin can add and remove team members | Admin CRUD endpoints. D-07 defines token revocation via Redis blocklist on user removal. D-06 defines initial admin bootstrap. |
</phase_requirements>

## Project Constraints (from CLAUDE.md)

These are hard constraints that must be followed:

- **Python 3.12** runtime (use `python:3.12-slim` Docker base image, NOT the local 3.14)
- **FastAPI** with `>=0.115,<1.0` version constraint, Pydantic v2 required
- **SQLAlchemy 2.x async API only** -- never use 1.x `Session`/`Query` patterns
- **Celery + Redis** for background jobs -- never use FastAPI `BackgroundTasks`
- **httpx only** -- never use `requests` library
- **openpyxl** for Excel -- never use xlrd/xlwt
- **HS256** for JWT (not RS256)
- **No SQLite** -- PostgreSQL only
- **No RabbitMQ** -- Redis as Celery broker
- **No Docker `--privileged` or host networking**
- **uv** as package manager (not pip/poetry)
- **Ruff** as linter/formatter
- **pytest + pytest-asyncio** for testing

## Standard Stack

### Core (Phase 1)

| Library | Version | Purpose | Why Standard | Source |
|---------|---------|---------|--------------|--------|
| FastAPI | >=0.115,<1.0 (latest: 0.135.3) | API framework | Async-native, auto Swagger UI, Pydantic v2 built-in | [VERIFIED: PyPI] |
| uvicorn[standard] | 0.44.0 | ASGI server | Production server for FastAPI, includes uvloop | [VERIFIED: PyPI] |
| SQLAlchemy | 2.0.49 | ORM (async) | 2.x async engine with asyncpg driver | [VERIFIED: PyPI] |
| asyncpg | 0.31.0 | PostgreSQL async driver | Required by SQLAlchemy async engine | [VERIFIED: PyPI] |
| Alembic | 1.18.4 | DB migrations | Pairs with SQLAlchemy 2.x, async template support | [VERIFIED: PyPI] |
| Celery | 5.6.3 | Background job queue | Retry logic, task state tracking, rate-limit backoff | [VERIFIED: PyPI] |
| redis | 7.4.0 | Python Redis client | Celery broker + result backend + token blocklist | [VERIFIED: PyPI] |
| pydantic | 2.12.5 | Data validation | Core dependency of FastAPI, schema definitions | [VERIFIED: PyPI] |
| pydantic-settings | 2.13.1 | Config management | Reads .env + env vars with type validation (D-10) | [VERIFIED: PyPI] |
| PyJWT | 2.12.1 | JWT token generation | **Replaces python-jose** -- actively maintained, FastAPI-recommended | [VERIFIED: PyPI + FastAPI docs] |
| pwdlib[bcrypt] | 0.3.0 | Password hashing | **Replaces passlib** -- actively maintained, FastAPI-recommended | [VERIFIED: PyPI + FastAPI docs] |
| python-multipart | 0.0.24 | File upload support | Required by FastAPI for UploadFile (multipart form data) | [VERIFIED: PyPI] |
| httpx | 0.28.1 | HTTP client | Async client for Apollo API calls (future phases) | [VERIFIED: PyPI] |
| tenacity | 9.1.4 | Retry logic | Exponential backoff for API calls | [VERIFIED: PyPI] |
| flower | 2.0.1 | Celery monitoring UI | Web UI for worker/task monitoring (D-12) | [VERIFIED: PyPI] |

### Development

| Tool | Version | Purpose | Source |
|------|---------|---------|--------|
| pytest | 8.x or 9.x | Test runner | [VERIFIED: PyPI -- latest 9.0.2] |
| pytest-asyncio | 1.3.0 | Async test support | [VERIFIED: PyPI] |
| httpx | 0.28.1 | Test client (AsyncClient) | [VERIFIED: PyPI] |
| ruff | 0.15.9 | Linter + formatter | [VERIFIED: PyPI] |
| pre-commit | 4.5.1 | Git hook manager | [VERIFIED: PyPI] |

### Docker Images

| Image | Tag | Purpose | Source |
|-------|-----|---------|--------|
| python | 3.12-slim | API + worker base | [ASSUMED -- standard Docker Hub image] |
| postgres | 16-alpine | Database | [ASSUMED -- standard, per CLAUDE.md] |
| redis | 7-alpine | Broker + cache + blocklist | [ASSUMED -- per CLAUDE.md] |

### CRITICAL: Library Substitutions from CLAUDE.md

CLAUDE.md recommends `passlib[bcrypt]` and `python-jose[cryptography]`. **Both are unmaintained and must be replaced:**

| CLAUDE.md Says | Use Instead | Why |
|----------------|-------------|-----|
| passlib[bcrypt] 1.7.x | pwdlib[bcrypt] 0.3.0 | passlib last released 2020, broken with bcrypt 5.x. FastAPI official docs switched to pwdlib. [CITED: fastapi.tiangolo.com/tutorial/security/oauth2-jwt/] |
| python-jose[cryptography] 3.3.x | PyJWT 2.12.1 | python-jose last released 2021, unmaintained. FastAPI official docs switched to PyJWT. [CITED: fastapi.tiangolo.com/tutorial/security/oauth2-jwt/] |

### Version Updates from CLAUDE.md

CLAUDE.md version pins are stale. Current verified versions:

| CLAUDE.md Version | Current Version | Delta |
|-------------------|-----------------|-------|
| Celery 5.4.x | 5.6.3 | Minor version bump, 5.5 and 5.6 released since |
| uvicorn 0.30.x | 0.44.0 | Significant version bump |
| Alembic 1.13.x | 1.18.4 | Multiple minor versions |
| httpx 0.27.x | 0.28.1 | Minor bump |
| asyncpg 0.29.x | 0.31.0 | Two minor versions |
| tenacity 8.x | 9.1.4 | Major version bump |
| python-multipart 0.0.9 | 0.0.24 | Many patches |

**Recommendation:** Pin to current verified versions in requirements. Use `>=current,<next_major` style constraints.

### Installation

```bash
# In Docker (Dockerfile) -- use uv for fast installs
FROM python:3.12-slim
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

# Core dependencies
uv pip install --system \
  "fastapi>=0.115,<1.0" \
  "uvicorn[standard]==0.44.0" \
  "sqlalchemy==2.0.49" \
  "asyncpg==0.31.0" \
  "alembic==1.18.4" \
  "celery==5.6.3" \
  "redis==7.4.0" \
  "pydantic-settings==2.13.1" \
  "pyjwt==2.12.1" \
  "pwdlib[bcrypt]==0.3.0" \
  "python-multipart==0.0.24" \
  "httpx==0.28.1" \
  "tenacity==9.1.4" \
  "flower==2.0.1"
```

## Architecture Patterns

### Recommended Project Structure (per D-09, D-10, D-11)

```
leadenrich/
├── docker-compose.yml           # Production services
├── docker-compose.override.yml  # Dev overrides (D-13)
├── Dockerfile                   # Multi-stage: base, dev, prod
├── pyproject.toml               # Project metadata + dependencies
├── alembic.ini                  # Alembic config
├── alembic/
│   ├── env.py                   # Async migration env
│   └── versions/                # Migration files
├── manage.py                    # CLI commands (create-admin, etc.) (D-06)
├── app/
│   ├── __init__.py
│   ├── main.py                  # FastAPI app creation, router includes
│   ├── config.py                # pydantic-settings Settings class (D-10)
│   ├── database.py              # Async engine + session factory
│   ├── deps.py                  # Shared FastAPI dependencies (get_db, get_current_user)
│   ├── models/
│   │   └── base.py              # Declarative base with UUID PK mixin (D-04)
│   ├── auth/
│   │   ├── __init__.py
│   │   ├── routes.py            # /auth/login, /auth/refresh, /auth/logout
│   │   ├── models.py            # User model
│   │   ├── schemas.py           # Pydantic request/response schemas
│   │   └── service.py           # Password hashing, JWT creation, blocklist checks
│   ├── admin/
│   │   ├── __init__.py
│   │   ├── routes.py            # /admin/users, /admin/config
│   │   ├── models.py            # ApiConfig model
│   │   ├── schemas.py           # Admin schemas
│   │   └── service.py           # User CRUD, API key management
│   ├── contacts/
│   │   ├── __init__.py
│   │   └── models.py            # Contact model (schema only in Phase 1)
│   └── health/
│       ├── __init__.py
│       └── routes.py            # /health endpoint (D-15)
├── tests/
│   ├── conftest.py              # Shared fixtures (async client, test DB)
│   ├── auth/
│   │   ├── test_login.py
│   │   ├── test_refresh.py
│   │   └── test_revocation.py
│   └── admin/
│       ├── test_users.py
│       └── test_config.py
└── .env.example                 # Template for required env vars
```

### Pattern 1: Async Database Session Dependency

**What:** FastAPI dependency injection for async SQLAlchemy sessions.
**When to use:** Every route that touches the database.

```python
# app/database.py
# Source: SQLAlchemy 2.0 async docs [CITED: docs.sqlalchemy.org/en/20/orm/extensions/asyncio.html]
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession

engine = create_async_engine(
    settings.database_url,  # postgresql+asyncpg://...
    echo=False,
    pool_size=5,
    max_overflow=10,
)
async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

# app/deps.py
from collections.abc import AsyncGenerator

async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with async_session() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
```

### Pattern 2: JWT Authentication with Redis Blocklist (D-05, D-07)

**What:** Access/refresh token pair with JTI-based revocation.
**When to use:** All authenticated endpoints.

```python
# app/auth/service.py
# Source: FastAPI security docs [CITED: fastapi.tiangolo.com/tutorial/security/oauth2-jwt/]
import jwt
import uuid
from datetime import datetime, timedelta, timezone

def create_access_token(user_id: str, is_admin: bool) -> str:
    jti = str(uuid.uuid4())
    payload = {
        "sub": user_id,
        "jti": jti,
        "is_admin": is_admin,
        "exp": datetime.now(timezone.utc) + timedelta(minutes=30),
        "type": "access",
    }
    return jwt.encode(payload, settings.secret_key, algorithm="HS256")

def create_refresh_token(user_id: str) -> str:
    jti = str(uuid.uuid4())
    payload = {
        "sub": user_id,
        "jti": jti,
        "exp": datetime.now(timezone.utc) + timedelta(days=7),
        "type": "refresh",
    }
    return jwt.encode(payload, settings.secret_key, algorithm="HS256")

# Redis blocklist check
async def is_token_revoked(jti: str, redis_client) -> bool:
    return await redis_client.exists(f"blocklist:{jti}")

async def revoke_token(jti: str, exp: datetime, redis_client) -> None:
    ttl = int((exp - datetime.now(timezone.utc)).total_seconds())
    if ttl > 0:
        await redis_client.setex(f"blocklist:{jti}", ttl, "revoked")
```

### Pattern 3: UUID Primary Key Mixin (D-04)

**What:** Consistent UUID PKs across all models.
**When to use:** Every SQLAlchemy model.

```python
# app/models/base.py
# Source: SQLAlchemy 2.0 docs [CITED: docs.sqlalchemy.org/en/20/]
import uuid
from sqlalchemy import Column
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

class Base(DeclarativeBase):
    pass

class UUIDMixin:
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
```

### Pattern 4: Alembic Async Migration Setup

**What:** Async-compatible Alembic env.py for PostgreSQL+asyncpg.
**When to use:** Database migration management.

```python
# alembic/env.py (key parts)
# Source: Alembic async template [CITED: alembic.sqlalchemy.org/en/latest/cookbook.html]
from alembic import context
from sqlalchemy.ext.asyncio import async_engine_from_config
import asyncio

# Import all models so autogenerate detects them
from app.models.base import Base
from app.auth.models import User
from app.admin.models import ApiConfig
from app.contacts.models import Contact

target_metadata = Base.metadata

def do_run_migrations(connection):
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()

async def run_async_migrations():
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section),
        prefix="sqlalchemy.",
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()

def run_migrations_online():
    asyncio.run(run_async_migrations())
```

### Pattern 5: Docker Compose Healthcheck (D-15)

**What:** Health endpoint that verifies DB + Redis connectivity.
**When to use:** Container orchestration readiness checks.

```python
# app/health/routes.py
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text

router = APIRouter()

@router.get("/health")
async def health_check(db: AsyncSession = Depends(get_db)):
    # Check DB
    await db.execute(text("SELECT 1"))
    # Check Redis
    await redis_client.ping()
    return {"status": "healthy"}
```

### Pattern 6: pydantic-settings Configuration (D-10)

**What:** Type-validated configuration from environment.
**When to use:** All application configuration.

```python
# app/config.py
# Source: pydantic-settings docs [CITED: docs.pydantic.dev/latest/concepts/pydantic_settings/]
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    # Database
    database_url: str = "postgresql+asyncpg://postgres:postgres@db:5432/leadenrich"

    # Redis
    redis_url: str = "redis://redis:6379/0"

    # JWT
    secret_key: str
    access_token_expire_minutes: int = 30
    refresh_token_expire_days: int = 7

    # App
    debug: bool = False

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}

settings = Settings()
```

### Anti-Patterns to Avoid

- **Synchronous SQLAlchemy 1.x patterns:** Never use `Session()`, `Query()`, or `engine.execute()`. Always use 2.x `select()`, `async_session`, and `await session.execute()`. [CITED: CLAUDE.md "What NOT to Use"]
- **`requests` library:** Never import `requests`. Use `httpx` for all HTTP calls. [CITED: CLAUDE.md]
- **FastAPI BackgroundTasks for heavy work:** Never use for enrichment jobs. Use Celery. [CITED: CLAUDE.md]
- **Storing JWT secret in code:** Must come from environment variable via pydantic-settings.
- **Global mutable state:** No module-level mutable dicts/lists shared between requests. Use Redis or database.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Password hashing | Custom bcrypt wrapper | pwdlib[bcrypt] | Salt generation, timing-safe comparison, future algorithm migration |
| JWT creation/validation | Manual base64 + HMAC | PyJWT | Token expiry validation, claim parsing, algorithm verification |
| Database migrations | Raw SQL scripts | Alembic | Autogenerate from models, version tracking, rollback support |
| Config management | os.getenv() wrappers | pydantic-settings | Type coercion, validation, .env file support, nested config |
| Retry logic | While loops with sleep | tenacity | Exponential backoff, jitter, per-exception retry policies |
| API documentation | Manual OpenAPI YAML | FastAPI auto-generation | Stays in sync with code, zero maintenance |
| ASGI server | Custom asyncio server | uvicorn[standard] | Production-grade, graceful shutdown, worker management |

**Key insight:** Phase 1 is the foundation layer. Every hand-rolled solution here becomes tech debt that all 3 subsequent phases inherit. Use battle-tested libraries.

## Common Pitfalls

### Pitfall 1: Alembic + Async Engine URL Mismatch
**What goes wrong:** Alembic uses `sqlalchemy.url` from `alembic.ini` which defaults to a synchronous URL format. Async engine requires `postgresql+asyncpg://` prefix.
**Why it happens:** Alembic's default template assumes sync. The async template must be used at `alembic init` time.
**How to avoid:** Initialize with `alembic init -t async alembic`. Override the URL in `env.py` to read from `Settings` rather than `alembic.ini`.
**Warning signs:** `ModuleNotFoundError: No module named 'psycopg2'` when running migrations.

### Pitfall 2: Missing python-multipart
**What goes wrong:** File upload endpoints return 422 Unprocessable Entity with no helpful error message.
**Why it happens:** FastAPI requires `python-multipart` for form data parsing but does not declare it as a hard dependency.
**How to avoid:** Always include `python-multipart` in requirements. Test file upload endpoints in Phase 1 even though file processing is Phase 2.
**Warning signs:** 422 errors on any endpoint that accepts `Form()` or `UploadFile`.

### Pitfall 3: UUID Serialization in JSON Responses
**What goes wrong:** Pydantic models with UUID fields fail to serialize to JSON, or UUIDs appear as objects instead of strings.
**Why it happens:** Default JSON encoder does not handle `uuid.UUID`.
**How to avoid:** Use Pydantic v2's built-in UUID support. In schemas, annotate as `uuid.UUID` and Pydantic handles serialization automatically. In SQLAlchemy, use `UUID(as_uuid=True)`.
**Warning signs:** `TypeError: Object of type UUID is not JSON serializable`.

### Pitfall 4: Celery Tasks Calling Async Code
**What goes wrong:** `RuntimeError: no current event loop` or tasks hang indefinitely.
**Why it happens:** Celery workers run synchronously by default. Calling `await` inside a Celery task fails.
**How to avoid:** For Phase 1, Celery worker is present but has no tasks yet. When tasks are added in later phases, use `asgiref.sync.async_to_sync` or run async code inside `asyncio.run()` within the Celery task. Alternatively, use synchronous SQLAlchemy sessions inside Celery tasks (Celery has its own concurrency model separate from the async API server).
**Warning signs:** Worker starts but tasks never complete or raise event loop errors.

### Pitfall 5: Docker Compose Service Startup Order
**What goes wrong:** API container starts before PostgreSQL is ready, `alembic upgrade head` fails.
**Why it happens:** `depends_on` only waits for container start, not service readiness.
**How to avoid:** Use `depends_on` with `condition: service_healthy`. Define healthchecks on postgres (`pg_isready`) and redis (`redis-cli ping`). The API entrypoint script should also retry the migration command.
**Warning signs:** Intermittent startup failures, especially on first `docker compose up`.

### Pitfall 6: Token Revocation Race Condition
**What goes wrong:** Admin removes user, but user's existing token still works briefly.
**Why it happens:** If the blocklist write and the token check happen on different Redis connections without synchronization.
**How to avoid:** Revocation should block (await) on the Redis write before returning success to the admin. Redis SET is atomic and immediately visible to subsequent GET calls on the same or different connections.
**Warning signs:** Removed users can still make one more request after removal.

### Pitfall 7: passlib/python-jose Import Errors on Modern Python
**What goes wrong:** `ImportError` or `AttributeError` at runtime.
**Why it happens:** passlib is broken with bcrypt>=4.1 and python-jose has unpatched security issues.
**How to avoid:** Use pwdlib and PyJWT as documented in this research. Do not install passlib or python-jose.
**Warning signs:** `AttributeError: module 'bcrypt' has no attribute '__about__'` from passlib.

## Code Examples

### Docker Compose Services (D-12, D-13, D-14, D-15)

```yaml
# docker-compose.yml
# Source: Docker Compose specification [ASSUMED -- standard patterns]
services:
  db:
    image: postgres:16-alpine
    environment:
      POSTGRES_USER: leadenrich
      POSTGRES_PASSWORD: ${DB_PASSWORD}
      POSTGRES_DB: leadenrich
    volumes:
      - postgres_data:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U leadenrich"]
      interval: 5s
      timeout: 3s
      retries: 5

  redis:
    image: redis:7-alpine
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 5s
      timeout: 3s
      retries: 5

  api:
    build:
      context: .
      target: production
    environment:
      DATABASE_URL: postgresql+asyncpg://leadenrich:${DB_PASSWORD}@db:5432/leadenrich
      REDIS_URL: redis://redis:6379/0
      SECRET_KEY: ${SECRET_KEY}
    ports:
      - "8000:8000"
    depends_on:
      db:
        condition: service_healthy
      redis:
        condition: service_healthy
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8000/health"]
      interval: 10s
      timeout: 5s
      retries: 3

  worker:
    build:
      context: .
      target: production
    command: celery -A app.celery_app worker --loglevel=info
    environment:
      DATABASE_URL: postgresql+asyncpg://leadenrich:${DB_PASSWORD}@db:5432/leadenrich
      REDIS_URL: redis://redis:6379/0
    depends_on:
      db:
        condition: service_healthy
      redis:
        condition: service_healthy

  flower:
    build:
      context: .
      target: production
    command: celery -A app.celery_app flower --port=5555
    ports:
      - "5555:5555"
    depends_on:
      - worker

volumes:
  postgres_data:
```

### Docker Entrypoint Script (D-14)

```bash
#!/bin/bash
# entrypoint.sh -- runs migrations then starts server
set -e

echo "Running database migrations..."
alembic upgrade head

echo "Starting server..."
exec uvicorn app.main:app --host 0.0.0.0 --port 8000
```

### Admin Seed Command (D-06)

```python
# manage.py
# Source: pattern from FastAPI ecosystem [ASSUMED]
import asyncio
import sys
from app.config import settings
from app.database import async_session
from app.auth.service import hash_password
from app.auth.models import User

async def create_admin():
    email = settings.admin_email  # from env
    password = settings.admin_password  # from env
    async with async_session() as session:
        user = User(
            email=email,
            hashed_password=hash_password(password),
            is_admin=True,
            is_active=True,
        )
        session.add(user)
        await session.commit()
        print(f"Admin user created: {email}")

if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "create-admin":
        asyncio.run(create_admin())
```

### Password Hashing with pwdlib

```python
# app/auth/service.py
# Source: FastAPI official docs [CITED: fastapi.tiangolo.com/tutorial/security/oauth2-jwt/]
from pwdlib import PasswordHash

password_hash = PasswordHash.recommended()
# For bcrypt specifically (per CLAUDE.md preference):
# from pwdlib.hashers.bcrypt import BcryptHasher
# password_hash = PasswordHash((BcryptHasher(),))

def hash_password(password: str) -> str:
    return password_hash.hash(password)

def verify_password(plain_password: str, hashed_password: str) -> bool:
    return password_hash.verify(plain_password, hashed_password)
```

### API Versioning Prefix (INFRA-03)

```python
# app/main.py
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(title="LeadEnrich API", version="1.0.0")

# CORS for future dashboard integration
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Restrict in production
    allow_methods=["*"],
    allow_headers=["*"],
)

# Health endpoint at root (no version prefix -- for Docker healthcheck)
app.include_router(health_router)

# Versioned API routes
app.include_router(auth_router, prefix="/api/v1/auth", tags=["auth"])
app.include_router(admin_router, prefix="/api/v1/admin", tags=["admin"])
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| passlib[bcrypt] for password hashing | pwdlib[bcrypt] or pwdlib[argon2] | 2024-2025 | passlib unmaintained since 2020, broken with bcrypt 5.x [CITED: github.com/fastapi/fastapi/discussions/11773] |
| python-jose for JWT | PyJWT | 2024-2025 | python-jose unmaintained since 2021, FastAPI docs updated [CITED: github.com/fastapi/fastapi/pull/11589] |
| SQLAlchemy 1.x Session/Query | SQLAlchemy 2.x select() + AsyncSession | 2023 | New API is async-native, type-safe [CITED: docs.sqlalchemy.org/en/20/] |
| pip for dependency management | uv | 2024 | 10-100x faster, compatible with requirements.txt [CITED: docs.astral.sh/uv/] |
| flake8 + black + isort | ruff | 2023-2024 | Single tool, much faster [CITED: docs.astral.sh/ruff/] |

**Deprecated/outdated:**
- `passlib`: Unmaintained, broken with bcrypt>=4.1. Use `pwdlib`.
- `python-jose`: Unmaintained since 2021, known security issues. Use `PyJWT`.
- `SQLAlchemy 1.x API`: Legacy. Use 2.x exclusively.
- `pip` as primary installer: Use `uv` for speed. `pip` still works but is slower.

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | Docker base image `python:3.12-slim` is suitable for all dependencies | Standard Stack | LOW -- well-tested image, may need build-essential for some native deps |
| A2 | pwdlib[bcrypt] is compatible with Celery worker context (sync) | Standard Stack | LOW -- bcrypt hashing is CPU-bound sync operation, works in any context |
| A3 | Redis 7-alpine Docker image is sufficient for both Celery broker and token blocklist | Standard Stack | LOW -- standard Redis supports all needed commands |
| A4 | Flower 2.0.1 works with Celery 5.6.x | Standard Stack | MEDIUM -- Flower sometimes lags behind Celery releases. If incompatible, pin Flower to latest compatible version |

## Open Questions

1. **pwdlib bcrypt vs argon2 for password hashing**
   - What we know: FastAPI docs default to argon2. CLAUDE.md says bcrypt. Both are secure.
   - What's unclear: Whether the user has a strong preference for bcrypt specifically, or just wants "secure password hashing."
   - Recommendation: Use `pwdlib[bcrypt]` to match CLAUDE.md's `passlib[bcrypt]` intent. Bcrypt is well-understood and sufficient for this use case.

2. **Apollo API key storage: encrypted or plaintext?**
   - What we know: D-02/AUTH-02 says "admin can configure the shared Apollo API key via API endpoint." The key is sensitive.
   - What's unclear: Whether the key should be encrypted at rest in the database or stored as plaintext (protected by DB access controls only).
   - Recommendation: Store encrypted (using Fernet symmetric encryption with the app's SECRET_KEY). Low effort, meaningful security improvement.

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| Docker | Container runtime | Yes | 29.2.1 | -- |
| Docker Compose | Service orchestration | Yes | v5.1.0 | -- |
| Python (host) | Local dev, manage.py | Yes | 3.14.3 (host), 3.12 (Docker) | Use Docker for all Python execution |
| Node.js | GSD tooling only | Yes | v24.14.0 | -- |
| uv | Fast package management | No | -- | Use pip inside Docker; install uv in Dockerfile via COPY --from |
| PostgreSQL client | Local psql access | No | -- | Access via `docker compose exec db psql` |
| Redis client | Local redis-cli | No | -- | Access via `docker compose exec redis redis-cli` |

**Missing dependencies with no fallback:**
- None -- all critical tools are available.

**Missing dependencies with fallback:**
- `uv` not on host PATH -- install in Dockerfile via multi-stage copy from `ghcr.io/astral-sh/uv:latest`. Host-side operations can fall back to pip.
- PostgreSQL/Redis CLIs not on host -- use `docker compose exec` for database access.

## Validation Architecture

### Test Framework

| Property | Value |
|----------|-------|
| Framework | pytest 8.x + pytest-asyncio 1.3.0 |
| Config file | `pyproject.toml` [tool.pytest.ini_options] -- Wave 0 creates this |
| Quick run command | `docker compose exec api pytest tests/ -x --timeout=30` |
| Full suite command | `docker compose exec api pytest tests/ -v --timeout=60` |

### Phase Requirements to Test Map

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| INFRA-01 | Docker Compose starts all services, API responds | smoke | `docker compose up -d && curl http://localhost:8000/health` | No -- Wave 0 |
| INFRA-02 | Swagger UI accessible | smoke | `curl -f http://localhost:8000/docs` | No -- Wave 0 |
| INFRA-03 | API routes use /api/v1/ prefix | unit | `pytest tests/test_routes.py -x` | No -- Wave 0 |
| AUTH-01 | Login with email/password returns JWT | integration | `pytest tests/auth/test_login.py -x` | No -- Wave 0 |
| AUTH-02 | Admin can set Apollo API key | integration | `pytest tests/admin/test_config.py -x` | No -- Wave 0 |
| AUTH-03 | Admin add/remove user, revoked token rejected | integration | `pytest tests/admin/test_users.py -x` | No -- Wave 0 |

### Sampling Rate

- **Per task commit:** `docker compose exec api pytest tests/ -x --timeout=30`
- **Per wave merge:** `docker compose exec api pytest tests/ -v --timeout=60`
- **Phase gate:** Full suite green + manual smoke test of `docker compose up` from clean state

### Wave 0 Gaps

- [ ] `pyproject.toml` -- [tool.pytest.ini_options] section with asyncio_mode = "auto"
- [ ] `tests/conftest.py` -- async test client fixture, test database setup, Redis mock/fixture
- [ ] `tests/auth/test_login.py` -- covers AUTH-01
- [ ] `tests/admin/test_users.py` -- covers AUTH-03
- [ ] `tests/admin/test_config.py` -- covers AUTH-02
- [ ] `tests/test_health.py` -- covers INFRA-01 (API-level), INFRA-02 (route existence)
- [ ] Framework install in Docker image: `uv pip install pytest pytest-asyncio httpx`

## Security Domain

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | Yes | pwdlib[bcrypt] for password hashing, PyJWT for token management, 30-min access token expiry (D-05) |
| V3 Session Management | Yes | JWT access + refresh tokens, Redis blocklist for revocation (D-07), 7-day refresh expiry |
| V4 Access Control | Yes | is_admin boolean (D-08), admin-only route guards on /admin/* endpoints |
| V5 Input Validation | Yes | Pydantic v2 schemas on all request bodies, FastAPI automatic validation |
| V6 Cryptography | Yes (minimal) | HS256 for JWT signing (per CLAUDE.md), bcrypt for passwords (via pwdlib) |

### Known Threat Patterns for This Stack

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| JWT secret in source code | Information Disclosure | SECRET_KEY from environment variable via pydantic-settings, never hardcoded |
| Brute force login | Spoofing | Rate limiting on /auth/login (consider slowapi or custom middleware) |
| Token replay after user removal | Elevation of Privilege | Redis blocklist (D-07) with JTI-based revocation |
| SQL injection | Tampering | SQLAlchemy ORM parameterized queries (never raw SQL with string interpolation) |
| Apollo API key exposure in logs | Information Disclosure | Never log API key value; mask in health/status endpoints |
| Mass assignment on user creation | Tampering | Explicit Pydantic schemas that only accept expected fields |

## Sources

### Primary (HIGH confidence)
- [PyPI registry] -- All package versions verified via `pip index versions` on 2026-04-06
- [FastAPI official docs: JWT tutorial](https://fastapi.tiangolo.com/tutorial/security/oauth2-jwt/) -- Confirmed switch to PyJWT and pwdlib
- [SQLAlchemy 2.0 async docs](https://docs.sqlalchemy.org/en/20/orm/extensions/asyncio.html) -- Async engine and session patterns

### Secondary (MEDIUM confidence)
- [FastAPI discussion #11773](https://github.com/fastapi/fastapi/discussions/11773) -- passlib maintenance status
- [FastAPI PR #11589](https://github.com/fastapi/fastapi/pull/11589) -- python-jose to PyJWT migration
- [pwdlib discussion](https://github.com/frankie567/pwdlib/discussions/1) -- pwdlib as passlib replacement

### Tertiary (LOW confidence)
- Docker Compose patterns (healthchecks, override files) -- based on standard practices, not verified against a specific official doc page

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH -- all versions verified against PyPI, library substitutions verified against FastAPI official docs
- Architecture: HIGH -- patterns follow established FastAPI + SQLAlchemy 2.x conventions
- Pitfalls: HIGH -- common issues well-documented in ecosystem
- Security: MEDIUM -- ASVS mapping based on training knowledge, not verified against current ASVS version

**Research date:** 2026-04-06
**Valid until:** 2026-05-06 (30 days -- stable ecosystem, no fast-moving dependencies)
