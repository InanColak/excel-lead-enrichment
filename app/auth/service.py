import uuid
from datetime import datetime, timedelta, timezone

import jwt
from pwdlib import PasswordHash
from pwdlib.hashers.bcrypt import BcryptHasher

from app.config import settings

password_hash = PasswordHash((BcryptHasher(),))


def hash_password(password: str) -> str:
    return password_hash.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return password_hash.verify(plain_password, hashed_password)


def create_access_token(user_id: str, is_admin: bool) -> tuple[str, str]:
    """Returns (token, jti) tuple."""
    jti = str(uuid.uuid4())
    payload = {
        "sub": user_id,
        "jti": jti,
        "is_admin": is_admin,
        "exp": datetime.now(timezone.utc) + timedelta(minutes=settings.access_token_expire_minutes),
        "type": "access",
    }
    token = jwt.encode(payload, settings.secret_key, algorithm="HS256")
    return token, jti


def create_refresh_token(user_id: str) -> tuple[str, str]:
    """Returns (token, jti) tuple."""
    jti = str(uuid.uuid4())
    payload = {
        "sub": user_id,
        "jti": jti,
        "exp": datetime.now(timezone.utc) + timedelta(days=settings.refresh_token_expire_days),
        "type": "refresh",
    }
    token = jwt.encode(payload, settings.secret_key, algorithm="HS256")
    return token, jti


def decode_token(token: str) -> dict:
    """Decode and validate JWT. Raises jwt.PyJWTError on failure."""
    return jwt.decode(token, settings.secret_key, algorithms=["HS256"])


async def is_token_revoked(jti: str, redis_client) -> bool:
    """Check if a token JTI exists in the Redis blocklist."""
    return await redis_client.exists(f"blocklist:{jti}")


async def revoke_token(jti: str, exp_timestamp: int, redis_client) -> None:
    """Add a token JTI to the Redis blocklist with TTL until token expiry."""
    ttl = exp_timestamp - int(datetime.now(timezone.utc).timestamp())
    if ttl > 0:
        await redis_client.setex(f"blocklist:{jti}", ttl, "revoked")
