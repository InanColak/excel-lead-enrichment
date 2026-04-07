from typing import Optional

from pydantic import BaseModel, Field


class ApolloEnrichRequest(BaseModel):
    """Request payload for Apollo People Enrichment API."""

    first_name: Optional[str] = None
    last_name: Optional[str] = None
    organization_name: Optional[str] = None
    email: Optional[str] = None
    linkedin_url: Optional[str] = None
    reveal_personal_emails: bool = True
    reveal_phone_number: bool = True
    webhook_url: Optional[str] = None


class ApolloOrganization(BaseModel):
    name: Optional[str] = None
    domain: Optional[str] = None


class ApolloPerson(BaseModel):
    id: Optional[str] = None
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    email: Optional[str] = None
    email_status: Optional[str] = None
    linkedin_url: Optional[str] = None
    title: Optional[str] = None
    organization: Optional[ApolloOrganization] = None


class ApolloWaterfall(BaseModel):
    status: Optional[str] = None


class ApolloEnrichResponse(BaseModel):
    person: Optional[ApolloPerson] = None
    waterfall: Optional[ApolloWaterfall] = None


class ApolloPhoneNumber(BaseModel):
    raw_number: Optional[str] = None
    sanitized_number: Optional[str] = None
    confidence_cd: Optional[str] = None
    status_cd: Optional[str] = None


class ApolloWebhookWaterfall(BaseModel):
    phone_numbers: list[ApolloPhoneNumber] = Field(default_factory=list)


class ApolloWebhookPerson(BaseModel):
    id: Optional[str] = None
    waterfall: Optional[ApolloWebhookWaterfall] = None


class ApolloWebhookPayload(BaseModel):
    request_id: Optional[str] = None
    people: list[ApolloWebhookPerson] = Field(default_factory=list)
