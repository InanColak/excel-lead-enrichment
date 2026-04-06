from collections.abc import AsyncGenerator

from redis.asyncio import from_url as redis_from_url
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import async_session


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with async_session() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def get_redis() -> AsyncGenerator:
    client = redis_from_url(settings.redis_url, decode_responses=True)
    try:
        yield client
    finally:
        await client.aclose()
