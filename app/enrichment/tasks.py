"""Celery task wrappers for the enrichment pipeline.

Two tasks:
1. process_enrichment_job -- main enrichment orchestrator
2. check_webhook_completion -- delayed webhook timeout checker

Per Pitfall 1: creates standalone async engine, no FastAPI deps.
Per Pitfall 2: job_id passed as str, converted to UUID inside.
"""

import asyncio
import logging
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.celery_app import celery_app
from app.config import settings
from app.contacts.models import Contact
from app.enrichment.service import process_job
from app.jobs.models import Job, JobRow, RowStatus
from app.jobs.output import generate_output_file

logger = logging.getLogger(__name__)


def _get_session_factory() -> async_sessionmaker[AsyncSession]:
    """Create a standalone async session factory for Celery tasks.

    Per Pitfall 1: Celery runs outside FastAPI -- cannot use get_db().
    Per Pitfall 4: creates engine per task invocation (acceptable for job-level granularity).
    """
    engine = create_async_engine(settings.database_url, echo=False)
    return async_sessionmaker(engine, expire_on_commit=False)


@celery_app.task(bind=True, acks_late=True, reject_on_worker_lost=True, time_limit=3600)
def process_enrichment_job(self, job_id: str):
    """Celery task: process a confirmed enrichment job.

    Per D-50: single orchestrator task per job.
    Per Pitfall 2: job_id passed as str, converted to UUID inside.
    Per T-03-05: time_limit=3600 prevents runaway tasks.
    """
    logger.info(f"Starting enrichment job {job_id}")
    session_factory = _get_session_factory()
    try:
        asyncio.run(_run_enrichment(job_id, session_factory))
    except Exception:
        logger.exception(f"Enrichment job {job_id} failed")
        # Mark job as FAILED on catastrophic error
        asyncio.run(_mark_job_failed(job_id, session_factory))
        raise


async def _run_enrichment(job_id: str, session_factory: async_sessionmaker):
    """Run the enrichment pipeline and schedule webhook checker if needed."""
    job_uuid = uuid.UUID(job_id)
    await process_job(job_uuid, session_factory)

    # Check if job is now AWAITING_WEBHOOKS -- if so, schedule the timeout checker
    async with session_factory() as db:
        result = await db.execute(select(Job).where(Job.id == job_uuid))
        job = result.scalar_one_or_none()
        if job and job.status == "awaiting_webhooks":
            # Per D-53: schedule delayed check after webhook_timeout_seconds
            check_webhook_completion.apply_async(
                args=[job_id],
                countdown=settings.webhook_timeout_seconds,
            )
            logger.info(
                f"Scheduled webhook completion check for job {job_id} "
                f"in {settings.webhook_timeout_seconds}s"
            )


async def _mark_job_failed(job_id: str, session_factory: async_sessionmaker):
    """Mark a job as FAILED after catastrophic error."""
    try:
        async with session_factory() as db:
            result = await db.execute(
                select(Job).where(Job.id == uuid.UUID(job_id))
            )
            job = result.scalar_one_or_none()
            if job:
                job.status = "failed"
                await db.commit()
    except Exception:
        logger.exception(f"Failed to mark job {job_id} as failed")


@celery_app.task(bind=True, acks_late=True)
def check_webhook_completion(self, job_id: str):
    """Celery task: check if all webhooks arrived after timeout period.

    Per D-53: scheduled with countdown=webhook_timeout_seconds after API calls complete.
    Per D-52: determines final job status (COMPLETE vs PARTIAL vs FAILED).
    """
    logger.info(f"Checking webhook completion for job {job_id}")
    session_factory = _get_session_factory()
    asyncio.run(_check_webhook_completion_async(job_id, session_factory))


async def _check_webhook_completion_async(
    job_id: str, session_factory: async_sessionmaker
):
    """Check webhook completion and finalize job status.

    Per D-53: mark remaining rows email-only when phone webhook timed out.
    Per D-52: determine final status based on row statuses.
    """
    job_uuid = uuid.UUID(job_id)
    async with session_factory() as db:
        result = await db.execute(select(Job).where(Job.id == job_uuid))
        job = result.scalar_one_or_none()
        if not job or job.status != "awaiting_webhooks":
            logger.info(
                f"Job {job_id} is not awaiting webhooks "
                f"(status={job.status if job else 'missing'}), skipping"
            )
            return

        # Find enriched rows to check for webhook timeouts
        result = await db.execute(
            select(JobRow)
            .where(JobRow.job_id == job_uuid)
            .where(JobRow.status == RowStatus.ENRICHED.value)
        )
        enriched_rows = result.scalars().all()

        # Check each enriched row's contact for phone status
        webhook_timeouts = 0
        for row in enriched_rows:
            if row.contact_id:
                contact_result = await db.execute(
                    select(Contact).where(Contact.id == row.contact_id)
                )
                contact = contact_result.scalar_one_or_none()
                if contact and contact.apollo_id and not contact.phone:
                    # Per D-53: contact had Apollo API call (has apollo_id) but no
                    # phone arrived via webhook. Mark the JobRow as EMAIL_ONLY so
                    # Phase 4 Excel generation can distinguish these rows.
                    row.status = "email_only"
                    webhook_timeouts += 1
                    logger.info(
                        f"Row {row.id} marked email_only: webhook timed out "
                        f"for apollo_id={contact.apollo_id}"
                    )

        job.webhook_timeouts = webhook_timeouts

        # Determine final status per D-52
        all_rows_result = await db.execute(
            select(JobRow).where(JobRow.job_id == job_uuid)
        )
        all_rows = all_rows_result.scalars().all()

        enriched_count = sum(
            1 for r in all_rows if r.status in (RowStatus.ENRICHED.value, "email_only")
        )
        not_found_count = sum(
            1 for r in all_rows if r.status == RowStatus.NOT_FOUND.value
        )
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

        await db.commit()

        # Generate output file for complete/partial jobs (per D-64)
        if job.status in ("complete", "partial"):
            await generate_output_file(job_uuid, session_factory)

        logger.info(
            f"Job {job_id} finalized: status={job.status}, "
            f"webhook_timeouts={webhook_timeouts}"
        )
