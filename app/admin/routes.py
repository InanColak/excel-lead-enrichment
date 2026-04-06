import uuid

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.admin.schemas import (
    ApiKeyResponse,
    CreateUserRequest,
    SetApiKeyRequest,
    UserListResponse,
)
from app.admin.service import (
    create_user,
    deactivate_user,
    get_api_key,
    get_user,
    list_users,
    set_api_key,
)
from app.deps import get_current_admin, get_db, get_redis

router = APIRouter(tags=["admin"])


@router.get("/users", response_model=list[UserListResponse])
async def list_all_users(
    admin=Depends(get_current_admin), db: AsyncSession = Depends(get_db)
):
    """List all users (admin only)."""
    return await list_users(db)


@router.post("/users", response_model=UserListResponse, status_code=status.HTTP_201_CREATED)
async def create_new_user(
    body: CreateUserRequest,
    admin=Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """Create a new user (admin only)."""
    return await create_user(db, body.email, body.password, body.is_admin)


@router.get("/users/{user_id}", response_model=UserListResponse)
async def get_single_user(
    user_id: uuid.UUID,
    admin=Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """Get a single user by ID (admin only)."""
    return await get_user(db, user_id)


@router.delete("/users/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_user(
    user_id: uuid.UUID,
    admin=Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
    redis=Depends(get_redis),
):
    """Deactivate a user and revoke their tokens (admin only)."""
    await deactivate_user(db, user_id, redis)
    return None


@router.put("/config/apollo-api-key", response_model=ApiKeyResponse)
async def set_apollo_key(
    body: SetApiKeyRequest,
    admin=Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """Set the Apollo API key (admin only). Key is stored encrypted."""
    return await set_api_key(db, body.api_key)


@router.get("/config/apollo-api-key", response_model=ApiKeyResponse)
async def get_apollo_key(
    admin=Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """Get the masked Apollo API key (admin only)."""
    return await get_api_key(db)
