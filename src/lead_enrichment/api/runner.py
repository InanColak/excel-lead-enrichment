"""Background task runner for enrichment jobs."""

from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING

import httpx

from .schemas import APIStatusCounts, CallbackPayload, RunStatus

if TYPE_CHECKING:
    from ..orchestrator import EnrichmentService

logger = logging.getLogger(__name__)


class EnrichmentRunner:
    """Manages background enrichment tasks."""

    def __init__(self) -> None:
        self._runs: dict[str, dict] = {}
        self._tasks: dict[str, asyncio.Task] = {}

    def create_run(
        self,
        input_file: str,
        callback_url: str | None = None,
        user_email: str | None = None,
    ) -> str:
        """Create a new run and return its ID."""
        run_id = str(uuid.uuid4())[:8]
        self._runs[run_id] = {
            "run_id": run_id,
            "status": RunStatus.PENDING,
            "input_file": input_file,
            "output_file": None,
            "total_rows": 0,
            "started_at": datetime.now(timezone.utc),
            "completed_at": None,
            "error_message": None,
            "callback_url": callback_url,
            "user_email": user_email,
            "lusha": {"complete": 0, "error": 0, "pending": 0},
            "apollo": {
                "complete": 0,
                "error": 0,
                "pending": 0,
                "awaiting_webhook": 0,
                "timeout": 0,
            },
        }
        return run_id

    def get_run(self, run_id: str) -> dict | None:
        """Get run status by ID."""
        return self._runs.get(run_id)

    def get_all_runs(self) -> list[dict]:
        """Get all runs."""
        return list(self._runs.values())

    def update_run(self, run_id: str, **kwargs) -> None:
        """Update run state."""
        if run_id in self._runs:
            self._runs[run_id].update(kwargs)

    def update_from_service(self, run_id: str, service: "EnrichmentService") -> None:
        """Update run state from service status."""
        if run_id not in self._runs:
            return

        try:
            summary = service.get_status()
            self._runs[run_id]["total_rows"] = summary.get("total_rows", 0)
            self._runs[run_id]["lusha"] = summary.get("lusha", {})
            self._runs[run_id]["apollo"] = summary.get("apollo", {})
        except Exception:
            pass

    async def _send_callback(self, run_id: str) -> None:
        """Send callback to Power Automate when enrichment completes or fails."""
        run = self._runs.get(run_id)
        if not run:
            return

        callback_url = run.get("callback_url")
        if not callback_url:
            return

        lusha_data = run.get("lusha", {})
        apollo_data = run.get("apollo", {})

        payload = CallbackPayload(
            run_id=run_id,
            status=run["status"].value if isinstance(run["status"], RunStatus) else run["status"],
            input_file=run.get("input_file"),
            total_rows=run.get("total_rows", 0),
            lusha=APIStatusCounts(
                complete=lusha_data.get("complete", 0),
                error=lusha_data.get("error", 0),
                pending=lusha_data.get("pending", 0),
            ),
            apollo=APIStatusCounts(
                complete=apollo_data.get("complete", 0),
                error=apollo_data.get("error", 0),
                pending=apollo_data.get("pending", 0),
                awaiting_webhook=apollo_data.get("awaiting_webhook", 0),
                timeout=apollo_data.get("timeout", 0),
            ),
            started_at=run["started_at"].isoformat() if run.get("started_at") else None,
            completed_at=run["completed_at"].isoformat() if run.get("completed_at") else None,
            error_message=run.get("error_message"),
            download_url=f"/api/export/{run_id}" if run["status"] == RunStatus.COMPLETED else None,
            user_email=run.get("user_email"),
        )

        try:
            async with httpx.AsyncClient(timeout=30) as client:
                response = await client.post(
                    callback_url,
                    json=payload.model_dump(),
                    headers={"Content-Type": "application/json"},
                )
                logger.info(
                    "Callback sent to %s — status %d", callback_url, response.status_code
                )
        except Exception:
            logger.exception("Failed to send callback to %s", callback_url)

    async def run_enrichment(
        self,
        run_id: str,
        service: "EnrichmentService",
        input_path: Path,
        output_path: Path,
    ) -> None:
        """Run the enrichment pipeline in background."""
        try:
            # Phase 1: Load
            self.update_run(run_id, status=RunStatus.LOADING)
            total = service.load_excel(input_path)
            self.update_run(run_id, total_rows=total)

            # Set repo in app.state for webhook endpoint (integrated into main API)
            from .server import app
            app.state.repo = service.repo
            logger.info("Webhook endpoint ready at /webhook/apollo")

            try:
                # Phase 2: Lusha
                self.update_run(run_id, status=RunStatus.ENRICHING_LUSHA)
                await service.enrich_lusha()
                self.update_from_service(run_id, service)

                # Phase 3: Apollo sync
                self.update_run(run_id, status=RunStatus.ENRICHING_APOLLO)
                await service.enrich_apollo_sync()
                self.update_from_service(run_id, service)

                # Phase 4: Wait for webhooks
                self.update_run(run_id, status=RunStatus.WAITING_WEBHOOKS)
                await service.wait_for_webhooks()
                self.update_from_service(run_id, service)

            finally:
                # Clear repo from app state when done
                app.state.repo = None

            # Phase 5: Export
            self.update_run(run_id, status=RunStatus.EXPORTING)
            service.export_excel(input_path, output_path)

            # Done
            self.update_run(
                run_id,
                status=RunStatus.COMPLETED,
                output_file=str(output_path),
                completed_at=datetime.now(timezone.utc),
            )
            self.update_from_service(run_id, service)
            logger.info("Run %s completed successfully", run_id)

        except Exception as e:
            logger.exception("Run %s failed", run_id)
            self.update_run(
                run_id,
                status=RunStatus.FAILED,
                error_message=str(e),
                completed_at=datetime.now(timezone.utc),
            )

        finally:
            service.close()
            # Send callback to Power Automate (both success and failure)
            await self._send_callback(run_id)

    def start_background_task(
        self,
        run_id: str,
        service: "EnrichmentService",
        input_path: Path,
        output_path: Path,
    ) -> None:
        """Start enrichment as a background asyncio task."""
        task = asyncio.create_task(
            self.run_enrichment(run_id, service, input_path, output_path)
        )
        self._tasks[run_id] = task


# Global runner instance
runner = EnrichmentRunner()
