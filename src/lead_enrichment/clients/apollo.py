"""Apollo API client for person enrichment (sync phase).

The sync phase returns email and company data immediately.
Phone numbers arrive asynchronously via webhook (handled by the webhook module).
"""

from __future__ import annotations

import json
import logging
import uuid

from ..config import Settings
from ..db.repository import Repository
from ..models import (
    ApolloBulkMatchResponse,
    ApolloPersonMatch,
    ApolloSingleMatchResponse,
    PersonInput,
)
from ..utils.retry import with_retry
from .base import BaseAPIClient
from .rate_limiter import TokenBucketRateLimiter

logger = logging.getLogger(__name__)

APOLLO_BASE_URL = "https://api.apollo.io"


class ApolloClient(BaseAPIClient):
    """Client for Apollo people enrichment API."""

    def __init__(self, settings: Settings) -> None:
        limiter = TokenBucketRateLimiter(
            rate=settings.apollo_rate_per_minute,
            per=60.0,
        )
        super().__init__(
            settings=settings,
            rate_limiter=limiter,
            base_url=APOLLO_BASE_URL,
            headers={
                "X-Api-Key": settings.apollo_api_key,
                "Content-Type": "application/json",
                "Cache-Control": "no-cache",
            },
        )
        self._webhook_url = settings.webhook_url

    @with_retry(max_attempts=3)
    async def match_single(self, person: PersonInput) -> ApolloSingleMatchResponse:
        """Enrich a single person via POST /api/v1/people/match."""
        body = {
            "first_name": person.first_name,
            "last_name": person.last_name,
            "organization_name": person.company,
            "reveal_personal_emails": True,
            "reveal_phone_number": True,
            "webhook_url": self._webhook_url,
        }
        response = await self._request("POST", "/api/v1/people/match", json=body)
        return ApolloSingleMatchResponse.model_validate(response.json())

    @with_retry(max_attempts=3)
    async def match_bulk(
        self, persons: list[PersonInput]
    ) -> ApolloBulkMatchResponse:
        """Enrich up to 10 persons via POST /api/v1/people/bulk_match."""
        details = []
        for p in persons:
            details.append({
                "first_name": p.first_name,
                "last_name": p.last_name,
                "organization_name": p.company,
            })

        body = {
            "reveal_personal_emails": True,
            "reveal_phone_number": True,
            "webhook_url": self._webhook_url,
            "details": details,
        }

        response = await self._request("POST", "/api/v1/people/bulk_match", json=body)
        return ApolloBulkMatchResponse.model_validate(response.json())

    async def enrich_and_save(
        self,
        persons: list[PersonInput],
        repo: Repository,
    ) -> int:
        """Enrich a batch of persons (sync phase) and save to database.

        Stores email and apollo_person_id. Creates webhook tracking entries
        for phone number correlation. Returns count of matched persons.
        """
        batch_id = str(uuid.uuid4())[:8]
        row_ids = [p.row_id for p in persons]
        repo.log_batch("apollo", batch_id, row_ids)

        try:
            if len(persons) == 1:
                result = await self.match_single(persons[0])
                match = result.person
                success = self._save_single_match(
                    persons[0].row_id, match, batch_id, repo
                )
                count = 1 if success else 0
            else:
                result = await self.match_bulk(persons)
                count = self._save_bulk_matches(persons, result, batch_id, repo)

            repo.update_batch_status(batch_id, status="complete")
            return count

        except Exception as exc:
            logger.error("Apollo batch %s failed: %s", batch_id, exc)
            repo.update_batch_status(batch_id, status="error", error=str(exc))
            for p in persons:
                repo.update_apollo_sync_result(
                    p.row_id, status="error", error=str(exc)
                )
            raise

    def _save_single_match(
        self,
        row_id: int,
        match: ApolloPersonMatch | None,
        batch_id: str,
        repo: Repository,
    ) -> bool:
        """Save a single Apollo match result. Returns True if matched."""
        if not match or not match.id:
            repo.update_apollo_sync_result(
                row_id, status="error", error="No match found"
            )
            return False

        raw = json.dumps(match.model_dump(), ensure_ascii=False, default=str)

        repo.update_apollo_sync_result(
            row_id,
            status="awaiting_webhook",
            email=match.email,
            person_id=match.id,
            raw_json=raw,
        )
        repo.create_webhook_tracking(match.id, row_id, batch_id)
        return True

    def _save_bulk_matches(
        self,
        persons: list[PersonInput],
        response: ApolloBulkMatchResponse,
        batch_id: str,
        repo: Repository,
    ) -> int:
        """Save bulk Apollo match results. Returns count of matched persons.

        The bulk_match response returns matches in the same order as the
        details array. A None entry means no match for that position.
        """
        matches = response.matches or []
        success_count = 0

        for i, person in enumerate(persons):
            match = matches[i] if i < len(matches) else None

            if match is None or not match.id:
                repo.update_apollo_sync_result(
                    person.row_id, status="error", error="No match found"
                )
                continue

            raw = json.dumps(match.model_dump(), ensure_ascii=False, default=str)

            repo.update_apollo_sync_result(
                person.row_id,
                status="awaiting_webhook",
                email=match.email,
                person_id=match.id,
                raw_json=raw,
            )
            repo.create_webhook_tracking(match.id, person.row_id, batch_id)
            success_count += 1

        return success_count
