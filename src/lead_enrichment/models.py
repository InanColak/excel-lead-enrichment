"""Pydantic models for API requests, responses, and internal data transfer."""

from __future__ import annotations

from pydantic import BaseModel, Field


# ── Input ────────────────────────────────────────────────────────

class PersonInput(BaseModel):
    """A person extracted from the input Excel file."""

    row_id: int
    first_name: str
    last_name: str
    company: str


class ColumnMapping(BaseModel):
    """Maps detected Excel columns to our internal field names."""

    first_name_col: str = Field(description="Column header for first name")
    last_name_col: str = Field(description="Column header for last name")
    company_col: str = Field(description="Column header for company name")


# ── Lusha ────────────────────────────────────────────────────────

class LushaPhoneNumber(BaseModel):
    number: str
    phone_type: str | None = Field(default=None, alias="phoneType")
    do_not_call: bool = Field(default=False, alias="doNotCall")

    model_config = {"populate_by_name": True, "extra": "allow"}


class LushaEmailAddress(BaseModel):
    email: str
    email_type: str | None = Field(default=None, alias="emailType")
    email_confidence: str | None = Field(default=None, alias="emailConfidence")

    model_config = {"populate_by_name": True}


class LushaContactData(BaseModel):
    """The 'data' object inside a Lusha person response."""

    first_name: str | None = Field(default=None, alias="firstName")
    last_name: str | None = Field(default=None, alias="lastName")
    email_addresses: list[LushaEmailAddress] = Field(
        default_factory=list, alias="emailAddresses"
    )
    phone_numbers: list[LushaPhoneNumber] = Field(
        default_factory=list, alias="phoneNumbers"
    )

    model_config = {"populate_by_name": True}


class LushaContact(BaseModel):
    """A single contact in the Lusha response."""

    error: str | None = None
    data: LushaContactData | None = None


class LushaPersonResponse(BaseModel):
    """Top-level Lusha GET /v2/person response."""

    contact: LushaContact | None = None


class LushaBulkContact(BaseModel):
    """A single contact result in the Lusha bulk response."""

    error: str | None = None
    is_credit_charged: bool | None = Field(default=None, alias="isCreditCharged")
    data: LushaContactData | None = None

    model_config = {"populate_by_name": True, "extra": "allow"}


# ── Apollo ───────────────────────────────────────────────────────

class ApolloPhoneNumber(BaseModel):
    raw_number: str | None = None
    sanitized_number: str | None = None
    type_cd: str | None = None
    confidence_cd: str | None = None

    model_config = {"extra": "allow"}


class ApolloPersonMatch(BaseModel):
    """A single person match from Apollo's sync response."""

    id: str | None = None
    first_name: str | None = None
    last_name: str | None = None
    name: str | None = None
    email: str | None = None
    title: str | None = None
    phone_numbers: list[ApolloPhoneNumber] = Field(default_factory=list)

    model_config = {"extra": "allow"}


class ApolloBulkMatchResponse(BaseModel):
    """Apollo POST /v1/people/bulk_match response."""

    status: str | None = None
    matches: list[ApolloPersonMatch | None] = Field(default_factory=list)
    total_requested_enrichments: int | None = None
    unique_enriched_records: int | None = None
    credits_consumed: int | None = None

    model_config = {"extra": "allow"}


class ApolloSingleMatchResponse(BaseModel):
    """Apollo POST /v1/people/match response."""

    person: ApolloPersonMatch | None = None

    model_config = {"extra": "allow"}


class ApolloWebhookPerson(BaseModel):
    """A person record in the Apollo webhook payload."""

    id: str | None = None
    first_name: str | None = None
    last_name: str | None = None
    email: str | None = None
    phone_numbers: list[ApolloPhoneNumber] = Field(default_factory=list)

    model_config = {"extra": "allow"}


class ApolloWebhookPayload(BaseModel):
    """The payload Apollo POSTs to our webhook URL."""

    status: str | None = None
    people: list[ApolloWebhookPerson] = Field(default_factory=list)
    total_requested_enrichments: int | None = None
    unique_enriched_records: int | None = None
    credits_consumed: int | None = None

    model_config = {"extra": "allow"}


# ── Enriched output ─────────────────────────────────────────────

class EnrichedPerson(BaseModel):
    """Final enriched person with data from both APIs."""

    row_id: int
    first_name: str
    last_name: str
    company: str

    apollo_email: str | None = None
    apollo_handynummer: str | None = None
    apollo_festnetz_durchwahl: str | None = None

    lusha_email: str | None = None
    lusha_handynummer: str | None = None
    lusha_festnetz_durchwahl: str | None = None
