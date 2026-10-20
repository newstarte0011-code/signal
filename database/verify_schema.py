#!/usr/bin/env python3
"""Read-only verification of the current Signal Analyzer SQLite schema."""
from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

from database.connection import resolve_database_path

# Kept aligned with database/schema.py. This checks required columns, not every
# CHECK constraint or every SQL statement used by the application.
REQUIRED_COLUMNS: dict[str, set[str]] = {
    "channels": {
        "id", "telegram_id", "username", "title", "is_active",
        "first_seen_at", "last_checked_at", "created_at", "updated_at",
    },
    "raw_messages": {
        "id", "channel_id", "telegram_message_id", "message_date",
        "collected_at", "text", "edit_date", "content_hash", "has_media",
        "reply_to_message_id", "collection_status", "created_at", "updated_at",
    },
    "message_versions": {
        "id", "raw_message_id", "version_number", "text", "content_hash",
        "edit_date", "observed_at",
    },
    "signals": {
        "id", "raw_message_id", "signal_index", "instrument", "direction",
        "entry_type", "entry_min", "entry_max", "stop_loss", "take_profit_1",
        "take_profit_2", "take_profit_3", "extraction_method",
        "validation_status", "confidence", "published_at", "extracted_at",
        "created_at", "updated_at",
    },
    "signal_versions": {
        "id", "signal_id", "version_number", "source_message_edit_date",
        "direction", "entry_min", "entry_max", "stop_loss", "take_profit_1",
        "take_profit_2", "take_profit_3", "snapshot_json", "recorded_at",
        "is_original", "notes",
    },
    "candles": {
        "id", "source", "instrument", "timeframe", "candle_open_time",
        "candle_close_time", "open", "high", "low", "close", "volume",
        "downloaded_at",
    },
    "backtest_runs": {
        "id", "run_name", "instrument", "candle_source", "timeframe",
        "start_time", "end_time", "timezone", "spread", "slippage",
        "latency_seconds", "entry_expiry_minutes", "execution_rules_json",
        "status", "started_at", "finished_at", "error_message", "created_at",
    },
}


def inspect_database(path: Path) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    notes: list[str] = []
    if not path.is_file():
        return [f"Database file does not exist: {path}"], notes

    try:
        connection = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA query_only = ON")
    except sqlite3.Error as exc:
        return [f"Could not open database read-only: {exc}"], notes

    try:
        tables = {
            row["name"] for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
            )
        }
        for table, required in REQUIRED_COLUMNS.items():
            if table not in tables:
                errors.append(f"Missing table: {table}")
                continue
            actual = {row["name"] for row in connection.execute(f'PRAGMA table_info("{table}")')}
            missing = sorted(required - actual)
            if missing:
                errors.append(f"{table}: missing columns: {', '.join(missing)}")
            else:
                notes.append(f"{table}: OK ({len(actual)} columns found)")

        for table in ("raw_messages", "message_versions", "signals", "signal_versions"):
            if table in tables:
                violations = connection.execute(f'PRAGMA foreign_key_check("{table}")').fetchall()
                if violations:
                    errors.append(f"{table}: {len(violations)} foreign-key violation(s)")

        integrity = [row[0] for row in connection.execute("PRAGMA quick_check").fetchall()]
        if integrity != ["ok"]:
            errors.append("SQLite quick_check failed: " + "; ".join(integrity))
        else:
            notes.append("SQLite quick_check: OK")
    except sqlite3.Error as exc:
        errors.append(f"SQLite inspection failed: {exc}")
    finally:
        connection.close()

    if not errors:
        notes.append("Required schema verification passed.")
    return errors, notes


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "database", nargs="?", type=Path,
        help="Existing SQLite database (defaults to configured project database)",
    )
    args = parser.parse_args()
    path = args.database.resolve() if args.database else resolve_database_path()
    errors, notes = inspect_database(path)
    for note in notes:
        print(f"[OK/INFO] {note}")
    for error in errors:
        print(f"[ERROR] {error}", file=sys.stderr)
    if errors:
        print("\nSchema verification FAILED. No changes were made.", file=sys.stderr)
        return 1
    print("\nSchema verification PASSED. No changes were made.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
