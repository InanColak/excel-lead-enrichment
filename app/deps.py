from collections.abc import AsyncGenerator

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from redis.asyncio import from_url as redis_from_url
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import async_session

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login", auto_error=False)

# Fixed UUID for the system user when auth is disabled
_SYSTEM_USER_ID = "00000000-0000-0000-0000-000000000000"


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


async def _get_or_create_system_user(db: AsyncSession):
    """Return the system user, creating it if it doesn't exist."""
    from app.auth.models import User

    result = await db.execute(select(User).where(User.id == _SYSTEM_USER_ID))
    user = result.scalar_one_or_none()
    if user is None:
        user = User(
            id=_SYSTEM_USER_ID,
            email="system@leadenrich.local",
            hashed_password="disabled",
            is_admin=True,
            is_active=True,
        )
        db.add(user)
        await db.flush()
    return user


async def get_current_user(
    token: str | None = Depends(oauth2_scheme),
    db: AsyncSession = Depends(get_db),
    redis=Depends(get_redis),
):
    """Decode JWT, check blocklist, return authenticated User.
    When auth is disabled, returns a system user instead."""
    from app.auth.models import User
    from app.auth.service import decode_token, is_token_revoked

    if not settings.auth_enabled:
        return await _get_or_create_system_user(db)

    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid or expired token",
        headers={"WWW-Authenticate": "Bearer"},
    )

    if token is None:
        raise credentials_exception

    try:
        payload = decode_token(token)
        if payload.get("type") != "access":
            raise credentials_exception
        user_id = payload.get("sub")
        jti = payload.get("jti")
        if user_id is None or jti is None:
            raise credentials_exception
    except jwt.PyJWTError:
        raise credentials_exception

    # Check Redis blocklist
    if await is_token_revoked(jti, redis):
        raise credentials_exception

    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if user is None or not user.is_active:
        raise credentials_exception

    return user


async def get_current_admin(user=Depends(get_current_user)):
    """Verify the current user has admin privileges."""
    if not settings.auth_enabled:
        return user
    if not user.is_admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin access required")
    return user
