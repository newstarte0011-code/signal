"""SQLite connection helpers for Signal Analyzer."""
from __future__ import annotations

import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

# This file is <project_root>/database/connection.py.
PROJECT_ROOT = Path(__file__).resolve().parents[1]
# Match config.settings.DATABASE_PATH and the database shipped with the project.
DEFAULT_DATABASE_PATH = PROJECT_ROOT / "data" / "app.db"


def resolve_database_path(database_path: str | Path | None = None) -> Path:
    """Resolve explicit path, environment override, or project default.

    Relative paths are interpreted relative to the project root, not the
    process working directory. The explicit argument takes precedence over
    SIGNAL_DATABASE_PATH.
    """
    raw_path = database_path if database_path is not None else os.getenv("SIGNAL_DATABASE_PATH")
    path = Path(raw_path).expanduser() if raw_path else DEFAULT_DATABASE_PATH
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    return path.resolve()


def _open_connection(database_path: str | Path | None = None) -> sqlite3.Connection:
    path = resolve_database_path(database_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(str(path), timeout=30.0, isolation_level=None)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA busy_timeout = 30000")
    connection.execute("PRAGMA journal_mode = WAL")
    connection.execute("PRAGMA synchronous = NORMAL")
    return connection


@contextmanager
def database_connection(database_path: str | Path | None = None) -> Iterator[sqlite3.Connection]:
    """Yield a configured connection and always close it; no implicit transaction."""
    connection = _open_connection(database_path)
    try:
        yield connection
    finally:
        connection.close()


@contextmanager
def database_transaction(database_path: str | Path | None = None) -> Iterator[sqlite3.Connection]:
    """Commit all operations on success; roll back on any exception."""
    connection = _open_connection(database_path)
    try:
        connection.execute("BEGIN IMMEDIATE")
        try:
            yield connection
        except BaseException:
            connection.rollback()
            raise
        else:
            connection.commit()
    finally:
        connection.close()
