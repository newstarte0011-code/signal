#!/usr/bin/env python3
"""
Read-only schema verification for Signal Analyzer.

Checks whether an existing SQLite database contains the tables and
columns required by database/schema.py.

This script never creates, migrates, or modifies the database.
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path


# Required columns must match database/schema.py.
REQUIRED_COLUMNS: dict[str, set[str]] = {
    "channels": {
        "id",
        "telegram_id",
        "username",
        "title",
        "is_active",
        "first_seen_at",
        "last_checked_at",
        "created_at",
        "updated_at",
    },
    "raw_messages": {
        "id",
        "channel_id",
        "telegram_message_id",
        "message_date",
        "collected_at",
        "text",
        "edit_date",
        "content_hash",
        "has_media",
        "reply_to_message_id",
        "collection_status",
        "created_at",
        "updated_at",
    },
    "message_versions": {
        "id",
        "raw_message_id",
        "version_number",
        "text",
        "content_hash",
        "edit_date",
        "observed_at",
    },
    "signals": {
        "id",
        "raw_message_id",
        "signal_index",
        "instrument",
        "direction",
        "entry_type",
        "entry_min",
        "entry_max",
        "stop_loss",
        "take_profit_1",
        "take_profit_2",
        "take_profit_3",
        "extraction_method",
        "validation_status",
        "confidence",
        "published_at",
        "extracted_at",
        "created_at",
        "updated_at",
    },
    "signal_versions": {
        "id",
        "signal_id",
        "version_number",
        "source_message_edit_date",
        "direction",
        "entry_min",
        "entry_max",
        "stop_loss",
        "take_profit_1",
        "take_profit_2",
        "take_profit_3",
        "snapshot_json",
        "recorded_at",
        "is_original",
        "notes",
    },
    "candles": {
        "id",
        "source",
        "instrument",
        "timeframe",
        "candle_open_time",
        "candle_close_time",
        "open",
        "high",
        "low",
        "close",
        "volume",
        "downloaded_at",
    },
    "backtest_runs": {
        "id",
        "run_name",
        "instrument",
        "candle_source",
        "timeframe",
        "start_time",
        "end_time",
        "timezone",
        "spread",
        "slippage",
        "latency_seconds",
        "entry_expiry_minutes",
        "execution_rules_json",
        "status",
        "started_at",
        "finished_at",
    },
}


def open_database_read_only(path: Path) -> sqlite3.Connection:
    """
    Open an existing SQLite database without allowing writes.
    """

    if not path.is_file():
        raise FileNotFoundError(
            f"Database file does not exist: {path}"
        )

    database_uri = path.resolve().as_uri() + "?mode=ro"

    connection = sqlite3.connect(
        database_uri,
        uri=True,
        timeout=10,
    )
    connection.row_factory = sqlite3.Row

    # Additional protection against accidental writes.
    connection.execute("PRAGMA query_only = ON")

    return connection


def inspect_database(
    database_path: Path,
) -> tuple[list[str], list[str]]:
    """
    Verify required tables and columns.

    Returns:
        (errors, notes)
    """

    errors: list[str] = []
    notes: list[str] = []

    try:
        connection = open_database_read_only(database_path)

    except FileNotFoundError as exc:
        return [str(exc)], notes

    except sqlite3.Error as exc:
        return [
            f"Could not open database in read-only mode: {exc}"
        ], notes

    try:
        table_rows = connection.execute(
            """
            SELECT name
            FROM sqlite_master
            WHERE type = 'table'
              AND name NOT LIKE 'sqlite_%'
            """
        ).fetchall()

        existing_tables = {
            row["name"] for row in table_rows
        }

        for table_name, required_columns in REQUIRED_COLUMNS.items():

            if table_name not in existing_tables:
                errors.append(
                    f"Missing table: {table_name}"
                )
                continue

            column_rows = connection.execute(
                f'PRAGMA table_info("{table_name}")'
            ).fetchall()

            actual_columns = {
                row["name"] for row in column_rows
            }

            missing_columns = sorted(
                required_columns - actual_columns
            )

            if missing_columns:
                errors.append(
                    f"{table_name}: missing columns: "
                    f"{', '.join(missing_columns)}"
                )
                continue

            notes.append(
                f"{table_name}: OK "
                f"({len(actual_columns)} columns found)"
            )

        # Check that foreign-key declarations are syntactically
        # present and report violations in existing data.
        foreign_key_violations = []

        for table_name in (
            "raw_messages",
            "message_versions",
            "signals",
            "signal_versions",
        ):
            if table_name not in existing_tables:
                continue

            try:
                rows = connection.execute(
                    f'PRAGMA foreign_key_check("{table_name}")'
                ).fetchall()

                if rows:
                    foreign_key_violations.append(
                        f"{table_name}: "
                        f"{len(rows)} foreign-key violation(s)"
                    )

            except sqlite3.Error as exc:
                notes.append(
                    f"Could not check foreign keys for "
                    f"{table_name}: {exc}"
                )

        errors.extend(foreign_key_violations)

        # Confirm that SQLite can read the database structure.
        integrity_rows = connection.execute(
            "PRAGMA quick_check"
        ).fetchall()

        integrity_messages = [
            row[0] for row in integrity_rows
        ]

        if integrity_messages != ["ok"]:
            errors.append(
                "SQLite quick_check failed: "
                + "; ".join(integrity_messages)
            )
        else:
            notes.append("SQLite quick_check: OK")

        if not errors:
            notes.append(
                "Required schema verification passed."
            )
            notes.append(
                "This check does not guarantee that all application "
                "queries or repository operations will work."
            )

    except sqlite3.Error as exc:
        errors.append(
            f"SQLite inspection failed: {exc}"
        )

    finally:
        connection.close()

    return errors, notes


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__
    )

    parser.add_argument(
        "database",
        type=Path,
        help="Path to an existing SQLite database",
    )

    args = parser.parse_args()

    errors, notes = inspect_database(args.database)

    for note in notes:
        print(f"[OK/INFO] {note}")

    for error in errors:
        print(
            f"[ERROR] {error}",
            file=sys.stderr,
        )

    if errors:
        print(
            "\nSchema verification FAILED. "
            "No changes were made.",
            file=sys.stderr,
        )
        return 1

    print(
        "\nSchema verification PASSED. "
        "No changes were made."
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
