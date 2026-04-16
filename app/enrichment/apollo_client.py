import logging
from typing import Optional

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from app.admin.models import ApiConfig
from app.admin.service import decrypt_api_key
from app.config import settings
from app.enrichment.schemas import ApolloEnrichResponse, ApolloBulkEnrichResponse

logger = logging.getLogger(__name__)


class ApolloTransientError(Exception):
    """Retryable error: 429 rate limit, 5xx server error, network timeout."""

    pass


class ApolloClientError(Exception):
    """Non-retryable error: 400 bad request, 401 unauthorized, etc."""

    pass


class ApolloNotFoundError(Exception):
    """Apollo returned a valid response but no person match."""

    pass


async def _get_api_key_from_db(db: AsyncSession) -> str:
    """Read the encrypted Apollo API key from the api_config table and decrypt it.

    Raises ApolloClientError if no key is configured.
    """
    result = await db.execute(
        select(ApiConfig).where(ApiConfig.key == "apollo_api_key")
    )
    config = result.scalar_one_or_none()
    if config is None:
        raise ApolloClientError(
            "Apollo API key not configured. Admin must set it via /api/v1/admin/api-key."
        )
    return decrypt_api_key(config.value)


class ApolloClient:
    """Apollo People Enrichment API client with httpx + tenacity retry.

    Per D-38: exponential backoff starting at 2s, max 60s, 5 retries.
    Only retries ApolloTransientError (429, 5xx, network).
    Per Pitfall 4: reads API key from DB at init, not from env.
    """

    def __init__(self, api_key: str, webhook_url: Optional[str] = None):
        self.api_key = api_key
        self.webhook_url = webhook_url
        self.client = httpx.AsyncClient(
            timeout=httpx.Timeout(30.0, connect=10.0),
            limits=httpx.Limits(max_connections=10, max_keepalive_connections=5),
        )

    async def close(self) -> None:
        """Close the underlying httpx client."""
        await self.client.aclose()

    @retry(
        stop=stop_after_attempt(5),
        wait=wait_exponential(multiplier=2, min=2, max=60),
        retry=retry_if_exception_type(ApolloTransientError),
        reraise=True,
    )
    async def enrich_person(
        self,
        first_name: Optional[str] = None,
        last_name: Optional[str] = None,
        organization_name: Optional[str] = None,
        email: Optional[str] = None,
        linkedin_url: Optional[str] = None,
    ) -> ApolloEnrichResponse:
        """Call Apollo People Enrichment API. Returns parsed response.

        Raises ApolloTransientError on 429/5xx/network (will be retried).
        Raises ApolloClientError on 401/400 (will NOT be retried).
        Raises ApolloNotFoundError if Apollo returns no person match.
        """
        payload: dict = {}
        if first_name:
            payload["first_name"] = first_name
        if last_name:
            payload["last_name"] = last_name
        if organization_name:
            payload["organization_name"] = organization_name
        if email:
            payload["email"] = email
        if linkedin_url:
            payload["linkedin_url"] = linkedin_url
        payload["reveal_personal_emails"] = True
        payload["reveal_phone_number"] = True
        payload["run_waterfall_phone"] = True
        if self.webhook_url:
            payload["webhook_url"] = self.webhook_url

        try:
            response = await self.client.post(
                settings.apollo_api_url,
                json=payload,
                headers={
                    "x-api-key": self.api_key,
                    "Content-Type": "application/json",
                },
            )
        except httpx.TimeoutException as e:
            raise ApolloTransientError(f"Network timeout: {e}") from e
        except httpx.ConnectError as e:
            raise ApolloTransientError(f"Connection error: {e}") from e

        if response.status_code == 429:
            raise ApolloTransientError("Rate limited (429)")
        if response.status_code >= 500:
            raise ApolloTransientError(f"Server error ({response.status_code})")
        if response.status_code == 401:
            raise ApolloClientError("Invalid Apollo API key (401)")
        if response.status_code == 400:
            raise ApolloClientError(f"Bad request (400): {response.text[:200]}")

        data = response.json()
        parsed = ApolloEnrichResponse.model_validate(data)

        if parsed.person is None:
            raise ApolloNotFoundError("Apollo returned no person match")

        return parsed

    @retry(
        stop=stop_after_attempt(5),
        wait=wait_exponential(multiplier=2, min=2, max=60),
        retry=retry_if_exception_type(ApolloTransientError),
        reraise=True,
    )
    async def bulk_enrich_people(
        self,
        details: list[dict],
    ) -> ApolloBulkEnrichResponse:
        """Call Apollo Bulk People Enrichment API (max 10 people per call).

        Each entry in details is a dict with optional keys:
        first_name, last_name, organization_name, email, linkedin_url.

        Returns parsed bulk response with matches array.
        """
        payload: dict = {
            "details": details,
            "reveal_personal_emails": True,
            "reveal_phone_number": True,
            "run_waterfall_phone": True,
        }
        if self.webhook_url:
            payload["webhook_url"] = self.webhook_url

        try:
            response = await self.client.post(
                settings.apollo_bulk_api_url,
                json=payload,
                headers={
                    "x-api-key": self.api_key,
                    "Content-Type": "application/json",
                },
            )
        except httpx.TimeoutException as e:
            raise ApolloTransientError(f"Network timeout: {e}") from e
        except httpx.ConnectError as e:
            raise ApolloTransientError(f"Connection error: {e}") from e

        if response.status_code == 429:
            raise ApolloTransientError("Rate limited (429)")
        if response.status_code >= 500:
            raise ApolloTransientError(f"Server error ({response.status_code})")
        if response.status_code == 401:
            raise ApolloClientError("Invalid Apollo API key (401)")
        if response.status_code == 400:
            raise ApolloClientError(f"Bad request (400): {response.text[:200]}")

        data = response.json()
        return ApolloBulkEnrichResponse.model_validate(data)
