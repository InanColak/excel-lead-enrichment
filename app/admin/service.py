import base64
import hashlib
import uuid
from datetime import datetime, timezone

from cryptography.fernet import Fernet
from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.admin.models import ApiConfig
from app.auth.models import User
from app.auth.service import hash_password
from app.config import settings


def _get_fernet() -> Fernet:
    """Derive a Fernet key from the application SECRET_KEY."""
    key = base64.urlsafe_b64encode(hashlib.sha256(settings.secret_key.encode()).digest())
    return Fernet(key)


def encrypt_api_key(api_key: str) -> str:
    """Encrypt an API key using Fernet symmetric encryption."""
    return _get_fernet().encrypt(api_key.encode()).decode()


def decrypt_api_key(encrypted: str) -> str:
    """Decrypt an encrypted API key."""
    return _get_fernet().decrypt(encrypted.encode()).decode()


def mask_api_key(api_key: str) -> str:
    """Mask an API key, showing only the last 4 characters."""
    if len(api_key) <= 4:
        return "****"
    return f"{'*' * (len(api_key) - 4)}{api_key[-4:]}"


async def create_user(
    db: AsyncSession, email: str, password: str, is_admin: bool = False
) -> User:
    """Create a new user. Raises 409 if email already exists."""
    result = await db.execute(select(User).where(User.email == email))
    if result.scalar_one_or_none() is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"User with email {email} already exists",
        )
    user = User(
        email=email,
        hashed_password=hash_password(password),
        is_admin=is_admin,
        is_active=True,
    )
    db.add(user)
    await db.flush()
    return user


async def deactivate_user(
    db: AsyncSession, user_id: uuid.UUID, redis
) -> None:
    """Deactivate a user and revoke all their active tokens."""
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="User not found"
        )
    user.is_active = False

    # Revoke all active tokens for this user
    token_key = f"user_tokens:{user_id}"
    jtis = await redis.smembers(token_key)
    for jti in jtis:
        # Set blocklist entry with a generous TTL (7 days max refresh token lifetime)
        ttl = 7 * 24 * 60 * 60
        await redis.setex(f"blocklist:{jti}", ttl, "revoked")
    await redis.delete(token_key)

    await db.flush()


async def list_users(db: AsyncSession) -> list[User]:
    """Return all users."""
    result = await db.execute(select(User))
    return list(result.scalars().all())


async def get_user(db: AsyncSession, user_id: uuid.UUID) -> User:
    """Return a single user by ID."""
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="User not found"
        )
    return user


async def set_api_key(db: AsyncSession, api_key: str) -> dict:
    """Encrypt and store the Apollo API key. Upserts the config row."""
    encrypted = encrypt_api_key(api_key)
    result = await db.execute(
        select(ApiConfig).where(ApiConfig.key == "apollo_api_key")
    )
    config = result.scalar_one_or_none()
    if config is not None:
        config.value = encrypted
        config.updated_at = datetime.now(timezone.utc)
    else:
        config = ApiConfig(key="apollo_api_key", value=encrypted)
        db.add(config)
    await db.flush()
    return {"key_set": True, "masked_key": mask_api_key(api_key)}


async def get_api_key(db: AsyncSession) -> dict:
    """Retrieve and return masked Apollo API key."""
    result = await db.execute(
        select(ApiConfig).where(ApiConfig.key == "apollo_api_key")
    )
    config = result.scalar_one_or_none()
    if config is None:
        return {"key_set": False, "masked_key": None}
    decrypted = decrypt_api_key(config.value)
    return {"key_set": True, "masked_key": mask_api_key(decrypted)}
