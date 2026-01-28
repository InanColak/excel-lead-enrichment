"""SQLite connection factory with WAL mode for concurrent access."""

import sqlite3
from pathlib import Path


def create_connection(db_path: Path) -> sqlite3.Connection:
    """Create a SQLite connection configured for concurrent access.

    Uses WAL (Write-Ahead Logging) mode so the main thread and the webhook
    server thread can read/write simultaneously without blocking each other.
    """
    db_path.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(str(db_path), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn
