from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.deps import get_db, get_redis

router = APIRouter(tags=["health"])


@router.get("/health")
async def health_check(db: AsyncSession = Depends(get_db), redis=Depends(get_redis)):
    """Check database and Redis connectivity."""
    # Verify database connectivity
    await db.execute(text("SELECT 1"))

    # Verify Redis connectivity
    await redis.ping()

    return {"status": "healthy", "database": "connected", "redis": "connected"}
