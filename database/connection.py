"""
SQLite connection management for Signal Analyzer.

Database location:
    <project_root>/data/signal_analyzer.db

The database path can be overridden using:
    SIGNAL_DATABASE_PATH=/absolute/or/relative/path.db
"""

from __future__ import annotations

import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator


# connection.py is located in <project_root>/database/.
# parents[1] therefore points to <project_root>.
PROJECT_ROOT = Path(__file__).resolve().parents[1]

DEFAULT_DATABASE_PATH = (
    PROJECT_ROOT / "data" / "signal_analyzer.db"
)


def get_database_path() -> Path:
    """
    Return the configured SQLite database path.

    Relative SIGNAL_DATABASE_PATH values are resolved relative
    to the project root, not the current working directory.
    """

    configured_path = os.getenv("SIGNAL_DATABASE_PATH")

    if not configured_path:
        return DEFAULT_DATABASE_PATH

    path = Path(configured_path).expanduser()

    if not path.is_absolute():
        path = PROJECT_ROOT / path

    return path.resolve()


def get_connection() -> sqlite3.Connection:
    """
    Create and return a SQLite connection.

    The parent directory is created if it does not exist.
    Foreign-key enforcement is enabled for this connection.
    """

    database_path = get_database_path()
    database_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    connection = sqlite3.connect(
        str(database_path),
        timeout=30.0,
    )

    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA busy_timeout = 30000")

    return connection


@contextmanager
def database_transaction() -> Iterator[sqlite3.Connection]:
    """
    Execute operations inside a transaction.

    Commits when the block succeeds and rolls back if an exception
    occurs. The connection is always closed.
    """

    connection = get_connection()

    try:
        with connection:
            yield connection
    finally:
        connection.close()


def initialize_database() -> None:
    """
    Create an empty SQLite database file if needed.

    This function does not create application tables.
    Table creation and migrations belong to schema.py.
    """

    connection = get_connection()
    connection.close()


def get_database_info() -> dict[str, str]:
    """
    Return basic information about the configured database.
    """

    database_path = get_database_path()

    return {
        "project_root": str(PROJECT_ROOT),
        "database_path": str(database_path),
        "database_exists": str(database_path.is_file()),
    }
