import jwt
from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.models import User
from app.auth.schemas import LoginRequest, RefreshRequest, TokenResponse
from app.auth.service import (
    create_access_token,
    create_refresh_token,
    decode_token,
    is_token_revoked,
    revoke_token,
    verify_password,
)
from app.deps import get_current_user, get_db, get_redis

router = APIRouter(tags=["auth"])


@router.post("/login", response_model=TokenResponse)
async def login(body: LoginRequest, db: AsyncSession = Depends(get_db), redis=Depends(get_redis)):
    """Authenticate user and return JWT token pair."""
    result = await db.execute(select(User).where(User.email == body.email))
    user = result.scalar_one_or_none()
    if user is None or not user.is_active or not verify_password(body.password, user.hashed_password):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid email or password")

    access_token, access_jti = create_access_token(str(user.id), user.is_admin)
    refresh_token, refresh_jti = create_refresh_token(str(user.id))

    # Track JTIs for bulk revocation on user deactivation
    await redis.sadd(f"user_tokens:{user.id}", access_jti, refresh_jti)

    return TokenResponse(access_token=access_token, refresh_token=refresh_token)


@router.post("/refresh", response_model=TokenResponse)
async def refresh(body: RefreshRequest, redis=Depends(get_redis), db: AsyncSession = Depends(get_db)):
    """Issue new token pair from a valid refresh token."""
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired refresh token"
    )
    try:
        payload = decode_token(body.refresh_token)
        if payload.get("type") != "refresh":
            raise credentials_exception
        user_id = payload.get("sub")
        jti = payload.get("jti")
        if user_id is None or jti is None:
            raise credentials_exception
    except jwt.PyJWTError:
        raise credentials_exception

    # Check if refresh token has been revoked
    if await is_token_revoked(jti, redis):
        raise credentials_exception

    # Verify user still exists and is active
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if user is None or not user.is_active:
        raise credentials_exception

    # Issue new token pair
    new_access_token, new_access_jti = create_access_token(str(user.id), user.is_admin)
    new_refresh_token, new_refresh_jti = create_refresh_token(str(user.id))

    # Track new JTIs in user_tokens set for bulk revocation consistency
    await redis.sadd(f"user_tokens:{user.id}", new_access_jti, new_refresh_jti)

    return TokenResponse(access_token=new_access_token, refresh_token=new_refresh_token)


@router.post("/logout", status_code=204)
async def logout(request: Request, user: User = Depends(get_current_user), redis=Depends(get_redis)):
    """Revoke the current access token by adding its JTI to the Redis blocklist."""
    auth_header = request.headers.get("Authorization", "")
    token = auth_header.replace("Bearer ", "")
    payload = decode_token(token)
    jti = payload.get("jti")
    exp = payload.get("exp")
    if jti and exp:
        await revoke_token(jti, exp, redis)
    return None
