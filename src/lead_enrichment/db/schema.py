"""SQLite schema definitions and initialization."""

import sqlite3

SCHEMA_SQL = """
-- One row per person from the input Excel file
CREATE TABLE IF NOT EXISTS enrichment_rows (
    row_id          INTEGER PRIMARY KEY,
    first_name      TEXT NOT NULL,
    last_name       TEXT NOT NULL,
    company         TEXT NOT NULL,

    -- Lusha results
    lusha_status    TEXT NOT NULL DEFAULT 'pending',
    lusha_email     TEXT,
    lusha_mobile    TEXT,
    lusha_direct    TEXT,
    lusha_error     TEXT,
    lusha_raw       TEXT,

    -- Apollo results
    apollo_status   TEXT NOT NULL DEFAULT 'pending',
    apollo_email    TEXT,
    apollo_mobile   TEXT,
    apollo_direct   TEXT,
    apollo_person_id TEXT,
    apollo_error    TEXT,
    apollo_raw      TEXT,

    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Tracks expected webhook callbacks from Apollo
CREATE TABLE IF NOT EXISTS webhook_tracking (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    apollo_person_id TEXT NOT NULL,
    row_id           INTEGER NOT NULL REFERENCES enrichment_rows(row_id),
    batch_id         TEXT,
    submitted_at     TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    received_at      TIMESTAMP,
    payload          TEXT,
    UNIQUE(apollo_person_id)
);

-- Logs every API batch call for debugging and rate-limit tracking
CREATE TABLE IF NOT EXISTS batch_log (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    api         TEXT NOT NULL,
    batch_id    TEXT NOT NULL,
    row_ids     TEXT NOT NULL,
    status      TEXT NOT NULL DEFAULT 'submitted',
    request_at  TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    response_at TIMESTAMP,
    http_status INTEGER,
    error       TEXT
);

-- Key-value store for run-level metadata
CREATE TABLE IF NOT EXISTS run_metadata (
    key   TEXT PRIMARY KEY,
    value TEXT
);

CREATE INDEX IF NOT EXISTS idx_enrichment_apollo_status
    ON enrichment_rows(apollo_status);

CREATE INDEX IF NOT EXISTS idx_enrichment_lusha_status
    ON enrichment_rows(lusha_status);

CREATE INDEX IF NOT EXISTS idx_webhook_received
    ON webhook_tracking(received_at);

CREATE INDEX IF NOT EXISTS idx_webhook_person_id
    ON webhook_tracking(apollo_person_id);
"""


def initialize_schema(conn: sqlite3.Connection) -> None:
    """Create all tables and indexes if they don't exist."""
    conn.executescript(SCHEMA_SQL)
