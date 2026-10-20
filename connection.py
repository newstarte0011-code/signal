import logging
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator, Optional

from config.settings import DATABASE_PATH, ensure_directories

logger = logging.getLogger("database.connection")


def get_database_path() -> Path:
    """Return the configured database path."""
    return DATABASE_PATH


def create_connection(
    database_path: Optional[Path] = None,
) -> sqlite3.Connection:
    """Create a configured SQLite connection."""
    path = Path(database_path) if database_path is not None else get_database_path()

    if database_path is None:
        ensure_directories()
    else:
        path.parent.mkdir(parents=True, exist_ok=True)

    connection = None
    try:
        connection = sqlite3.connect(
            str(path),
            timeout=30.0,
            isolation_level=None,
        )
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 30000")
        connection.execute("PRAGMA synchronous = NORMAL")

        # journal_mode is persistent for file-backed databases. Avoid issuing
        # the mode-changing PRAGMA on every connection when WAL is already on.
        current_mode = connection.execute(
            "PRAGMA journal_mode"
        ).fetchone()[0]
        if str(current_mode).lower() != "wal":
            connection.execute("PRAGMA journal_mode = WAL")

        logger.debug("SQLite connection established: %s", path)
        return connection

    except sqlite3.Error:
        if connection is not None:
            connection.close()
        logger.exception("Failed to connect to SQLite database: %s", path)
        raise


@contextmanager
def database_connection(
    database_path: Optional[Path] = None,
) -> Iterator[sqlite3.Connection]:
    """Open a connection and always close it when the context exits."""
    connection = create_connection(database_path)
    try:
        yield connection
    finally:
        connection.close()
        logger.debug("SQLite connection closed.")


@contextmanager
def database_transaction(
    database_path: Optional[Path] = None,
) -> Iterator[sqlite3.Connection]:
    """Commit on success and roll back on any exception."""
    with database_connection(database_path) as connection:
        try:
            connection.execute("BEGIN")
            yield connection
            connection.execute("COMMIT")
            logger.debug("Database transaction committed.")
        except Exception:
            if connection.in_transaction:
                connection.execute("ROLLBACK")
            logger.exception("Database transaction rolled back.")
            raise
