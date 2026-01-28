"""Data access layer for enrichment state management."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from .connection import create_connection
from .schema import initialize_schema


@dataclass
class EnrichmentRow:
    """A single person's enrichment state."""

    row_id: int
    first_name: str
    last_name: str
    company: str
    lusha_status: str
    lusha_email: str | None
    lusha_mobile: str | None
    lusha_direct: str | None
    apollo_status: str
    apollo_email: str | None
    apollo_mobile: str | None
    apollo_direct: str | None
    apollo_person_id: str | None


class Repository:
    """CRUD operations for enrichment state stored in SQLite."""

    def __init__(self, db_path: Path) -> None:
        self._conn = create_connection(db_path)
        initialize_schema(self._conn)

    @property
    def connection(self) -> sqlite3.Connection:
        return self._conn

    def close(self) -> None:
        self._conn.close()

    # ── Row loading ──────────────────────────────────────────────

    def upsert_row(
        self, row_id: int, first_name: str, last_name: str, company: str
    ) -> None:
        """Insert a row or skip if it already exists (idempotent load)."""
        self._conn.execute(
            """
            INSERT OR IGNORE INTO enrichment_rows (row_id, first_name, last_name, company)
            VALUES (?, ?, ?, ?)
            """,
            (row_id, first_name, last_name, company),
        )
        self._conn.commit()

    def upsert_rows_bulk(
        self, rows: list[tuple[int, str, str, str]]
    ) -> None:
        """Bulk insert rows. Each tuple: (row_id, first_name, last_name, company)."""
        self._conn.executemany(
            """
            INSERT OR IGNORE INTO enrichment_rows (row_id, first_name, last_name, company)
            VALUES (?, ?, ?, ?)
            """,
            rows,
        )
        self._conn.commit()

    # ── Querying ─────────────────────────────────────────────────

    def get_rows_by_status(
        self, api: str, status: str, limit: int | None = None
    ) -> list[EnrichmentRow]:
        """Get rows filtered by API status. api is 'lusha' or 'apollo'."""
        col = f"{api}_status"
        query = f"""
            SELECT row_id, first_name, last_name, company,
                   lusha_status, lusha_email, lusha_mobile, lusha_direct,
                   apollo_status, apollo_email, apollo_mobile, apollo_direct,
                   apollo_person_id
            FROM enrichment_rows WHERE {col} = ?
            ORDER BY row_id
        """
        if limit:
            query += f" LIMIT {limit}"
        rows = self._conn.execute(query, (status,)).fetchall()
        return [EnrichmentRow(*r) for r in rows]

    def get_all_rows(self) -> list[EnrichmentRow]:
        """Get all rows ordered by row_id."""
        rows = self._conn.execute(
            """
            SELECT row_id, first_name, last_name, company,
                   lusha_status, lusha_email, lusha_mobile, lusha_direct,
                   apollo_status, apollo_email, apollo_mobile, apollo_direct,
                   apollo_person_id
            FROM enrichment_rows ORDER BY row_id
            """
        ).fetchall()
        return [EnrichmentRow(*r) for r in rows]

    def total_row_count(self) -> int:
        result = self._conn.execute("SELECT COUNT(*) FROM enrichment_rows").fetchone()
        return result[0]

    # ── Lusha updates ────────────────────────────────────────────

    def update_lusha_result(
        self,
        row_id: int,
        *,
        status: str,
        email: str | None = None,
        mobile: str | None = None,
        direct: str | None = None,
        error: str | None = None,
        raw_json: str | None = None,
    ) -> None:
        self._conn.execute(
            """
            UPDATE enrichment_rows
            SET lusha_status = ?, lusha_email = ?, lusha_mobile = ?,
                lusha_direct = ?, lusha_error = ?, lusha_raw = ?,
                updated_at = ?
            WHERE row_id = ?
            """,
            (status, email, mobile, direct, error, raw_json, _now(), row_id),
        )
        self._conn.commit()

    # ── Apollo updates ───────────────────────────────────────────

    def update_apollo_sync_result(
        self,
        row_id: int,
        *,
        status: str,
        email: str | None = None,
        person_id: str | None = None,
        error: str | None = None,
        raw_json: str | None = None,
    ) -> None:
        """Update with Apollo's synchronous response (email, person_id)."""
        self._conn.execute(
            """
            UPDATE enrichment_rows
            SET apollo_status = ?, apollo_email = ?, apollo_person_id = ?,
                apollo_error = ?, apollo_raw = ?, updated_at = ?
            WHERE row_id = ?
            """,
            (status, email, person_id, error, raw_json, _now(), row_id),
        )
        self._conn.commit()

    def update_apollo_phone_result(
        self,
        row_id: int,
        *,
        mobile: str | None = None,
        direct: str | None = None,
        raw_json: str | None = None,
    ) -> None:
        """Update with Apollo's webhook phone data."""
        self._conn.execute(
            """
            UPDATE enrichment_rows
            SET apollo_mobile = ?, apollo_direct = ?, apollo_status = 'complete',
                apollo_raw = COALESCE(apollo_raw || ' | ' || ?, apollo_raw),
                updated_at = ?
            WHERE row_id = ?
            """,
            (mobile, direct, raw_json, _now(), row_id),
        )
        self._conn.commit()

    # ── Webhook tracking ─────────────────────────────────────────

    def create_webhook_tracking(
        self, apollo_person_id: str, row_id: int, batch_id: str | None = None
    ) -> None:
        self._conn.execute(
            """
            INSERT OR IGNORE INTO webhook_tracking (apollo_person_id, row_id, batch_id)
            VALUES (?, ?, ?)
            """,
            (apollo_person_id, row_id, batch_id),
        )
        self._conn.commit()

    def mark_webhook_received(
        self, apollo_person_id: str, payload: str | None = None
    ) -> int | None:
        """Mark a webhook as received and return the associated row_id."""
        row = self._conn.execute(
            "SELECT row_id FROM webhook_tracking WHERE apollo_person_id = ?",
            (apollo_person_id,),
        ).fetchone()
        if not row:
            return None

        self._conn.execute(
            """
            UPDATE webhook_tracking
            SET received_at = ?, payload = ?
            WHERE apollo_person_id = ?
            """,
            (_now(), payload, apollo_person_id),
        )
        self._conn.commit()
        return row[0]

    def get_row_id_by_apollo_person_id(self, apollo_person_id: str) -> int | None:
        row = self._conn.execute(
            "SELECT row_id FROM webhook_tracking WHERE apollo_person_id = ?",
            (apollo_person_id,),
        ).fetchone()
        return row[0] if row else None

    def count_pending_webhooks(self) -> int:
        result = self._conn.execute(
            "SELECT COUNT(*) FROM webhook_tracking WHERE received_at IS NULL"
        ).fetchone()
        return result[0]

    def count_total_webhooks(self) -> int:
        result = self._conn.execute("SELECT COUNT(*) FROM webhook_tracking").fetchone()
        return result[0]

    def mark_webhook_timeouts(self) -> int:
        """Mark all rows still awaiting webhooks as 'timeout'. Returns count."""
        cursor = self._conn.execute(
            """
            UPDATE enrichment_rows
            SET apollo_status = 'timeout', updated_at = ?
            WHERE apollo_status = 'awaiting_webhook'
            """,
            (_now(),),
        )
        self._conn.commit()
        return cursor.rowcount

    # ── Batch logging ────────────────────────────────────────────

    def log_batch(
        self,
        api: str,
        batch_id: str,
        row_ids: list[int],
        *,
        status: str = "submitted",
        http_status: int | None = None,
        error: str | None = None,
    ) -> None:
        self._conn.execute(
            """
            INSERT INTO batch_log (api, batch_id, row_ids, status, http_status, error)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (api, batch_id, json.dumps(row_ids), status, http_status, error),
        )
        self._conn.commit()

    def update_batch_status(
        self,
        batch_id: str,
        *,
        status: str,
        http_status: int | None = None,
        error: str | None = None,
    ) -> None:
        self._conn.execute(
            """
            UPDATE batch_log
            SET status = ?, response_at = ?, http_status = ?, error = ?
            WHERE batch_id = ?
            """,
            (status, _now(), http_status, error, batch_id),
        )
        self._conn.commit()

    # ── Run metadata ─────────────────────────────────────────────

    def set_metadata(self, key: str, value: str) -> None:
        self._conn.execute(
            "INSERT OR REPLACE INTO run_metadata (key, value) VALUES (?, ?)",
            (key, value),
        )
        self._conn.commit()

    def get_metadata(self, key: str) -> str | None:
        row = self._conn.execute(
            "SELECT value FROM run_metadata WHERE key = ?", (key,)
        ).fetchone()
        return row[0] if row else None

    # ── Status summary ───────────────────────────────────────────

    def get_status_summary(self) -> dict:
        """Return a summary of enrichment progress."""
        total = self.total_row_count()
        lusha_complete = self._count_status("lusha_status", "complete")
        lusha_error = self._count_status("lusha_status", "error")
        apollo_complete = self._count_status("apollo_status", "complete")
        apollo_awaiting = self._count_status("apollo_status", "awaiting_webhook")
        apollo_timeout = self._count_status("apollo_status", "timeout")
        apollo_error = self._count_status("apollo_status", "error")

        return {
            "total_rows": total,
            "lusha": {
                "complete": lusha_complete,
                "error": lusha_error,
                "pending": total - lusha_complete - lusha_error,
            },
            "apollo": {
                "complete": apollo_complete,
                "awaiting_webhook": apollo_awaiting,
                "timeout": apollo_timeout,
                "error": apollo_error,
                "pending": total - apollo_complete - apollo_awaiting - apollo_timeout - apollo_error,
            },
        }

    def _count_status(self, column: str, status: str) -> int:
        result = self._conn.execute(
            f"SELECT COUNT(*) FROM enrichment_rows WHERE {column} = ?", (status,)
        ).fetchone()
        return result[0]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()
