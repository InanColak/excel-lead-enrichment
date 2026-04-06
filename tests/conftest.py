import uuid
from unittest.mock import AsyncMock

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.auth.models import User
from app.auth.service import create_access_token, hash_password
from app.config import settings
from app.deps import get_db, get_redis
from app.main import app
from app.models.base import Base

# Import all models so Base.metadata knows about them for create_all/drop_all
from app.admin.models import ApiConfig  # noqa: F401

# Use the real PostgreSQL database from settings (reads DATABASE_URL from environment).
# Tests MUST run inside Docker: docker compose exec api pytest tests/ -v
# SQLite is NOT used -- CLAUDE.md forbids it (no JSONB, no UUID, no concurrent writes).


@pytest.fixture(scope="session")
async def test_engine():
    """Create engine connected to the real PostgreSQL. Tables created once per session."""
    engine = create_async_engine(settings.database_url, echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


@pytest.fixture
async def test_session(test_engine):
    """Per-test session with transaction rollback for isolation."""
    async with test_engine.connect() as conn:
        trans = await conn.begin()
        session = AsyncSession(bind=conn, expire_on_commit=False)
        yield session
        await session.close()
        await trans.rollback()


@pytest.fixture
def mock_redis():
    """Mock Redis client. Tests do not need a real Redis connection."""
    redis = AsyncMock()
    redis.exists = AsyncMock(return_value=0)  # No tokens revoked by default
    redis.ping = AsyncMock(return_value=True)
    redis.setex = AsyncMock()
    redis.sadd = AsyncMock()
    redis.smembers = AsyncMock(return_value=set())
    redis.delete = AsyncMock()
    return redis


@pytest.fixture
async def async_client(test_session, mock_redis):
    """httpx AsyncClient with dependency overrides for DB and Redis."""

    async def override_get_db():
        yield test_session

    async def override_get_redis():
        yield mock_redis

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_redis] = override_get_redis

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        yield client

    app.dependency_overrides.clear()


@pytest.fixture
async def admin_user(test_session) -> User:
    """Create an admin user within the test transaction."""
    user = User(
        id=uuid.uuid4(),
        email="admin@test.com",
        hashed_password=hash_password("adminpass"),
        is_admin=True,
        is_active=True,
    )
    test_session.add(user)
    await test_session.flush()
    await test_session.refresh(user)
    return user


@pytest.fixture
async def regular_user(test_session) -> User:
    """Create a non-admin user within the test transaction."""
    user = User(
        id=uuid.uuid4(),
        email="user@test.com",
        hashed_password=hash_password("userpass"),
        is_admin=False,
        is_active=True,
    )
    test_session.add(user)
    await test_session.flush()
    await test_session.refresh(user)
    return user


@pytest.fixture
def admin_token(admin_user) -> str:
    """JWT access token for admin user."""
    token, _jti = create_access_token(str(admin_user.id), True)
    return token


@pytest.fixture
def user_token(regular_user) -> str:
    """JWT access token for regular (non-admin) user."""
    token, _jti = create_access_token(str(regular_user.id), False)
    return token
