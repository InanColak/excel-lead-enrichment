# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Purpose

Excel lead enrichment tool that takes an Excel file with contact names and company info, enriches them via **Apollo** and **Lusha** APIs, and writes results back with new columns (email, mobile, direct dial) for each API separately.

## Commands

```bash
# Always use the venv
.venv\Scripts\activate        # Windows
source .venv/bin/activate     # Linux/Mac

# Install dependencies
pip install -e ".[dev]"

# Run enrichment
python -m lead_enrichment enrich data/input/leads.xlsx data/output/leads_enriched.xlsx

# Check status
python -m lead_enrichment status

# Export current state (even if incomplete)
python -m lead_enrichment export data/input/leads.xlsx data/output/leads_partial.xlsx

# Lint
ruff check src/ tests/
ruff format src/ tests/

# Tests
pytest                        # all tests
pytest tests/test_lusha_client.py  # single file
pytest -k "test_name"         # single test by name
```

## Architecture

The system is a **5-phase pipeline** driven by `EnrichmentService` in `orchestrator.py`:

1. **Load** — Excel → SQLite (via OpenAI column auto-detection)
2. **Lusha enrichment** — fully synchronous, bulk POST up to 100/batch
3. **Apollo sync** — email returned immediately, phone webhook registered
4. **Wait for webhooks** — poll SQLite until all Apollo phone data arrives or timeout
5. **Export** — SQLite → enriched Excel with 6 new columns

### Critical: Apollo's Async Webhook

Apollo does **not** return phone numbers synchronously. It POSTs them to a webhook URL minutes later. This drives the entire architecture:

- `webhook/server.py` — FastAPI app receiving `POST /webhook/apollo`
- `webhook/runner.py` — runs uvicorn in a daemon thread alongside main process
- `webhook/handlers.py` — correlates `apollo_person_id` → `row_id` via `webhook_tracking` table
- SQLite with **WAL mode** enables concurrent read/write between main thread and webhook thread

### State Management (SQLite)

SQLite (`db/repository.py`) is the central state store. It enables:
- **Resumability**: crash-safe, picks up where it left off
- **Webhook correlation**: maps `apollo_person_id` to Excel row
- **Progress tracking**: status per row per API (`pending` → `complete`/`error`/`timeout`)

Tables: `enrichment_rows`, `webhook_tracking`, `batch_log`, `run_metadata`

### API Clients

Both in `clients/` extend `BaseAPIClient` which provides httpx + rate limiting:
- **Lusha** (`lusha.py`): GET `/v2/person` (single) or POST `/v2/person` (bulk 100). Synchronous — phone data in response.
- **Apollo** (`apollo.py`): POST `/api/v1/people/bulk_match` (bulk 10). Email sync, phone via webhook.

### Column Detection

`excel/reader.py` uses **OpenAI API** to detect column mappings from headers + sample rows. This handles Excel files in any language (German, Turkish, English).

## Key Design Decisions

- **Lusha runs first** (Phase 2) because it's fully sync and completes fast
- Apollo `person_id` from sync response is stored in `webhook_tracking` to correlate async phone data
- Phone classification: `utils/phone.py` maps API-specific types to `mobile` (Handynummer) and `direct_dial` (Festnetz/Durchwahl)
- `rate_limiter.py` uses async token-bucket, configured per-API
- `utils/retry.py` handles 429 (Retry-After header) and 5xx with exponential backoff

## Configuration

All config via environment variables prefixed `ENRICHMENT_` or `.env` file. See `.env.example`. Key vars: API keys for Apollo, Lusha, OpenAI; webhook URL and port; rate limits.

## Language Note

Output column names are German: `apollo_handynummer`, `lusha_festnetz_durchwahl`, etc. Code comments and logs are in English.
