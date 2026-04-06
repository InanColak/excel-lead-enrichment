import uuid
from datetime import datetime
from typing import Optional

from pydantic import BaseModel


class JobResponse(BaseModel):
    id: uuid.UUID
    filename: str
    status: str
    total_rows: int
    valid_rows: int
    error_rows: int
    column_mappings: Optional[dict] = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class JobRowResponse(BaseModel):
    id: uuid.UUID
    row_index: int
    raw_data: dict
    status: str
    error_message: Optional[str] = None
    contact_id: Optional[uuid.UUID] = None

    model_config = {"from_attributes": True}


class UploadResponse(BaseModel):
    job_id: uuid.UUID
    filename: str
    status: str
    total_rows: int
    valid_rows: int
    error_rows: int
    message: str


class ColumnMappingEntry(BaseModel):
    column: str
    detected_type: str
    confidence: str


class ColumnMappingsResponse(BaseModel):
    job_id: uuid.UUID
    mappings: list[ColumnMappingEntry]


class ColumnMappingOverride(BaseModel):
    column: str
    mapped_type: str


class ColumnMappingsOverrideRequest(BaseModel):
    mappings: list[ColumnMappingOverride]


class ConfirmResponse(BaseModel):
    job_id: uuid.UUID
    status: str
    total_rows: int
    valid_rows: int
    error_rows: int
    message: str
