"""Pydantic schemas for API requests and responses."""

from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field


class RunStatus(str, Enum):
    """Status of an enrichment run."""

    PENDING = "pending"
    LOADING = "loading"
    ENRICHING_LUSHA = "enriching_lusha"
    ENRICHING_APOLLO = "enriching_apollo"
    WAITING_WEBHOOKS = "waiting_webhooks"
    EXPORTING = "exporting"
    COMPLETED = "completed"
    FAILED = "failed"


class HealthResponse(BaseModel):
    """Health check response."""

    status: str = "ok"
    version: str = "1.0.0"


class EnrichmentStartResponse(BaseModel):
    """Response when starting a new enrichment."""

    run_id: str
    status: RunStatus
    message: str


class APIStatusCounts(BaseModel):
    """Status counts for a single API."""

    complete: int = 0
    error: int = 0
    pending: int = 0
    awaiting_webhook: int | None = None
    timeout: int | None = None


class EnrichmentStatusResponse(BaseModel):
    """Response for enrichment status query."""

    run_id: str
    status: RunStatus
    total_rows: int = 0
    lusha: APIStatusCounts = Field(default_factory=APIStatusCounts)
    apollo: APIStatusCounts = Field(default_factory=APIStatusCounts)
    started_at: datetime | None = None
    completed_at: datetime | None = None
    error_message: str | None = None
    output_file: str | None = None


class RunListItem(BaseModel):
    """Summary of a single run for listing."""

    run_id: str
    status: RunStatus
    total_rows: int
    input_file: str | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None


class RunListResponse(BaseModel):
    """Response for listing all runs."""

    runs: list[RunListItem] = Field(default_factory=list)


class ErrorResponse(BaseModel):
    """Standard error response."""

    error: str
    detail: str | None = None
