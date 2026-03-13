"""FastAPI server for the lead enrichment REST API."""

from __future__ import annotations

import json
import logging
from pathlib import Path

from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse

from ..config import Settings
from ..models import ApolloWebhookPayload
from ..orchestrator import EnrichmentService
from .runner import runner
from .schemas import (
    APIStatusCounts,
    EnrichmentStartResponse,
    EnrichmentStatusResponse,
    ErrorResponse,
    HealthResponse,
    RunListItem,
    RunListResponse,
    RunStatus,
)
from .security import get_current_user

logger = logging.getLogger(__name__)

app = FastAPI(
    title="Lead Enrichment API",
    description="REST API for enriching leads via Apollo and Lusha",
    version="1.0.0",
)

# Enable CORS for dashboard access
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Configure this for production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Directory for uploaded and output files
UPLOAD_DIR = Path("data/uploads")
OUTPUT_DIR = Path("data/output")


@app.on_event("startup")
async def startup() -> None:
    """Create required directories on startup."""
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    logger.info("Lead Enrichment API started")


@app.get("/health", response_model=HealthResponse, tags=["Health"])
async def health_check() -> HealthResponse:
    """Health check endpoint."""
    return HealthResponse()


@app.post(
    "/api/enrich",
    response_model=EnrichmentStartResponse,
    responses={400: {"model": ErrorResponse}, 500: {"model": ErrorResponse}},
    tags=["Enrichment"],
)
async def start_enrichment(
    request: Request,
    file: UploadFile | None = File(default=None),
    file_base64: str | None = Form(default=None),
    filename: str | None = Form(default=None),
    callback_url: str | None = Form(
        default=None,
        description="Power Automate trigger URL for completion/failure notification",
    ),
    user_email: str | None = Form(
        default=None,
        description="Email of the user who uploaded the file (for Teams notification)",
    ),
    current_user: dict = Depends(get_current_user),
) -> EnrichmentStartResponse:
    """Start a new enrichment job.

    Upload an Excel file (.xlsx) containing leads to enrich.
    Accepts either:
      - file: standard multipart file upload
      - file_base64 + filename: base64-encoded file (for Power Automate)
    """
    import base64

    # Determine file content and name
    if file_base64:
        # Power Automate sends base64-encoded file content
        actual_filename = filename or "upload.xlsx"
        if not actual_filename.endswith(".xlsx"):
            raise HTTPException(
                status_code=400, detail="File must be an Excel file (.xlsx)"
            )
        try:
            content = base64.b64decode(file_base64)
        except Exception:
            raise HTTPException(
                status_code=400, detail="Invalid base64 file content"
            )
    elif file:
        actual_filename = file.filename or "upload.xlsx"
        if not actual_filename.endswith(".xlsx"):
            raise HTTPException(
                status_code=400, detail="File must be an Excel file (.xlsx)"
            )
        content = await file.read()
    else:
        raise HTTPException(
            status_code=400, detail="No file provided. Send 'file' or 'file_base64'."
        )

    # Sanitize filename to prevent path traversal
    actual_filename = Path(actual_filename).name
    if not actual_filename or actual_filename.startswith("."):
        actual_filename = "upload.xlsx"

    try:
        settings = Settings()  # type: ignore[call-arg]
    except Exception as e:
        logger.error("Configuration error: %s", e)
        raise HTTPException(status_code=500, detail=f"Server configuration error: {e}")

    # Create run
    run_id = runner.create_run(
        actual_filename, callback_url=callback_url, user_email=user_email
    )

    # Save uploaded file
    input_path = UPLOAD_DIR / f"{run_id}_{actual_filename}"
    output_path = OUTPUT_DIR / f"{run_id}_enriched.xlsx"

    try:
        with open(input_path, "wb") as f:
            f.write(content)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to save file: {e}")

    # Each run gets its own isolated database to prevent data leakage
    run_db_path = Path("data") / f"enrichment_{run_id}.db"
    settings = settings.model_copy(update={"db_path": run_db_path})

    # Create service and start background task
    service = EnrichmentService(settings)
    runner.start_background_task(run_id, service, input_path, output_path)

    return EnrichmentStartResponse(
        run_id=run_id,
        status=RunStatus.PENDING,
        message=f"Enrichment started. Check status at /api/status/{run_id}",
    )


@app.get(
    "/api/status/{run_id}",
    response_model=EnrichmentStatusResponse,
    responses={404: {"model": ErrorResponse}},
    tags=["Enrichment"],
)
async def get_status(
    run_id: str,
    current_user: dict = Depends(get_current_user),
) -> EnrichmentStatusResponse:
    """Get the status of an enrichment job."""
    run = runner.get_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail=f"Run '{run_id}' not found")

    lusha_data = run.get("lusha", {})
    apollo_data = run.get("apollo", {})

    return EnrichmentStatusResponse(
        run_id=run["run_id"],
        status=run["status"],
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
        started_at=run.get("started_at"),
        completed_at=run.get("completed_at"),
        error_message=run.get("error_message"),
        output_file=run.get("output_file"),
    )


@app.get(
    "/api/export/{run_id}",
    responses={
        404: {"model": ErrorResponse},
        400: {"model": ErrorResponse},
    },
    tags=["Enrichment"],
)
async def download_result(
    run_id: str,
    current_user: dict = Depends(get_current_user),
) -> FileResponse:
    """Download the enriched Excel file for a completed run."""
    run = runner.get_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail=f"Run '{run_id}' not found")

    if run["status"] != RunStatus.COMPLETED:
        raise HTTPException(
            status_code=400,
            detail=f"Run is not completed. Current status: {run['status']}",
        )

    output_file = run.get("output_file")
    if not output_file or not Path(output_file).exists():
        raise HTTPException(status_code=404, detail="Output file not found")

    return FileResponse(
        path=output_file,
        filename=f"enriched_{run_id}.xlsx",
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


@app.get(
    "/api/runs",
    response_model=RunListResponse,
    tags=["Enrichment"],
)
async def list_runs(
    current_user: dict = Depends(get_current_user),
) -> RunListResponse:
    """List all enrichment runs."""
    runs = runner.get_all_runs()
    items = [
        RunListItem(
            run_id=r["run_id"],
            status=r["status"],
            total_rows=r.get("total_rows", 0),
            input_file=r.get("input_file"),
            started_at=r.get("started_at"),
            completed_at=r.get("completed_at"),
        )
        for r in runs
    ]
    return RunListResponse(runs=items)


# ──────────────────────────────────────────────────────────────────
# Apollo Webhook Endpoint (integrated into main API)
# ──────────────────────────────────────────────────────────────────

@app.post("/webhook/apollo", tags=["Webhook"])
async def receive_apollo_webhook(request: Request) -> JSONResponse:
    """Receive phone number data from Apollo.

    Apollo POSTs this payload asynchronously after a people/match call
    with reveal_phone_number=true. Routes each person to the correct
    run's database by looking up apollo_person_id across active repos.
    """
    from ..utils.phone import classify_apollo_phones

    body = await request.json()
    logger.info("Received Apollo webhook payload")

    try:
        payload = ApolloWebhookPayload.model_validate(body)
    except Exception:
        logger.exception("Error parsing Apollo webhook payload")
        return JSONResponse({"status": "error"}, status_code=200)

    processed = 0
    for person in payload.people:
        person_id = person.id
        if not person_id:
            logger.warning("Webhook person has no ID, skipping")
            continue

        # Find the correct repo for this person across all active runs
        repo = runner.find_repo_for_person(person_id)
        if repo is None:
            logger.warning(
                "No active run has webhook_tracking for apollo_person_id=%s",
                person_id,
            )
            continue

        raw_payload = json.dumps(person.model_dump(), ensure_ascii=False, default=str)
        row_id = repo.mark_webhook_received(person_id, payload=raw_payload)
        if row_id is None:
            continue

        phones = classify_apollo_phones(person.phone_numbers)
        repo.update_apollo_phone_result(
            row_id,
            mobile=phones["mobile"],
            direct=phones["direct_dial"],
            raw_json=raw_payload,
        )
        logger.info(
            "Updated row %d with Apollo phones: mobile=%s, direct=%s",
            row_id,
            phones["mobile"],
            phones["direct_dial"],
        )
        processed += 1

    logger.info("Processed %d person(s) from webhook", processed)
    return JSONResponse({"status": "received", "processed": processed})


@app.get("/webhook/apollo/health", tags=["Webhook"])
async def webhook_health() -> dict:
    """Health check for webhook endpoint."""
    return {"status": "ok", "webhook": "apollo"}


# ──────────────────────────────────────────────────────────────────
# Entry point for running the API server directly
# ──────────────────────────────────────────────────────────────────

def run_server(host: str = "0.0.0.0", port: int = 8000) -> None:
    """Run the API server with uvicorn."""
    import uvicorn

    uvicorn.run(app, host=host, port=port)


if __name__ == "__main__":
    import logging

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    run_server()
