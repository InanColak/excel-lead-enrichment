"""Enrichment orchestration service.

Core business logic for processing confirmed jobs: deduplicates contacts,
checks the local database, calls Apollo for unknowns, writes results by
row UUID, and tracks progress metrics.

No Celery dependency -- pure async functions accepting a session factory.
"""

import asyncio
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
    ApolloTransientError,
    _get_api_key_from_db,
)
from app.enrichment.schemas import extract_best_phone
from app.jobs.models import Job, JobRow, RowStatus
from app.jobs.output import generate_output_file

logger = logging.getLogger(__name__)

# Progress flush interval (rows processed before committing metrics)
PROGRESS_FLUSH_INTERVAL = 50


def extract_field(
    raw_data: dict, column_mappings: list[dict], field_type: str
) -> Optional[str]:
    """Extract a field value from raw_data using column mappings.

    Finds the FIRST column mapping entry where detected_type == field_type,
    then returns the corresponding value from raw_data.
    Only uses the first matching column — never falls through to other
    columns of the same type (prevents e.g. "Total Funding" being used
    when "Mobile Phone" is empty).

    For email and linkedin_url: stripped and lowered.
    For names and company: stripped only.
    Returns None if not found or empty.
    """
    for mapping in column_mappings:
        if mapping.get("detected_type") == field_type:
            column_name = mapping.get("column")
            if column_name is None:
                return None
            value = raw_data.get(column_name)
            if value is None:
                return None
            value_str = str(value).strip()
            if not value_str:
                return None
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
                # g. Separate cache hits from API-needed groups
                api_groups: list[tuple[str, list[JobRow]]] = []

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
                        # Check if file already has email + phone
                        first_row = group_rows[0]
                        mappings = job.column_mappings or []
                        email = extract_field(first_row.raw_data, mappings, "email")
                        phone = extract_field(first_row.raw_data, mappings, "phone")

                        if email and phone:
                            contact = Contact(
                                email=email,
                                first_name=extract_field(first_row.raw_data, mappings, "first_name"),
                                last_name=extract_field(first_row.raw_data, mappings, "last_name"),
                                company=extract_field(first_row.raw_data, mappings, "company"),
                                linkedin_url=extract_field(first_row.raw_data, mappings, "linkedin_url"),
                                phone=phone,
                            )
                            db.add(contact)
                            await db.flush()
                            await db.commit()

                            for row in group_rows:
                                row.contact_id = contact.id
                                row.status = "enriched"
                            cache_hits += 1
                            processed += len(group_rows)
                            logger.info(
                                f"Skipped Apollo for group {group_key}: "
                                f"email+phone already in file"
                            )
                        else:
                            api_groups.append((group_key, group_rows))

                # h. Process API-needed groups in bulk batches of 10 with 30s delay
                batch_size = settings.bulk_batch_size
                for batch_start in range(0, len(api_groups), batch_size):
                    batch = api_groups[batch_start:batch_start + batch_size]
                    batch_num = batch_start // batch_size + 1
                    total_batches = (len(api_groups) + batch_size - 1) // batch_size

                    # Build bulk request details
                    details = []
                    batch_meta = []  # track group_key and group_rows per detail entry
                    for group_key, group_rows in batch:
                        first_row = group_rows[0]
                        mappings = job.column_mappings or []
                        entry: dict = {}
                        first_name = extract_field(first_row.raw_data, mappings, "first_name")
                        last_name = extract_field(first_row.raw_data, mappings, "last_name")
                        organization_name = extract_field(first_row.raw_data, mappings, "company")
                        email = extract_field(first_row.raw_data, mappings, "email")
                        linkedin_url = extract_field(first_row.raw_data, mappings, "linkedin_url")

                        if first_name:
                            entry["first_name"] = first_name
                        if last_name:
                            entry["last_name"] = last_name
                        if organization_name:
                            entry["organization_name"] = organization_name
                        if email:
                            entry["email"] = email
                        if linkedin_url:
                            entry["linkedin_url"] = linkedin_url

                        details.append(entry)
                        batch_meta.append((group_key, group_rows, {
                            "first_name": first_name,
                            "last_name": last_name,
                            "organization_name": organization_name,
                            "email": email,
                            "linkedin_url": linkedin_url,
                        }))

                    try:
                        bulk_response = await apollo_client.bulk_enrich_people(details)

                        # Process each match in the response
                        for i, (group_key, group_rows, fields) in enumerate(batch_meta):
                            person = bulk_response.matches[i] if i < len(bulk_response.matches) else None

                            if person is None:
                                for row in group_rows:
                                    row.status = "not_found"
                                    row.error_message = "Contact not found in Apollo"
                                api_calls += 1
                                processed += len(group_rows)
                                continue

                            # Extract phone from response
                            initial_phone = None
                            if person.phone_numbers:
                                initial_phone = extract_best_phone(person.phone_numbers)

                            contact = Contact(
                                email=person.email or fields["email"],
                                first_name=person.first_name or fields["first_name"],
                                last_name=person.last_name or fields["last_name"],
                                company=(
                                    person.organization.name
                                    if person.organization
                                    else fields["organization_name"]
                                ),
                                linkedin_url=person.linkedin_url or fields["linkedin_url"],
                                apollo_id=person.id,
                                phone=initial_phone,
                                raw_apollo_response={"person": person.model_dump()},
                            )
                            db.add(contact)
                            await db.flush()

                            for row in group_rows:
                                row.contact_id = contact.id
                                row.status = "enriched"

                            api_calls += 1
                            processed += len(group_rows)

                        await db.commit()

                    except ApolloClientError as e:
                        logger.error(f"Job {job_id}: Apollo bulk error batch {batch_num}: {e}")
                        for group_key, group_rows, fields in batch_meta:
                            for row in group_rows:
                                row.status = "error"
                                row.error_message = str(e)
                            processed += len(group_rows)
                        await db.commit()

                    except ApolloTransientError as e:
                        logger.error(f"Job {job_id}: Apollo transient error batch {batch_num}: {e}")
                        for group_key, group_rows, fields in batch_meta:
                            for row in group_rows:
                                row.status = "not_found"
                                row.error_message = f"Apollo API failure after retries: {e}"
                            api_calls += 1
                            processed += len(group_rows)
                        await db.commit()

                    # Update progress
                    job.processed_rows = processed
                    job.cache_hits = cache_hits
                    job.api_calls = api_calls
                    await db.commit()

                    logger.info(
                        f"Job {job_id}: batch {batch_num}/{total_batches} done, "
                        f"processed={processed}"
                    )

                    # Wait between batches (skip delay after last batch)
                    if batch_start + batch_size < len(api_groups):
                        await asyncio.sleep(settings.bulk_batch_delay_seconds)

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

            # Generate output file for complete/partial jobs (per D-64)
            if job.status in ("complete", "partial"):
                await generate_output_file(job_id, session_factory)

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
