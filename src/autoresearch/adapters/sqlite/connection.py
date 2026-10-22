"""SQLite connection setup kept separate from repositories."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from autoresearch.adapters.sqlite.migrations import migrate


def open_database(path: str | Path) -> sqlite3.Connection:
    if str(path) != ":memory:":
        database = Path(path)
        database.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path, timeout=5.0, isolation_level=None)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys=ON")
    connection.execute("PRAGMA busy_timeout=5000")
    if str(path) != ":memory:":
        connection.execute("PRAGMA journal_mode=WAL")
    migrate(connection)
    return connection
