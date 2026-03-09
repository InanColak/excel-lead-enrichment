"""
Authentication for Lead Enrichment API.
Supports both JWT (auth-service) and API Key (Power Automate).
"""

import os

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt

security = HTTPBearer(auto_error=False)


def get_jwt_secret() -> str:
    secret = os.getenv("JWT_SECRET")
    if not secret:
        raise ValueError("JWT_SECRET environment variable is not set")
    return secret


def get_api_key() -> str | None:
    return os.getenv("ENRICHMENT_API_KEY")


def verify_token(token: str) -> dict | None:
    """Verify JWT token and return payload."""
    try:
        payload = jwt.decode(
            token,
            get_jwt_secret(),
            algorithms=["HS256"]
        )
        return payload
    except JWTError:
        return None


def get_current_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(security),
) -> dict:
    """
    FastAPI dependency to validate access.
    Accepts either:
      1. API Key via X-API-Key header (for Power Automate)
      2. JWT Bearer token (for auth-service)
    """
    # Check API Key header first
    api_key_header = request.headers.get("X-API-Key")
    expected_api_key = get_api_key()

    if api_key_header and expected_api_key:
        if api_key_header == expected_api_key:
            return {"email": "power-automate", "auth_method": "api_key"}
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API key",
        )

    # Fall back to JWT Bearer token
    if not credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing authentication. Provide X-API-Key header or Bearer token.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    token = credentials.credentials
    payload = verify_token(token)

    if not payload:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if payload.get("type") != "access":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token type",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return {
        "email": payload.get("sub"),
        "exp": payload.get("exp"),
        "auth_method": "jwt",
    }
