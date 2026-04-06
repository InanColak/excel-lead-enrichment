import uuid
from typing import Optional

from pydantic import BaseModel


class CreateUserRequest(BaseModel):
    email: str
    password: str
    is_admin: bool = False


class UpdateUserRequest(BaseModel):
    email: Optional[str] = None
    is_admin: Optional[bool] = None
    is_active: Optional[bool] = None


class UserListResponse(BaseModel):
    id: uuid.UUID
    email: str
    is_admin: bool
    is_active: bool

    model_config = {"from_attributes": True}


class SetApiKeyRequest(BaseModel):
    api_key: str


class ApiKeyResponse(BaseModel):
    key_set: bool
    masked_key: Optional[str] = None
