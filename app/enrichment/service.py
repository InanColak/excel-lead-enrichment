"""Enrichment orchestration service.

Core business logic for processing confirmed jobs: deduplicates contacts,
checks the local database, calls Apollo for unknowns, writes results by
row UUID, and tracks progress metrics.

No Celery dependency -- pure async functions accepting a session factory.
"""

import logging
import uuid
from collections import defaultdict
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import settings
from app.contacts.models import Contact
from app.enrichment.apollo_client import (
    ApolloClient,
    ApolloClientError,
    ApolloNotFoundError,
    ApolloTransientError,
    _get_api_key_from_db,
)
from app.enrichment.schemas import ApolloEnrichResponse
from app.jobs.models import Job, JobRow, RowStatus

logger = logging.getLogger(__name__)

# Progress flush interval (rows processed before committing metrics)
PROGRESS_FLUSH_INTERVAL = 50


def extract_field(
    raw_data: dict, column_mappings: list[dict], field_type: str
) -> Optional[str]:
    """Extract a field value from raw_data using column mappings.

    Finds the column mapping entry where detected_type == field_type,
    then returns the corresponding value from raw_data.

    For email and linkedin_url: stripped and lowered.
    For names and company: stripped only.
    Returns None if not found or empty.
    """
    for mapping in column_mappings:
        if mapping.get("detected_type") == field_type:
            column_name = mapping.get("column")
            if column_name is None:
                continue
            value = raw_data.get(column_name)
            if value is None:
                continue
            value_str = str(value).strip()
            if not value_str:
                continue
            if field_type in ("email", "linkedin_url"):
                return value_str.lower()
            return value_str
    return None


def build_dedup_groups(
    rows: list[JobRow], column_mappings: list[dict]
) -> dict[str, list[JobRow]]:
    """Group rows by normalized contact identity for deduplication.

    Per D-48: duplicate contacts within a single upload result in exactly
    one Apollo API call per unique contact.

    Key logic:
    - If row has email: key = "email:{email.strip().lower()}"
    - Elif row has linkedin_url: key = "linkedin:{linkedin_url.strip().lower()}"
    - Else: key = "row:{row.id}" (treat as unique)

    Rows with status != "pending" are skipped.
    """
    groups: dict[str, list[JobRow]] = defaultdict(list)

    for row in rows:
        if row.status != RowStatus.PENDING.value:
            continue

        email = extract_field(row.raw_data, column_mappings, "email")
        linkedin_url = extract_field(row.raw_data, column_mappings, "linkedin_url")

        if email:
            key = f"email:{email}"
        elif linkedin_url:
            key = f"linkedin:{linkedin_url}"
        else:
            key = f"row:{str(row.id)}"

        groups[key].append(row)

    return dict(groups)


async def batch_contact_lookup(
    db: AsyncSession, groups: dict[str, list[JobRow]]
) -> dict[str, Contact]:
    """Batch lookup contacts in the local database.

    Per D-47: database-first lookup before any API call.
    Per Pitfall 6: batch query, not N+1.

    Returns dict mapping group key -> Contact for found contacts.
    """
    found: dict[str, Contact] = {}

    # Collect email and linkedin keys
    email_keys: dict[str, str] = {}  # email -> group_key
    linkedin_keys: dict[str, str] = {}  # linkedin_url -> group_key

    for key, _rows in groups.items():
        if key.startswith("email:"):
            email = key[len("email:"):]
            email_keys[email] = key
        elif key.startswith("linkedin:"):
            linkedin_url = key[len("linkedin:"):]
            linkedin_keys[linkedin_url] = key

    # Batch query for email-keyed groups
    if email_keys:
        email_list = list(email_keys.keys())
        result = await db.execute(
            select(Contact).where(Contact.email.in_(email_list))
        )
        contacts = result.scalars().all()
        for contact in contacts:
            if contact.email and contact.email.lower() in email_keys:
                group_key = email_keys[contact.email.lower()]
                found[group_key] = contact

    # Batch query for linkedin-keyed groups
    if linkedin_keys:
        linkedin_list = list(linkedin_keys.keys())
        result = await db.execute(
            select(Contact).where(Contact.linkedin_url.in_(linkedin_list))
        )
        contacts = result.scalars().all()
        for contact in contacts:
            if contact.linkedin_url and contact.linkedin_url.lower() in linkedin_keys:
                group_key = linkedin_keys[contact.linkedin_url.lower()]
                found[group_key] = contact

    return found


async def process_job(
    job_id: uuid.UUID, session_factory: async_sessionmaker
) -> None:
    """Main enrichment orchestration function.

    Per D-50: single orchestrator per job.
    Per ENRICH-08: each job gets its own session -- no shared state.
    Per ENRICH-09: never reads/modifies the original .xlsx file.
    Per ENRICH-01: rows identified by UUID throughout.

    Steps:
    a. Transition job to PROCESSING
    b. Load pending rows
    c. Build dedup groups
    d. Batch contact lookup (DB-first)
    e. Call Apollo for cache misses
    f. Track progress metrics
    g. Transition to AWAITING_WEBHOOKS or COMPLETE
    """
    async with session_factory() as db:
        try:
            # a. Load job and transition to PROCESSING
            result = await db.execute(select(Job).where(Job.id == job_id))
            job = result.scalar_one_or_none()
            if job is None:
                logger.error(f"Job {job_id} not found")
                return
            job.status = "processing"
            await db.commit()

            # b. Load all pending rows ordered by row_index
            result = await db.execute(
                select(JobRow)
                .where(JobRow.job_id == job_id)
                .where(JobRow.status == RowStatus.PENDING.value)
                .order_by(JobRow.row_index)
            )
            rows = result.scalars().all()

            if not rows:
                logger.info(f"Job {job_id}: no pending rows to process")
                job.status = "complete"
                await db.commit()
                return

            # c. Build dedup groups
            groups = build_dedup_groups(rows, job.column_mappings or [])

            # d. Batch contact lookup
            cached_contacts = await batch_contact_lookup(db, groups)

            # e. Read API key and build Apollo client
            api_key = await _get_api_key_from_db(db)
            webhook_url = None
            if settings.webhook_base_url:
                webhook_url = f"{settings.webhook_base_url}/api/v1/webhooks/apollo"

            apollo_client = ApolloClient(api_key=api_key, webhook_url=webhook_url)

            # f. Initialize counters
            cache_hits = 0
            api_calls = 0
            processed = 0

            try:
                # g. Process each group
                for group_key, group_rows in groups.items():
                    if group_key in cached_contacts:
                        # Cache hit -- link all rows to existing contact
                        contact = cached_contacts[group_key]
                        for row in group_rows:
                            row.contact_id = contact.id
                            row.status = "enriched"
                        cache_hits += 1
                        processed += len(group_rows)
                    else:
                        # Cache miss -- call Apollo
                        first_row = group_rows[0]
                        mappings = job.column_mappings or []
                        first_name = extract_field(first_row.raw_data, mappings, "first_name")
                        last_name = extract_field(first_row.raw_data, mappings, "last_name")
                        organization_name = extract_field(first_row.raw_data, mappings, "company")
                        email = extract_field(first_row.raw_data, mappings, "email")
                        linkedin_url = extract_field(first_row.raw_data, mappings, "linkedin_url")

                        try:
                            response: ApolloEnrichResponse = await apollo_client.enrich_person(
                                first_name=first_name,
                                last_name=last_name,
                                organization_name=organization_name,
                                email=email,
                                linkedin_url=linkedin_url,
                            )

                            # Create or update Contact record
                            contact = Contact(
                                email=response.person.email if response.person else email,
                                first_name=response.person.first_name if response.person else first_name,
                                last_name=response.person.last_name if response.person else last_name,
                                company=(
                                    response.person.organization.name
                                    if response.person and response.person.organization
                                    else organization_name
                                ),
                                linkedin_url=response.person.linkedin_url if response.person else linkedin_url,
                                apollo_id=response.person.id if response.person else None,
                                raw_apollo_response=response.model_dump(),
                            )
                            db.add(contact)
                            await db.flush()

                            # Link all rows in group to this contact
                            for row in group_rows:
                                row.contact_id = contact.id
                                row.status = "enriched"

                            api_calls += 1
                            processed += len(group_rows)

                        except ApolloNotFoundError:
                            # Per D-40: mark as not_found, still counts as API call
                            for row in group_rows:
                                row.status = "not_found"
                                row.error_message = "Contact not found in Apollo"
                            api_calls += 1
                            processed += len(group_rows)

                        except ApolloClientError as e:
                            # Non-retryable error (bad API key, etc.)
                            logger.error(f"Job {job_id}: Apollo client error for group {group_key}: {e}")
                            for row in group_rows:
                                row.status = "error"
                                row.error_message = str(e)
                            processed += len(group_rows)

                        except ApolloTransientError as e:
                            # Per D-40: after retries exhausted, mark as not_found
                            logger.error(f"Job {job_id}: Apollo transient error for group {group_key}: {e}")
                            for row in group_rows:
                                row.status = "not_found"
                                row.error_message = f"Apollo API failure after retries: {e}"
                            api_calls += 1
                            processed += len(group_rows)

                    # Flush progress every PROGRESS_FLUSH_INTERVAL rows
                    if processed % PROGRESS_FLUSH_INTERVAL == 0 and processed > 0:
                        job.processed_rows = processed
                        job.cache_hits = cache_hits
                        job.api_calls = api_calls
                        await db.commit()

            finally:
                await apollo_client.close()

            # h. Final metrics update
            job.processed_rows = processed
            job.cache_hits = cache_hits
            job.api_calls = api_calls

            # i. Transition job status
            if api_calls > 0:
                # Webhooks expected for API calls -- wait for phone data
                job.status = "awaiting_webhooks"
            else:
                # All cache hits -- determine final status per D-52
                all_rows_result = await db.execute(
                    select(JobRow).where(JobRow.job_id == job_id)
                )
                all_rows = all_rows_result.scalars().all()
                enriched_count = sum(1 for r in all_rows if r.status == "enriched")
                not_found_count = sum(1 for r in all_rows if r.status == RowStatus.NOT_FOUND.value)
                error_count = sum(
                    1 for r in all_rows
                    if r.status in (RowStatus.ERROR.value, RowStatus.SKIPPED.value)
                )

                if enriched_count == 0 and (not_found_count > 0 or error_count > 0):
                    job.status = "failed"
                elif not_found_count > 0 or error_count > 0:
                    job.status = "partial"
                else:
                    job.status = "complete"

            # j. Final commit
            await db.commit()
            logger.info(
                f"Job {job_id} processed: status={job.status}, "
                f"processed={processed}, cache_hits={cache_hits}, api_calls={api_calls}"
            )

        except Exception:
            # Catastrophic error -- mark job as failed
            logger.exception(f"Job {job_id} failed with unexpected error")
            try:
                result = await db.execute(select(Job).where(Job.id == job_id))
                job = result.scalar_one_or_none()
                if job:
                    job.status = "failed"
                    await db.commit()
            except Exception:
                logger.exception(f"Failed to mark job {job_id} as failed")
            raise
