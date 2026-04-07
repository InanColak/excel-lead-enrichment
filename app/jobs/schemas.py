import uuid
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field, model_validator


class JobResponse(BaseModel):
    id: uuid.UUID
    filename: str
    status: str
    total_rows: int
    valid_rows: int
    error_rows: int
    processed_rows: int = 0
    cache_hits: int = 0
    api_calls: int = 0
    webhook_callbacks_received: int = 0
    webhook_timeouts: int = 0
    progress_percent: float | None = None
    has_output: bool = False
    output_file_path: str | None = Field(default=None, exclude=True)
    column_mappings: Optional[list | dict] = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}

    @model_validator(mode="after")
    def compute_fields(self) -> "JobResponse":
        """Compute progress_percent and has_output from raw model fields."""
        # D-59: progress_percent when processing/awaiting_webhooks
        if self.status in ("processing", "awaiting_webhooks") and self.total_rows > 0:
            self.progress_percent = round(self.processed_rows / self.total_rows * 100, 1)
        # T-04-07: has_output boolean instead of exposing filesystem path
        self.has_output = self.output_file_path is not None
        return self


class PaginatedJobsResponse(BaseModel):
    items: list[JobResponse]
    total: int
    limit: int
    offset: int


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


class UsageStatsResponse(BaseModel):
    total_jobs: int
    total_api_calls: int
    total_cache_hits: int
    cache_hit_rate_percent: float
    total_webhook_callbacks: int
    total_webhook_timeouts: int
    jobs_by_status: dict[str, int]
