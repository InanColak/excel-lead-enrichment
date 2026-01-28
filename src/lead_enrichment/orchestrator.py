"""Enrichment pipeline orchestrator.

Coordinates the 5-phase enrichment process:
1. Load Excel into SQLite
2. Lusha enrichment (synchronous)
3. Apollo sync enrichment (email + webhook registration)
4. Wait for Apollo webhooks (phone numbers)
5. Export enriched Excel
"""

from __future__ import annotations

import asyncio
import logging
import time
from pathlib import Path

from .clients.apollo import ApolloClient
from .clients.lusha import LushaClient
from .config import Settings
from .db.repository import Repository
from .excel.reader import (
    detect_columns,
    get_persons_from_db,
    load_excel_to_db,
    read_excel_headers_and_samples,
)
from .excel.writer import write_enriched_excel
from .models import PersonInput
from .webhook.runner import WebhookServerRunner

logger = logging.getLogger(__name__)


def _chunked(items: list, size: int) -> list[list]:
    """Split a list into chunks of the given size."""
    return [items[i : i + size] for i in range(0, len(items), size)]


class EnrichmentService:
    """Main service class that orchestrates the entire enrichment pipeline.

    This is the primary Python API — designed to be called programmatically
    by a CLI, an MCP tool, or any other integration layer.
    """

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._repo = Repository(settings.db_path)

    @property
    def repo(self) -> Repository:
        return self._repo

    def close(self) -> None:
        self._repo.close()

    # ── Phase 1: Load Excel ──────────────────────────────────────

    def load_excel(self, input_path: Path) -> int:
        """Phase 1: Read Excel and load rows into the database.

        Uses OpenAI to detect column mappings automatically.
        Returns the number of rows loaded.
        """
        logger.info("Phase 1: Loading Excel from %s", input_path)

        headers, samples = read_excel_headers_and_samples(input_path)
        logger.info("Excel headers: %s", headers)

        column_mapping = detect_columns(
            headers, samples, self._settings.openai_api_key
        )
        logger.info(
            "Detected columns: first_name='%s', last_name='%s', company='%s'",
            column_mapping.first_name_col,
            column_mapping.last_name_col,
            column_mapping.company_col,
        )

        total = load_excel_to_db(input_path, self._repo, column_mapping)
        self._repo.set_metadata("input_file", str(input_path))
        self._repo.set_metadata("total_rows", str(total))
        logger.info("Phase 1 complete: %d rows loaded", total)
        return total

    # ── Phase 2: Lusha Enrichment ────────────────────────────────

    async def enrich_lusha(self) -> dict:
        """Phase 2: Enrich all pending rows via Lusha (fully synchronous)."""
        logger.info("Phase 2: Lusha enrichment")

        pending = get_persons_from_db(self._repo, "lusha", "pending")
        if not pending:
            logger.info("No pending Lusha rows")
            return {"processed": 0, "success": 0}

        total_success = 0
        batches = _chunked(pending, self._settings.lusha_batch_size)

        async with LushaClient(self._settings) as client:
            for i, batch in enumerate(batches, 1):
                logger.info("Lusha batch %d/%d (%d persons)", i, len(batches), len(batch))
                try:
                    count = await client.enrich_and_save(batch, self._repo)
                    total_success += count
                except Exception:
                    logger.exception("Lusha batch %d failed", i)

        logger.info("Phase 2 complete: %d/%d enriched", total_success, len(pending))
        return {"processed": len(pending), "success": total_success}

    # ── Phase 3: Apollo Sync Enrichment ──────────────────────────

    async def enrich_apollo_sync(self) -> dict:
        """Phase 3: Enrich all pending rows via Apollo (sync phase — email only).

        Phone numbers will arrive via webhook in Phase 4.
        """
        logger.info("Phase 3: Apollo sync enrichment")

        pending = get_persons_from_db(self._repo, "apollo", "pending")
        if not pending:
            logger.info("No pending Apollo rows")
            return {"processed": 0, "matched": 0}

        total_matched = 0
        batches = _chunked(pending, self._settings.apollo_batch_size)

        async with ApolloClient(self._settings) as client:
            for i, batch in enumerate(batches, 1):
                logger.info(
                    "Apollo batch %d/%d (%d persons)", i, len(batches), len(batch)
                )
                try:
                    count = await client.enrich_and_save(batch, self._repo)
                    total_matched += count
                except Exception:
                    logger.exception("Apollo batch %d failed", i)

        logger.info("Phase 3 complete: %d/%d matched", total_matched, len(pending))
        return {"processed": len(pending), "matched": total_matched}

    # ── Phase 4: Wait for Webhooks ───────────────────────────────

    async def wait_for_webhooks(self) -> dict:
        """Phase 4: Wait for all Apollo webhook callbacks to arrive.

        Polls the database periodically. Returns when all webhooks are
        received or the timeout is reached.
        """
        logger.info("Phase 4: Waiting for Apollo webhooks")

        total_expected = self._repo.count_total_webhooks()
        if total_expected == 0:
            logger.info("No webhooks expected")
            return {"expected": 0, "received": 0, "timed_out": 0}

        deadline = time.time() + self._settings.webhook_timeout_seconds
        poll_interval = 5  # seconds

        while time.time() < deadline:
            pending = self._repo.count_pending_webhooks()
            received = total_expected - pending

            if pending == 0:
                logger.info("All %d webhooks received!", total_expected)
                return {
                    "expected": total_expected,
                    "received": total_expected,
                    "timed_out": 0,
                }

            remaining_secs = int(deadline - time.time())
            logger.info(
                "Webhooks: %d/%d received. Timeout in %ds",
                received,
                total_expected,
                remaining_secs,
            )
            await asyncio.sleep(poll_interval)

        # Timeout reached
        timed_out = self._repo.mark_webhook_timeouts()
        logger.warning("%d webhook(s) timed out", timed_out)

        received = total_expected - timed_out
        return {
            "expected": total_expected,
            "received": received,
            "timed_out": timed_out,
        }

    # ── Phase 5: Export ──────────────────────────────────────────

    def export_excel(self, input_path: Path, output_path: Path) -> Path:
        """Phase 5: Write enriched data back to Excel."""
        logger.info("Phase 5: Exporting enriched Excel")
        result = write_enriched_excel(input_path, output_path, self._repo)
        logger.info("Export complete: %s", result)
        return result

    # ── Full Pipeline ────────────────────────────────────────────

    async def run_full_pipeline(
        self,
        input_path: Path,
        output_path: Path,
    ) -> dict:
        """Run the complete 5-phase enrichment pipeline.

        Starts the webhook server, enriches via both APIs, waits for
        Apollo webhooks, and exports the result.
        """
        logger.info("Starting full enrichment pipeline")
        results: dict = {}

        # Phase 1: Load
        total = self.load_excel(input_path)
        results["total_rows"] = total

        # Start webhook server for Phase 3+4
        webhook_runner = WebhookServerRunner(
            host="0.0.0.0",
            port=self._settings.webhook_port,
            repo=self._repo,
        )
        webhook_runner.start()

        try:
            # Phase 2: Lusha (fully sync)
            results["lusha"] = await self.enrich_lusha()

            # Phase 3: Apollo sync (email + webhook registration)
            results["apollo_sync"] = await self.enrich_apollo_sync()

            # Phase 4: Wait for Apollo webhooks
            results["apollo_webhooks"] = await self.wait_for_webhooks()

        finally:
            webhook_runner.stop()

        # Phase 5: Export
        self.export_excel(input_path, output_path)
        results["output_file"] = str(output_path)

        # Summary
        summary = self._repo.get_status_summary()
        results["summary"] = summary
        self._print_summary(summary)

        return results

    def get_status(self) -> dict:
        """Get current enrichment progress."""
        return self._repo.get_status_summary()

    def _print_summary(self, summary: dict) -> None:
        total = summary["total_rows"]
        logger.info("=" * 50)
        logger.info("ENRICHMENT SUMMARY")
        logger.info("=" * 50)
        logger.info("Total rows: %d", total)
        logger.info(
            "Lusha: %d complete, %d errors, %d pending",
            summary["lusha"]["complete"],
            summary["lusha"]["error"],
            summary["lusha"]["pending"],
        )
        logger.info(
            "Apollo: %d complete, %d awaiting webhook, %d timeout, %d errors, %d pending",
            summary["apollo"]["complete"],
            summary["apollo"]["awaiting_webhook"],
            summary["apollo"]["timeout"],
            summary["apollo"]["error"],
            summary["apollo"]["pending"],
        )
        logger.info("=" * 50)
