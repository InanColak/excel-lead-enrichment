"""Lusha API client for person enrichment."""

from __future__ import annotations

import json
import logging
import uuid

from ..config import Settings
from ..db.repository import Repository
from ..models import (
    LushaBulkContact,
    LushaContactData,
    LushaPersonResponse,
    PersonInput,
)
from ..utils.phone import classify_lusha_phones
from ..utils.retry import with_retry
from .base import BaseAPIClient
from .rate_limiter import TokenBucketRateLimiter

logger = logging.getLogger(__name__)

LUSHA_BASE_URL = "https://api.lusha.com"


class LushaClient(BaseAPIClient):
    """Client for Lusha person enrichment API."""

    def __init__(self, settings: Settings) -> None:
        limiter = TokenBucketRateLimiter(
            rate=settings.lusha_rate_per_second,
            per=1.0,
        )
        super().__init__(
            settings=settings,
            rate_limiter=limiter,
            base_url=LUSHA_BASE_URL,
            headers={
                "api_key": settings.lusha_api_key,
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
        )

    @with_retry(max_attempts=3)
    async def enrich_single(self, person: PersonInput) -> LushaPersonResponse:
        """Enrich a single person via GET /v2/person."""
        response = await self._request(
            "GET",
            "/v2/person",
            params={
                "firstName": person.first_name,
                "lastName": person.last_name,
                "companyName": person.company,
            },
        )
        return LushaPersonResponse.model_validate(response.json())

    @with_retry(max_attempts=3)
    async def enrich_bulk(self, persons: list[PersonInput]) -> dict[str, LushaBulkContact]:
        """Enrich up to 100 persons via POST /v2/person.

        Returns a dict where keys are contactId (row_id as string).
        """
        contacts = []
        for p in persons:
            contacts.append({
                "contactId": str(p.row_id),
                "fullName": f"{p.first_name} {p.last_name}",
                "companies": [{"name": p.company, "isCurrent": True}],
            })

        body = {
            "contacts": contacts,
            "metadata": {
                "revealEmails": True,
                "revealPhones": True,
                "partialProfile": True,
            },
        }

        response = await self._request("POST", "/v2/person", json=body)
        raw_data = response.json()

        # Lusha bulk returns {"contacts": {contactId: {error, data, ...}, ...}, "companies": {...}}
        contacts_dict = raw_data.get("contacts", {})
        result: dict[str, LushaBulkContact] = {}
        for contact_id, contact_data in contacts_dict.items():
            result[contact_id] = LushaBulkContact.model_validate(contact_data)
        return result

    async def enrich_and_save(
        self,
        persons: list[PersonInput],
        repo: Repository,
    ) -> int:
        """Enrich a batch of persons and save results to the database.

        Returns the number of successfully enriched contacts.
        """
        batch_id = str(uuid.uuid4())[:8]
        row_ids = [p.row_id for p in persons]
        repo.log_batch("lusha", batch_id, row_ids)

        try:
            if len(persons) == 1:
                result = await self.enrich_single(persons[0])
                self._save_single_result(persons[0].row_id, result, repo)
                success_count = 1 if result.contact and result.contact.data else 0
            else:
                result = await self.enrich_bulk(persons)
                success_count = self._save_bulk_results(persons, result, repo)

            repo.update_batch_status(batch_id, status="complete")
            return success_count

        except Exception as exc:
            logger.error("Lusha batch %s failed: %s", batch_id, exc)
            repo.update_batch_status(batch_id, status="error", error=str(exc))
            for p in persons:
                repo.update_lusha_result(p.row_id, status="error", error=str(exc))
            raise

    def _save_single_result(
        self,
        row_id: int,
        response: LushaPersonResponse,
        repo: Repository,
    ) -> None:
        """Save a single Lusha response to the database."""
        if not response.contact or response.contact.error:
            error = response.contact.error if response.contact else "No contact returned"
            repo.update_lusha_result(row_id, status="error", error=error)
            return

        data = response.contact.data
        if not data:
            repo.update_lusha_result(row_id, status="error", error="No data in contact")
            return

        self._save_contact_data(row_id, data, repo)

    def _save_bulk_results(
        self,
        persons: list[PersonInput],
        results_by_id: dict[str, LushaBulkContact],
        repo: Repository,
    ) -> int:
        """Save bulk Lusha results. Returns count of successful enrichments."""
        success_count = 0
        for person in persons:
            contact = results_by_id.get(str(person.row_id))
            if not contact or contact.error:
                error = contact.error if contact else "No result returned"
                repo.update_lusha_result(person.row_id, status="error", error=error)
                continue

            if not contact.data:
                repo.update_lusha_result(
                    person.row_id, status="error", error="No data in contact"
                )
                continue

            self._save_contact_data(person.row_id, contact.data, repo)
            success_count += 1

        return success_count

    def _save_contact_data(
        self,
        row_id: int,
        data: LushaContactData,
        repo: Repository,
    ) -> None:
        """Extract email and phone from Lusha contact data and save to DB."""
        # Pick the best email (prefer work/business)
        email: str | None = None
        for addr in data.email_addresses:
            if addr.email:
                if addr.email_type in ("work", "business") or not email:
                    email = addr.email

        # Classify phone numbers
        phones = classify_lusha_phones(data.phone_numbers)

        raw_json = json.dumps(
            data.model_dump(by_alias=True),
            ensure_ascii=False,
            default=str,
        )

        repo.update_lusha_result(
            row_id,
            status="complete",
            email=email,
            mobile=phones["mobile"],
            direct=phones["direct_dial"],
            raw_json=raw_json,
        )
